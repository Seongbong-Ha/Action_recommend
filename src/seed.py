"""
시연용 시드 데이터 적재 스크립트.
2주 분량(4개 회의)의 회의·액션아이템·회의록을 mock 임베딩과 함께 DB에 삽입.
`make seed` 또는 `python -m src.seed`로 실행. 멱등 (재실행 안전).

토픽 설계 (유사 검색 시연):
  meet_seed_01 (5/19) 예산/캠페인 ─┐ 유사 → "예산" 검색 시 함께 상위 노출
  meet_seed_03 (5/26) 성과/예산   ─┘
  meet_seed_02 (5/22) 소재/CTA        별도 클러스터
  meet_seed_04 (5/29) 온보딩/일정     별도 클러스터
"""

import hashlib
import json
import re
from datetime import datetime, timezone

from src.database import get_cursor, init_db
from src.embeddings import topic_vec, _BASE_BUDGET, _BASE_CREATIVE, _BASE_ONBOARD
from src.ingest import ingest_meeting
from src.transcriber import Meeting, Utterance

# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------

def _h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]

def _norm(content: str) -> str:
    return re.sub(r"\s+", " ", content.strip()).lower()

def _action_item_id(meeting_id: str, content: str) -> str:
    return _h(f"{meeting_id}:{_norm(content)}")

# ---------------------------------------------------------------------------
# 시드 회의 데이터
# ---------------------------------------------------------------------------

_MEETINGS = [
    Meeting(
        meeting_id="meet_seed_01",
        title="노바드림 6월 캠페인 예산 사전 정렬",
        date="2026-05-19",
        participants=["박지원(팀장)", "김민지(퍼포먼스)", "홍길동(디자이너)"],
        utterances=[
            Utterance("박지원", "이번 6월 구글 SA 예산을 기존 대비 30% 증액하는 방향으로 확정됐습니다.", "10.0"),
            Utterance("김민지", "증액 예산 기준으로 캠페인 세팅 완료하겠습니다. 5월 23일까지 완료 가능합니다.", "25.0"),
            Utterance("박지원", "캠페인 세팅 이후 QA도 부탁드립니다. 런칭 전에 한 번 더 확인해주세요.", "40.0"),
            Utterance("홍길동", "소재 최종본은 5월 21일 오후에 전달드리겠습니다.", "55.0"),
            Utterance("박지원", "예산 증액 품의서는 제가 이번 주 안으로 올리겠습니다.", "70.0"),
        ],
    ),
    Meeting(
        meeting_id="meet_seed_02",
        title="노바드림 카카오 DA 소재 검수 회의",
        date="2026-05-22",
        participants=["박지원(팀장)", "김민지(퍼포먼스)", "홍길동(디자이너)"],
        utterances=[
            Utterance("박지원", "카카오 DA 소재 1차 시안 검토해봤는데, CTA 문구가 약한 것 같아요.", "10.0"),
            Utterance("홍길동", "CTA 문구 3가지 버전으로 수정해서 내일 오전까지 드릴게요.", "20.0"),
            Utterance("김민지", "A/B 테스트 설정은 소재 확정 이후 바로 진행하겠습니다.", "35.0"),
            Utterance("박지원", "2차 소재 최종 컨펌은 제가 5월 24일까지 드리겠습니다.", "50.0"),
            Utterance("홍길동", "컨펌 후 광고 시스템 업로드까지 당일 처리 가능합니다.", "65.0"),
        ],
    ),
    Meeting(
        meeting_id="meet_seed_03",
        title="노바드림 5월 성과 리뷰 및 예산 재배분",
        date="2026-05-26",
        participants=["박지원(팀장)", "김민지(퍼포먼스)"],
        utterances=[
            Utterance("박지원", "5월 구글 SA ROAS가 목표 대비 15% 하락했습니다. 원인 분석이 필요합니다.", "10.0"),
            Utterance("김민지", "키워드 입찰가 조정이 원인으로 보입니다. 분석 리포트를 5월 28일까지 작성하겠습니다.", "25.0"),
            Utterance("박지원", "카카오 DA는 성과가 좋으니 구글 SA에서 예산 일부를 카카오 DA로 재배분하는 방향으로 검토해주세요.", "40.0"),
            Utterance("김민지", "예산 재배분 시뮬레이션 자료 만들어서 5월 29일 오전까지 공유드리겠습니다.", "55.0"),
            Utterance("박지원", "재배분 확정 후 실제 반영은 제가 승인 처리하겠습니다.", "70.0"),
        ],
    ),
    Meeting(
        meeting_id="meet_seed_04",
        title="신규 광고주 스타트웰 온보딩 킥오프",
        date="2026-05-29",
        participants=["박지원(팀장)", "이수아(AE)"],
        utterances=[
            Utterance("박지원", "스타트웰 온보딩 킥오프 미팅 일정을 이번 주 내로 잡아주세요.", "10.0"),
            Utterance("이수아", "6월 2일 오후 2시로 제안드리겠습니다. 오늘 중으로 일정 공유하겠습니다.", "20.0"),
            Utterance("박지원", "온보딩 자료 — 계약서, 브리프, 미디어 플랜 템플릿 — 은 이수아님이 준비해주세요.", "35.0"),
            Utterance("이수아", "6월 1일까지 모든 자료 준비 완료하겠습니다.", "50.0"),
            Utterance("박지원", "킥오프 이후 광고주 채널 세팅은 김민지님과 협의해서 진행해주세요.", "65.0"),
        ],
    ),
]

# ---------------------------------------------------------------------------
# 시드 액션아이템
# ---------------------------------------------------------------------------

_ACTION_ITEMS: dict[str, list[dict]] = {
    "meet_seed_01": [
        {"content": "구글 SA 캠페인 세팅 완료 (예산 30% 증액 기준)", "assignee": "김민지", "due_date": "2026-05-23", "due_is_inferred": False, "confidence": 0.95, "is_ambiguous": False, "related_campaign": "구글 SA", "source_quote": "증액 예산 기준으로 캠페인 세팅 완료하겠습니다. 5월 23일까지 완료 가능합니다."},
        {"content": "소재 최종본 전달", "assignee": "홍길동", "due_date": "2026-05-21", "due_is_inferred": False, "confidence": 0.92, "is_ambiguous": False, "related_campaign": None, "source_quote": "소재 최종본은 5월 21일 오후에 전달드리겠습니다."},
        {"content": "예산 증액 품의서 제출", "assignee": "박지원", "due_date": None, "due_is_inferred": True, "confidence": 0.88, "is_ambiguous": False, "related_campaign": "구글 SA", "source_quote": "예산 증액 품의서는 제가 이번 주 안으로 올리겠습니다."},
    ],
    "meet_seed_02": [
        {"content": "카카오 DA CTA 문구 3가지 버전 수정", "assignee": "홍길동", "due_date": "2026-05-23", "due_is_inferred": False, "confidence": 0.94, "is_ambiguous": False, "related_campaign": "카카오 DA", "source_quote": "CTA 문구 3가지 버전으로 수정해서 내일 오전까지 드릴게요."},
        {"content": "카카오 DA A/B 테스트 설정 및 진행", "assignee": "김민지", "due_date": None, "due_is_inferred": False, "confidence": 0.87, "is_ambiguous": False, "related_campaign": "카카오 DA", "source_quote": "A/B 테스트 설정은 소재 확정 이후 바로 진행하겠습니다."},
        {"content": "소재 2차 최종 컨펌", "assignee": "박지원", "due_date": "2026-05-24", "due_is_inferred": False, "confidence": 0.91, "is_ambiguous": False, "related_campaign": "카카오 DA", "source_quote": "2차 소재 최종 컨펌은 제가 5월 24일까지 드리겠습니다."},
    ],
    "meet_seed_03": [
        {"content": "구글 SA ROAS 하락 원인 분석 리포트 작성", "assignee": "김민지", "due_date": "2026-05-28", "due_is_inferred": False, "confidence": 0.93, "is_ambiguous": False, "related_campaign": "구글 SA", "source_quote": "분석 리포트를 5월 28일까지 작성하겠습니다."},
        {"content": "카카오 DA 예산 재배분 시뮬레이션 자료 공유", "assignee": "김민지", "due_date": "2026-05-29", "due_is_inferred": False, "confidence": 0.90, "is_ambiguous": False, "related_campaign": "카카오 DA", "source_quote": "예산 재배분 시뮬레이션 자료 만들어서 5월 29일 오전까지 공유드리겠습니다."},
        {"content": "예산 재배분 최종 승인 처리", "assignee": "박지원", "due_date": None, "due_is_inferred": True, "confidence": 0.82, "is_ambiguous": False, "related_campaign": None, "source_quote": "재배분 확정 후 실제 반영은 제가 승인 처리하겠습니다."},
    ],
    "meet_seed_04": [
        {"content": "스타트웰 온보딩 킥오프 미팅 일정 제안 및 공유", "assignee": "이수아", "due_date": "2026-05-29", "due_is_inferred": False, "confidence": 0.96, "is_ambiguous": False, "related_campaign": None, "source_quote": "6월 2일 오후 2시로 제안드리겠습니다. 오늘 중으로 일정 공유하겠습니다."},
        {"content": "온보딩 자료 준비 (계약서, 브리프, 미디어 플랜 템플릿)", "assignee": "이수아", "due_date": "2026-06-01", "due_is_inferred": False, "confidence": 0.94, "is_ambiguous": False, "related_campaign": None, "source_quote": "6월 1일까지 모든 자료 준비 완료하겠습니다."},
        {"content": "광고주 채널 세팅 (김민지와 협의)", "assignee": "이수아", "due_date": None, "due_is_inferred": True, "confidence": 0.78, "is_ambiguous": False, "related_campaign": None, "source_quote": "킥오프 이후 광고주 채널 세팅은 김민지님과 협의해서 진행해주세요."},
    ],
}

# ---------------------------------------------------------------------------
# 시드 회의록 + 임베딩
# meet_seed_01, 03 → _BASE_BUDGET 클러스터 (유사 검색 시 함께 노출)
# meet_seed_02    → _BASE_CREATIVE 클러스터
# meet_seed_04    → _BASE_ONBOARD 클러스터
# ---------------------------------------------------------------------------

_MINUTES: dict[str, dict] = {
    "meet_seed_01": {
        "summary": "6월 구글 SA 예산 30% 증액을 확정하고 캠페인 세팅 일정을 조율했습니다. 소재 최종본 전달 및 예산 품의서 제출 일정을 합의했습니다.",
        "decisions": [
            "구글 SA 광고 예산 기존 대비 30% 증액 확정",
            "캠페인 세팅 5월 23일까지 완료",
            "소재 최종본 5월 21일 전달",
        ],
        "embedding": topic_vec(_BASE_BUDGET, seed=1),
    },
    "meet_seed_02": {
        "summary": "카카오 DA 소재 1차 시안 검토 후 CTA 문구 개선 방향을 결정했습니다. A/B 테스트 계획과 2차 최종 컨펌 일정을 확정했습니다.",
        "decisions": [
            "CTA 문구 3가지 버전 수정 후 5월 23일 제출",
            "소재 2차 컨펌 5월 24일까지 완료",
            "컨펌 즉시 A/B 테스트 설정 진행",
        ],
        "embedding": topic_vec(_BASE_CREATIVE, seed=2),
    },
    "meet_seed_03": {
        "summary": "5월 구글 SA ROAS 목표 대비 15% 하락을 확인하고 원인 분석 및 예산 재배분 방향을 논의했습니다.",
        "decisions": [
            "구글 SA ROAS 하락 원인 분석 리포트 5월 28일 제출",
            "구글 SA → 카카오 DA 예산 재배분 검토",
            "재배분 시뮬레이션 자료 5월 29일 공유",
        ],
        "embedding": topic_vec(_BASE_BUDGET, seed=3),  # seed_01과 같은 토픽 → 유사
    },
    "meet_seed_04": {
        "summary": "신규 광고주 스타트웰 온보딩 킥오프 일정을 6월 2일로 확정하고 사전 준비 자료 및 역할을 배분했습니다.",
        "decisions": [
            "온보딩 킥오프 미팅 6월 2일 오후 2시 확정",
            "온보딩 자료 6월 1일까지 이수아 준비",
            "킥오프 이후 채널 세팅은 이수아·김민지 협의",
        ],
        "embedding": topic_vec(_BASE_ONBOARD, seed=4),
    },
}

# ---------------------------------------------------------------------------
# DB 삽입 함수
# ---------------------------------------------------------------------------

def _seed_action_items(meeting_id: str) -> None:
    now = datetime.now(timezone.utc)
    items = _ACTION_ITEMS[meeting_id]
    with get_cursor(commit=True) as cur:
        for item in items:
            aid = _action_item_id(meeting_id, item["content"])
            cur.execute(
                """
                INSERT INTO raw_action_items
                    (action_item_id, meeting_id, content, assignee, due_date,
                     due_is_inferred, confidence, source_quote,
                     is_ambiguous, related_campaign, status, extracted_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'open', %s)
                ON CONFLICT (action_item_id) DO NOTHING
                """,
                (
                    aid, meeting_id,
                    item["content"], item.get("assignee"), item.get("due_date"),
                    item.get("due_is_inferred", False), item["confidence"],
                    item.get("source_quote"), item.get("is_ambiguous", False),
                    item.get("related_campaign"), now,
                ),
            )


def _seed_minutes(meeting_id: str) -> None:
    now = datetime.now(timezone.utc)
    m = _MINUTES[meeting_id]
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO raw_minutes (meeting_id, summary, decisions, embedding, extracted_at)
            VALUES (%s, %s, %s, %s::vector, %s)
            ON CONFLICT (meeting_id) DO NOTHING
            """,
            (
                meeting_id,
                m["summary"],
                json.dumps(m["decisions"], ensure_ascii=False),
                str(m["embedding"]),
                now,
            ),
        )


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------

def seed_all() -> None:
    init_db()
    for meeting in _MEETINGS:
        ingest_meeting(meeting)
        _seed_action_items(meeting.meeting_id)
        _seed_minutes(meeting.meeting_id)
        print(f"시드 완료: {meeting.meeting_id} ({meeting.title})")
    print(f"총 {len(_MEETINGS)}개 회의 시드 완료.")


if __name__ == "__main__":
    seed_all()
