import hashlib
import json
import re
from datetime import date, datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from src.config import GEMINI_API_KEY, LLM_MODE
from src.database import get_cursor
from src.transcriber import FileTranscriber

# ---------------------------------------------------------------------------
# Pydantic 스키마
# ---------------------------------------------------------------------------

class ActionItemSchema(BaseModel):
    content: str
    assignee: Optional[str] = None
    due_date: Optional[date] = None
    due_is_inferred: bool = False
    confidence: float = Field(..., ge=0.0, le=1.0)
    source_quote: str
    is_ambiguous: bool = False

    @field_validator("confidence")
    @classmethod
    def round_confidence(cls, v: float) -> float:
        return round(v, 4)


class MinutesSummarySchema(BaseModel):
    summary: str
    decisions: list[str]


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------

def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _normalize_content(content: str) -> str:
    return re.sub(r"\s+", " ", content.strip()).lower()


def _match_utterance_id(source_quote: str, utterances: list[dict]) -> Optional[str]:
    """source_quote를 포함하거나 포함되는 utterance_id 반환."""
    for utt in utterances:
        if source_quote in utt["content"] or utt["content"] in source_quote:
            return utt["utterance_id"]
    return None


# ---------------------------------------------------------------------------
# Mock LLM (기본값 — 결정론적, 외부 호출 0건)
# ---------------------------------------------------------------------------

_MOCK_ACTION_ITEMS_RAW = [
    {
        "content": "구글 SA 캠페인 세팅 완료",
        "assignee": "김민지",
        "due_date": "2026-06-03",
        "due_is_inferred": False,
        "confidence": 0.95,
        "source_quote": "제가 6월 3일까지 캠페인 세팅 완료하겠습니다.",
        "is_ambiguous": False,
    },
    {
        "content": "카카오 DA 성과 리포트 광고주 발송",
        "assignee": "김민지",
        "due_date": "2026-06-01",
        "due_is_inferred": False,
        "confidence": 0.93,
        "source_quote": "오후 3시까지 무조건 발송하겠습니다.",
        "is_ambiguous": False,
    },
    {
        "content": "광고 소재 검수 결과 확인 후 김민지에게 전달",
        "assignee": "홍길동",
        "due_date": "2026-06-02",
        "due_is_inferred": False,
        "confidence": 0.90,
        "source_quote": "피드백 받는 즉시 공유하겠습니다.",
        "is_ambiguous": False,
    },
    {
        "content": "신규 광고주 온보딩 미팅 일정 조율 및 공유",
        "assignee": "홍길동",
        "due_date": None,
        "due_is_inferred": True,
        "confidence": 0.82,
        "source_quote": "이번 주 안으로 일정 조율해서 공유하겠습니다.",
        "is_ambiguous": False,
    },
]

_MOCK_MINUTES_RAW = {
    "summary": (
        "구글 SA 예산 30% 증액 확정으로 캠페인 세팅 일정을 협의하고, "
        "카카오 DA 성과 리포트 당일 발송 일정을 확인했습니다. "
        "소재 검수 결과 공유 흐름과 신규 광고주 온보딩 미팅 일정 조율 담당을 배정했습니다."
    ),
    "decisions": [
        "구글 SA 광고 예산 기존 대비 30% 증액으로 확정",
        "카카오 DA 성과 리포트 당일(6월 1일) 오후 3시까지 발송하기로 결정",
        "신규 광고주 온보딩 미팅 일정을 이번 주 안으로 홍길동이 조율하기로 합의",
    ],
}


# ---------------------------------------------------------------------------
# 프롬프트 빌더
# ---------------------------------------------------------------------------

_DOMAIN_CONTEXT = """[광고 미디어 운영 도메인 약어 사전]
- SA (Search Ads): 검색 광고 (구글/네이버)
- DA (Display Ads): 디스플레이 광고 (배너/카카오 등)
- CPM: 1,000회 노출당 비용
- ROAS: 광고 지출 대비 수익률
- A/B 테스트: 광고 소재·랜딩 비교 실험
- CTA: 클릭 유도 문구 (Call to Action)
- 소재: 광고 크리에이티브 (이미지/영상/텍스트)
- 세팅: 광고 캠페인 설정 및 업로드"""

_NOISE_INSTRUCTIONS = """[잡음 처리 지침]
- "알겠습니다", "네, 맞습니다" 등 단순 수긍·확인 발화는 액션아이템이 아닙니다.
- R&R이 여러 발화에 걸쳐 협의될 때는 최종 명시적 확인 발화를 근거로 삼으세요.
- 담당자가 불명확하면 assignee를 null, is_ambiguous를 true로 설정하세요 (강제 추측 금지).
- 기한이 명시되지 않으면 due_date를 null, due_is_inferred를 false로 설정하세요.
- "이번 주 안으로", "곧" 같은 상대적 기한은 due_is_inferred를 true로 표시하세요."""

_FEW_SHOT = """[few-shot 예시 — R&R 핑퐁 처리]
발화 흐름:
  A: "이 건 누가 담당하죠?"
  B: "저도 괜찮은데..."
  C: "제가 챙길게요. 내일 오후까지 완료하겠습니다."
올바른 추출:
{
  "content": "해당 업무 처리 및 완료",
  "assignee": "C",
  "due_date": "내일 날짜",
  "due_is_inferred": false,
  "confidence": 0.88,
  "source_quote": "제가 챙길게요. 내일 오후까지 완료하겠습니다.",
  "is_ambiguous": false
}
→ 핵심: 최종 명시적 확인 발화(C)를 assignee와 source_quote 근거로 사용"""


def _build_action_items_prompt(utterances_text: str, meeting_date: str, error_hint: str = "") -> str:
    error_section = f"\n[이전 시도 오류 — 반드시 수정]\n{error_hint}\n" if error_hint else ""
    return f"""당신은 광고 미디어 운영 회사의 회의 기록 분석 전문가입니다.
아래 회의 발화록에서 액션아이템을 추출하고 JSON으로 반환하세요.

{_DOMAIN_CONTEXT}

{_NOISE_INSTRUCTIONS}

{_FEW_SHOT}
{error_section}
[출력 형식 — 반드시 준수]
{{
  "action_items": [
    {{
      "content": "액션아이템 내용 (명확하고 구체적으로)",
      "assignee": "담당자 이름 또는 null",
      "due_date": "YYYY-MM-DD 형식 또는 null",
      "due_is_inferred": false,
      "confidence": 0.0~1.0,
      "source_quote": "근거 발화 원문 (그대로 인용)",
      "is_ambiguous": false
    }}
  ]
}}

회의 날짜: {meeting_date}

[발화록]
{utterances_text}"""


def _build_minutes_prompt(utterances_text: str, error_hint: str = "") -> str:
    error_section = f"\n[이전 시도 오류 — 반드시 수정]\n{error_hint}\n" if error_hint else ""
    return f"""당신은 광고 미디어 운영 회사의 회의 기록 분석 전문가입니다.
아래 발화록을 기반으로 회의 요약과 주요 결정사항을 추출하세요.

{_DOMAIN_CONTEXT}
{error_section}
[출력 형식 — 반드시 준수]
{{
  "summary": "3~5문장 회의 요약",
  "decisions": ["결정사항1 (∼하기로 결정/확정)", "결정사항2", ...]
}}

[발화록]
{utterances_text}"""


# ---------------------------------------------------------------------------
# Gemini 호출 (LLM_MODE=real 시만 사용)
# ---------------------------------------------------------------------------

def _call_gemini(prompt: str) -> dict:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
        ),
    )
    response = model.generate_content(prompt)
    return json.loads(response.text)


# ---------------------------------------------------------------------------
# 추출 with 재시도
# ---------------------------------------------------------------------------

def _extract_action_items(utterances_text: str, meeting_date: str) -> list[ActionItemSchema]:
    if LLM_MODE == "mock":
        return [ActionItemSchema.model_validate(item) for item in _MOCK_ACTION_ITEMS_RAW]

    last_error = ""
    for attempt in range(3):
        try:
            prompt = _build_action_items_prompt(utterances_text, meeting_date, last_error)
            raw = _call_gemini(prompt)
            return [ActionItemSchema.model_validate(item) for item in raw["action_items"]]
        except Exception as e:
            last_error = str(e)
            print(f"  액션아이템 추출 재시도 {attempt + 1}/3: {last_error}")

    # 최종 실패 폴백: confidence=0 검수 큐 항목
    print("  최종 실패 — confidence=0 폴백 항목 생성")
    return [
        ActionItemSchema(
            content="[추출 실패 — 수동 검수 필요]",
            assignee=None,
            confidence=0.0,
            source_quote="",
            is_ambiguous=True,
        )
    ]


def _extract_minutes(utterances_text: str) -> MinutesSummarySchema:
    if LLM_MODE == "mock":
        return MinutesSummarySchema.model_validate(_MOCK_MINUTES_RAW)

    last_error = ""
    for attempt in range(3):
        try:
            prompt = _build_minutes_prompt(utterances_text, last_error)
            raw = _call_gemini(prompt)
            return MinutesSummarySchema.model_validate(raw)
        except Exception as e:
            last_error = str(e)
            print(f"  회의록 요약 재시도 {attempt + 1}/3: {last_error}")

    return MinutesSummarySchema(summary="[요약 실패 — 수동 검수 필요]", decisions=[])


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------

def _upsert_action_items(meeting_id: str, items: list[ActionItemSchema], utterances: list[dict]) -> None:
    now = datetime.now(timezone.utc)
    with get_cursor(commit=True) as cur:
        for item in items:
            action_item_id = _hash(f"{meeting_id}:{_normalize_content(item.content)}")
            source_utterance_id = _match_utterance_id(item.source_quote, utterances)
            cur.execute(
                """
                INSERT INTO action_items_raw
                    (action_item_id, meeting_id, content, assignee, due_date,
                     due_is_inferred, confidence, source_utterance_id, source_quote,
                     is_ambiguous, status, extracted_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'open', %s)
                ON CONFLICT (action_item_id) DO UPDATE SET
                    content             = EXCLUDED.content,
                    assignee            = EXCLUDED.assignee,
                    due_date            = EXCLUDED.due_date,
                    due_is_inferred     = EXCLUDED.due_is_inferred,
                    confidence          = EXCLUDED.confidence,
                    source_utterance_id = EXCLUDED.source_utterance_id,
                    source_quote        = EXCLUDED.source_quote,
                    is_ambiguous        = EXCLUDED.is_ambiguous,
                    extracted_at        = EXCLUDED.extracted_at
                """,
                (
                    action_item_id,
                    meeting_id,
                    item.content,
                    item.assignee,
                    item.due_date,
                    item.due_is_inferred,
                    item.confidence,
                    source_utterance_id,
                    item.source_quote,
                    item.is_ambiguous,
                    now,
                ),
            )
    print(f"  액션아이템 upsert 완료: {len(items)}건")


def _upsert_minutes(meeting_id: str, minutes: MinutesSummarySchema) -> None:
    now = datetime.now(timezone.utc)
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO raw_minutes (meeting_id, summary, decisions, extracted_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (meeting_id) DO UPDATE SET
                summary      = EXCLUDED.summary,
                decisions    = EXCLUDED.decisions,
                extracted_at = EXCLUDED.extracted_at
            """,
            (
                meeting_id,
                minutes.summary,
                json.dumps(minutes.decisions, ensure_ascii=False),
                now,
            ),
        )
    print(f"  회의록 upsert 완료: {meeting_id}")


# ---------------------------------------------------------------------------
# 발화 로딩
# ---------------------------------------------------------------------------

def _load_stg_utterances(meeting_id: str) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            "SELECT utterance_id, speaker, content, timestamp "
            "FROM stg_utterances WHERE meeting_id = %s ORDER BY timestamp",
            (meeting_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def _load_meeting_date(meeting_id: str) -> str:
    with get_cursor() as cur:
        cur.execute("SELECT date FROM raw_meetings WHERE meeting_id = %s", (meeting_id,))
        row = cur.fetchone()
        return str(row["date"]) if row else ""


# ---------------------------------------------------------------------------
# 메인 진입점
# ---------------------------------------------------------------------------

def extract_from_meeting(meeting_id: str) -> None:
    print(f"추출 시작: {meeting_id} (LLM_MODE={LLM_MODE})")

    utterances = _load_stg_utterances(meeting_id)
    if not utterances:
        print(f"  stg_utterances에 데이터 없음 — dbt run (staging) 먼저 실행하세요.")
        return

    meeting_date = _load_meeting_date(meeting_id)
    utterances_text = "\n".join(
        f"[{u['speaker']}] {u['content']}" for u in utterances
    )

    action_items = _extract_action_items(utterances_text, meeting_date)
    minutes = _extract_minutes(utterances_text)

    _upsert_action_items(meeting_id, action_items, utterances)
    _upsert_minutes(meeting_id, minutes)
    print(f"추출 완료: {meeting_id}")


if __name__ == "__main__":
    from src.database import init_db
    init_db()
    transcriber = FileTranscriber()
    meeting = transcriber.load("data/sample_meeting.json")
    extract_from_meeting(meeting.meeting_id)
