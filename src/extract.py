import hashlib
import json
import re
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from typing import Optional

import google.generativeai as genai
from pydantic import BaseModel, Field, field_validator

from src.config import GEMINI_API_KEY, LLM_MODE
from src.database import get_cursor
from src.transcriber import FileTranscriber

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

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
    related_campaign: Optional[str] = None

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
    # ID 생성용: 공백을 단일 스페이스로 정규화 (구글 SA ≠ 구글SA 유지)
    return re.sub(r"\s+", " ", content.strip()).lower()


def _normalize_for_match(s: str) -> str:
    # 매칭용: 공백 전체 제거 (표기 차이 무시)
    return re.sub(r"\s+", "", s.strip().lower())


def _match_utterance_id(source_quote: str, utterances: list[dict]) -> Optional[str]:
    """source_quote와 utterance content를 매칭하여 utterance_id 반환.
    1차: 원문 substring 매칭, 2차: 정규화 substring 매칭, 3차: difflib 유사도 0.6 이상 최고 점수."""
    if not source_quote:
        return None

    norm_quote = _normalize_for_match(source_quote)

    # 1차: 원문 substring (quote가 발화에 포함되는 방향만 허용)
    for utt in utterances:
        if source_quote in utt["content"]:
            return utt["utterance_id"]

    # 2차: 정규화 substring (quote가 발화에 포함되는 방향만 허용)
    for utt in utterances:
        if norm_quote in _normalize_for_match(utt["content"]):
            return utt["utterance_id"]

    # 3차: 유사도 기반 fallback (0.6 임계값)
    best_id, best_score = None, 0.0
    for utt in utterances:
        score = SequenceMatcher(None, norm_quote, _normalize_for_match(utt["content"])).ratio()
        if score > best_score:
            best_score, best_id = score, utt["utterance_id"]
    return best_id if best_score >= 0.6 else None


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
        "related_campaign": "구글 SA",
    },
    {
        "content": "카카오 DA 성과 리포트 광고주 발송",
        "assignee": "김민지",
        "due_date": "2026-06-01",
        "due_is_inferred": False,
        "confidence": 0.93,
        "source_quote": "오후 3시까지 무조건 발송하겠습니다.",
        "is_ambiguous": False,
        "related_campaign": "카카오 DA",
    },
    {
        "content": "광고 소재 검수 결과 확인 후 김민지에게 전달",
        "assignee": "홍길동",
        "due_date": "2026-06-02",
        "due_is_inferred": False,
        "confidence": 0.90,
        "source_quote": "피드백 받는 즉시 공유하겠습니다.",
        "is_ambiguous": False,
        "related_campaign": None,
    },
    {
        "content": "신규 광고주 온보딩 미팅 일정 조율 및 공유",
        "assignee": "홍길동",
        "due_date": None,
        "due_is_inferred": True,
        "confidence": 0.82,
        "source_quote": "이번 주 안으로 일정 조율해서 공유하겠습니다.",
        "is_ambiguous": False,
        "related_campaign": None,
    },
    {
        "content": "광고 소재 방향성 재검토 및 결론 도출",
        "assignee": None,
        "due_date": None,
        "due_is_inferred": False,
        "confidence": 0.42,
        "source_quote": "소재 방향이 좀 흐릿하게 끝난 것 같은데요.",
        "is_ambiguous": True,
        "related_campaign": None,
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
- 단, 화자가 "제가 ~담당이니까", "~팀에서 처리해야 해서" 등 직무·역할 맥락으로 자신이 담당임을 암묵적으로 확인하면 assignee로 인정하세요.
- 기한이 명시되지 않으면 due_date를 null, due_is_inferred를 false로 설정하세요.
- "이번 주 안으로", "곧", "이번 주 금요일까지" 같은 상대적 기한은 due_is_inferred를 true로 표시하세요.
- related_campaign은 발화에서 직접 언급된 캠페인명(예: 구글 SA, 카카오 DA, 네이버 SA)만 추출하고, 언급이 없으면 null로 설정하세요."""

_FEW_SHOT = """[few-shot 예시 1 — R&R 핑퐁: 명시적 최종 확인을 assignee 근거로 사용]
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
  "is_ambiguous": false,
  "related_campaign": null
}
→ 핵심: 최종 명시적 확인 발화(C)를 assignee와 source_quote 근거로 사용

[few-shot 예시 2 — 암묵적 담당자: 직무·역할 맥락 기반 추론]
발화 흐름:
  매니저: "카카오 DA 소재 성과 데이터 정리가 필요한데요."
  김민지: "제가 DA 성과 분석 담당이니까 오늘 EOD까지 정리해드릴게요."
올바른 추출:
{
  "content": "카카오 DA 소재 성과 데이터 정리",
  "assignee": "김민지",
  "due_date": "회의 당일 날짜",
  "due_is_inferred": false,
  "confidence": 0.91,
  "source_quote": "제가 DA 성과 분석 담당이니까 오늘 EOD까지 정리해드릴게요.",
  "is_ambiguous": false,
  "related_campaign": "카카오 DA"
}
→ 핵심: "제가 ~담당이니까" 문맥으로 암묵적 R&R 확인. 발화에서 언급된 캠페인명 추출

[few-shot 예시 3 — 단순 수긍 필터링: 확인·동의 발화는 액션아이템 아님]
발화 흐름:
  A: "구글 SA 예산 30% 증액으로 확정됐죠?"
  B: "네, 맞습니다."
  C: "알겠습니다."
올바른 추출: [] (빈 배열)
→ 핵심: 확인·동의 발화는 태스크가 아님. 아래처럼 추출하면 잘못된 결과:
  WRONG: {"content": "구글 SA 예산 증액 확인", "assignee": "B", ...}

[few-shot 예시 4 — 상대적 기한 + related_campaign 추출]
발화 흐름:
  홍길동: "네이버 SA A/B 테스트 결과를 이번 주 금요일까지 정리해서 공유드릴게요."
올바른 추출:
{
  "content": "네이버 SA A/B 테스트 결과 정리 및 공유",
  "assignee": "홍길동",
  "due_date": null,
  "due_is_inferred": true,
  "confidence": 0.92,
  "source_quote": "네이버 SA A/B 테스트 결과를 이번 주 금요일까지 정리해서 공유드릴게요.",
  "is_ambiguous": false,
  "related_campaign": "네이버 SA"
}
→ 핵심: "이번 주 금요일"은 due_is_inferred=true (회의 날짜 기준 추론 필요). related_campaign은 발화에서 직접 언급된 캠페인명만 추출

[few-shot 예시 5 — 지시형 발화: 팀장이 제3자에게 업무 지시하는 경우]
발화 흐름:
  팀장: "홍길동님이 내일 오후까지 소재 검수 결과 확인하고, 이상 없으면 바로 김민지님한테 전달해주세요."
  홍길동: "알겠습니다. 피드백 받는 즉시 공유하겠습니다."
올바른 추출:
{
  "content": "소재 검수 결과 확인 후 김민지에게 전달",
  "assignee": "홍길동",
  "due_date": null,
  "due_is_inferred": true,
  "confidence": 0.90,
  "source_quote": "알겠습니다. 피드백 받는 즉시 공유하겠습니다.",
  "is_ambiguous": false,
  "related_campaign": null
}
→ 핵심: 팀장의 지시 발화(assignee 명시)와 홍길동의 수락 발화를 조합. source_quote는 최종 수락 발화. "내일 오후까지"는 due_is_inferred=true"""


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
      "is_ambiguous": false,
      "related_campaign": "캠페인명 또는 null"
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
# Gemini 응답 스키마 (response_schema 파라미터로 모델 레벨에서 구조 강제)
# ---------------------------------------------------------------------------

_ACTION_ITEMS_SCHEMA = {
    "type": "object",
    "properties": {
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content":          {"type": "string"},
                    "assignee":         {"type": "string",  "nullable": True},
                    "due_date":         {"type": "string",  "nullable": True},
                    "due_is_inferred":  {"type": "boolean"},
                    "confidence":       {"type": "number"},
                    "source_quote":     {"type": "string"},
                    "is_ambiguous":     {"type": "boolean"},
                    "related_campaign": {"type": "string",  "nullable": True},
                },
                "required": ["content", "confidence", "source_quote", "due_is_inferred", "is_ambiguous"],
            },
        }
    },
    "required": ["action_items"],
}

_MINUTES_SCHEMA = {
    "type": "object",
    "properties": {
        "summary":   {"type": "string"},
        "decisions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "decisions"],
}


# ---------------------------------------------------------------------------
# Gemini 호출 (LLM_MODE=real 시만 사용)
# ---------------------------------------------------------------------------

def _call_gemini(prompt: str, schema: dict) -> dict:
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema=schema,
        ),
    )
    response = model.generate_content(prompt)
    text = response.text
    if not text:
        raise ValueError(f"Gemini 응답이 비어 있습니다. finish_reason={response.candidates[0].finish_reason if response.candidates else 'unknown'}")
    return json.loads(text)


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
            raw = _call_gemini(prompt, _ACTION_ITEMS_SCHEMA)
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
            raw = _call_gemini(prompt, _MINUTES_SCHEMA)
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
                INSERT INTO raw_action_items
                    (action_item_id, meeting_id, content, assignee, due_date,
                     due_is_inferred, confidence, source_utterance_id, source_quote,
                     is_ambiguous, related_campaign, status, extracted_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'open', %s)
                ON CONFLICT (action_item_id) DO UPDATE SET
                    content             = EXCLUDED.content,
                    assignee            = EXCLUDED.assignee,
                    due_date            = EXCLUDED.due_date,
                    due_is_inferred     = EXCLUDED.due_is_inferred,
                    confidence          = EXCLUDED.confidence,
                    source_utterance_id = COALESCE(EXCLUDED.source_utterance_id, raw_action_items.source_utterance_id),
                    source_quote        = EXCLUDED.source_quote,
                    is_ambiguous        = EXCLUDED.is_ambiguous,
                    related_campaign    = EXCLUDED.related_campaign,
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
                    item.related_campaign,
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
            "FROM stg_utterances WHERE meeting_id = %s ORDER BY timestamp NULLS LAST",
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
