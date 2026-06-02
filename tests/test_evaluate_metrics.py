from src.evaluate import ActionItem, evaluate_predictions, match_action_items


def test_match_action_items_uses_similarity_threshold():
    golden = [ActionItem(content="구글 SA 캠페인 세팅 완료")]
    predicted = [ActionItem(content="구글 SA 캠페인 세팅")]

    matches, unmatched_golden, unmatched_predicted = match_action_items(
        golden, predicted, threshold=0.75
    )

    assert len(matches) == 1
    assert unmatched_golden == []
    assert unmatched_predicted == []


def test_evaluate_predictions_counts_precision_recall_f1():
    golden = [
        ActionItem(content="구글 SA 캠페인 세팅 완료", assignee="김민지"),
        ActionItem(content="카카오 DA 리포트 발송", assignee="김민지"),
    ]
    predicted = [
        ActionItem(content="구글 SA 캠페인 세팅", assignee="김민지", confidence=0.9),
        ActionItem(content="불필요한 추가 액션", assignee="홍길동", confidence=0.4),
    ]

    result = evaluate_predictions("meet_test", golden, predicted, threshold=0.75)

    assert result.true_positive == 1
    assert result.false_positive == 1
    assert result.false_negative == 1
    assert result.precision == 0.5
    assert result.recall == 0.5
    assert result.f1 == 0.5
    assert result.assignee_accuracy == 1.0
    assert result.low_confidence_ratio == 0.5


def test_field_accuracy_is_calculated_on_matched_items():
    golden = [
        ActionItem(
            content="소재 검수 결과 전달",
            assignee="홍길동",
            due_date=None,
            related_campaign=None,
            source_quote="피드백 받는 즉시 공유하겠습니다.",
        )
    ]
    predicted = [
        ActionItem(
            content="소재 검수 결과 확인 후 전달",
            assignee="홍길동",
            due_date=None,
            related_campaign=None,
            source_quote="알겠습니다. 피드백 받는 즉시 공유하겠습니다.",
        )
    ]

    result = evaluate_predictions("meet_test", golden, predicted, threshold=0.5)

    assert result.assignee_accuracy == 1.0
    assert result.due_date_accuracy == 1.0
    assert result.campaign_accuracy == 1.0
    assert result.source_quote_match_rate == 1.0
