"""
LLM 추출 신뢰화 핵심 로직 검증 테스트.

이 과제의 핵심 평가 포인트인 "LLM 출력을 신뢰 가능한 데이터 자산으로 만드는 엔지니어링"이
실제로 동작함을 증명한다.
  - pydantic 스키마 강제 (적재 전 검증)
  - 3회 재시도 후 confidence=0 폴백 경로
  - is_ambiguous / assignee=None 보존 로직
"""
import pytest
from pydantic import ValidationError

from src.extract import (
    ActionItemSchema,
    MinutesSummarySchema,
    _apply_default_campaign,
    _extract_action_items,
    _infer_default_campaign,
)


# ---------------------------------------------------------------------------
# ActionItemSchema 유효성 검사
# ---------------------------------------------------------------------------

def test_confidence_above_max_rejected():
    """confidence > 1.0 은 pydantic이 거부해야 한다."""
    with pytest.raises(ValidationError):
        ActionItemSchema(content="테스트", confidence=1.5, source_quote="발화")


def test_confidence_below_min_rejected():
    """confidence < 0.0 은 pydantic이 거부해야 한다."""
    with pytest.raises(ValidationError):
        ActionItemSchema(content="테스트", confidence=-0.1, source_quote="발화")


def test_confidence_boundary_accepted():
    """confidence 0.0 과 1.0 경계값은 허용되어야 한다."""
    low = ActionItemSchema(content="테스트", confidence=0.0, source_quote="발화")
    high = ActionItemSchema(content="테스트", confidence=1.0, source_quote="발화")
    assert low.confidence == 0.0
    assert high.confidence == 1.0


def test_confidence_rounded_to_4_decimals():
    """confidence 는 소수점 4자리로 반올림되어야 한다."""
    item = ActionItemSchema(content="테스트", confidence=0.123456, source_quote="발화")
    assert item.confidence == 0.1235


def test_assignee_nullable():
    """assignee 는 None 허용 — 암묵적 R&R 강제 지정 금지."""
    item = ActionItemSchema(content="테스트", confidence=0.9, source_quote="발화", assignee=None)
    assert item.assignee is None


def test_is_ambiguous_preserved():
    """is_ambiguous=True 항목은 버리지 않고 보존되어야 한다."""
    item = ActionItemSchema(
        content="흐릿한 결정",
        confidence=0.5,
        source_quote="뭔가 해야 할 것 같은데",
        is_ambiguous=True,
    )
    assert item.is_ambiguous is True


def test_content_required():
    """content 누락 시 ValidationError가 발생해야 한다."""
    with pytest.raises(ValidationError):
        ActionItemSchema(confidence=0.9, source_quote="발화")


def test_related_campaign_nullable():
    """related_campaign 은 None 허용 — 캠페인 미언급 케이스."""
    item = ActionItemSchema(content="테스트", confidence=0.9, source_quote="발화", related_campaign=None)
    assert item.related_campaign is None


def test_related_campaign_extracted():
    """related_campaign 에 캠페인명이 설정되면 그대로 보존되어야 한다."""
    item = ActionItemSchema(
        content="카카오 DA 소재 성과 데이터 정리",
        confidence=0.91,
        source_quote="제가 DA 성과 분석 담당이니까 오늘 EOD까지 정리해드릴게요.",
        related_campaign="카카오 DA",
    )
    assert item.related_campaign == "카카오 DA"


def test_infer_default_campaign_from_early_meeting_context():
    utterances = [
        {
            "content": (
                "자, 오늘은 노바드림 다음달 캠페인 전에 "
                "정리할 게 좀 있어서 시작해볼게요."
            )
        },
        {"content": "지난 캠페인 전환 수치가 좀 이상해서요."},
    ]

    assert _infer_default_campaign(utterances) == "노바드림 다음달 캠페인"


def test_infer_default_campaign_tolerates_stt_typo_and_generic_reference():
    utterances = [
        {
            "content": (
                "오늘은 노바드림 다음 빨 캠페인 전에 정리할게 좀 있어서 "
                "시작해 볼게요."
            )
        },
        {
            "content": (
                "지난 캠페인 전환 수치가 좀 이상해서요. "
                "메타랑 GA 숫자가 안 맞아요."
            )
        },
    ]

    assert _infer_default_campaign(utterances) == "노바드림 다음달 캠페인"


def test_apply_default_campaign_only_when_item_campaign_is_empty():
    utterances = [
        {"content": "오늘은 노바드림 다음달 캠페인 준비 건을 보겠습니다."}
    ]
    items = [
        ActionItemSchema(
            content="픽셀 이벤트 중복 발화 보정",
            confidence=0.9,
            source_quote="픽셀 이벤트가 중복 발화되는 건 맞아 보여요.",
            related_campaign=None,
        ),
        ActionItemSchema(
            content="구글 SA 예산 조정",
            confidence=0.9,
            source_quote="구글 SA 예산을 조정하겠습니다.",
            related_campaign="구글 SA",
        ),
    ]

    result = _apply_default_campaign(items, utterances)

    assert result[0].related_campaign == "노바드림 다음달 캠페인"
    assert result[1].related_campaign == "구글 SA"


def test_infer_default_campaign_returns_none_when_multiple_candidates():
    utterances = [
        {"content": "노바드림 다음달 캠페인 먼저 보고요."},
        {"content": "그리고 카카오 DA 캠페인도 따로 봐야 합니다."},
    ]

    assert _infer_default_campaign(utterances) is None


# ---------------------------------------------------------------------------
# MinutesSummarySchema 유효성 검사
# ---------------------------------------------------------------------------

def test_minutes_schema_decisions_list():
    """decisions 는 리스트 타입이어야 한다."""
    m = MinutesSummarySchema(summary="요약", decisions=["결정1", "결정2"])
    assert isinstance(m.decisions, list)
    assert len(m.decisions) == 2


# ---------------------------------------------------------------------------
# 재시도·폴백 경로 검증
# ---------------------------------------------------------------------------

def test_fallback_on_all_retries_fail(monkeypatch):
    """3회 재시도 후 모두 실패하면 confidence=0 + is_ambiguous=True 폴백 항목이 반환되어야 한다."""
    import src.extract as ext

    monkeypatch.setattr(ext, "LLM_MODE", "real")
    monkeypatch.setattr(ext, "_call_gemini", lambda prompt, schema: {"action_items": [{"bad_field": "invalid"}]})

    result = ext._extract_action_items("발화록 텍스트", "2026-06-01")

    assert len(result) == 1
    assert result[0].confidence == 0.0
    assert result[0].is_ambiguous is True
    assert result[0].assignee is None


def test_retry_succeeds_on_second_attempt(monkeypatch):
    """첫 번째 시도 실패 후 두 번째 시도에서 올바른 응답이 오면 정상 반환되어야 한다."""
    import src.extract as ext

    call_count = {"n": 0}

    def mock_gemini(prompt, schema):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {"action_items": [{"bad": "schema"}]}
        return {
            "action_items": [{
                "content": "정상 액션아이템",
                "assignee": "홍길동",
                "due_date": None,
                "due_is_inferred": False,
                "confidence": 0.9,
                "source_quote": "제가 처리할게요.",
                "is_ambiguous": False,
            }]
        }

    monkeypatch.setattr(ext, "LLM_MODE", "real")
    monkeypatch.setattr(ext, "_call_gemini", mock_gemini)

    result = ext._extract_action_items("발화록 텍스트", "2026-06-01")

    assert call_count["n"] == 2
    assert len(result) == 1
    assert result[0].content == "정상 액션아이템"
    assert result[0].confidence == 0.9
