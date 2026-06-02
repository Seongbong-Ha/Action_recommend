import argparse
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional


DEFAULT_GOLDEN_PATH = "data/golden_action_items.json"
DEFAULT_MATCH_THRESHOLD = 0.75


@dataclass(frozen=True)
class ActionItem:
    content: str
    assignee: Optional[str] = None
    due_date: Optional[str] = None
    related_campaign: Optional[str] = None
    source_quote: Optional[str] = None
    confidence: Optional[float] = None


@dataclass(frozen=True)
class MatchedPair:
    golden: ActionItem
    predicted: ActionItem
    similarity: float


@dataclass(frozen=True)
class EvaluationResult:
    meeting_id: str
    true_positive: int
    false_positive: int
    false_negative: int
    precision: float
    recall: float
    f1: float
    assignee_accuracy: Optional[float]
    due_date_accuracy: Optional[float]
    campaign_accuracy: Optional[float]
    source_quote_match_rate: Optional[float]
    low_confidence_ratio: Optional[float]
    matches: list[MatchedPair]
    unmatched_golden: list[ActionItem]
    unmatched_predicted: list[ActionItem]


def _normalize_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", "", value.strip().lower())


def _normalize_optional(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped if stripped else None


def content_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, _normalize_text(left), _normalize_text(right)).ratio()


def _source_quote_matches(golden_quote: Optional[str], predicted_quote: Optional[str]) -> bool:
    golden_norm = _normalize_text(golden_quote)
    predicted_norm = _normalize_text(predicted_quote)
    if not golden_norm or not predicted_norm:
        return False
    return golden_norm in predicted_norm or predicted_norm in golden_norm


def _safe_ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _average(values: list[bool]) -> Optional[float]:
    if not values:
        return None
    return sum(1 for value in values if value) / len(values)


def _to_action_item(raw: dict[str, Any]) -> ActionItem:
    confidence = raw.get("confidence")
    return ActionItem(
        content=str(raw["content"]),
        assignee=_normalize_optional(raw.get("assignee")),
        due_date=_normalize_optional(raw.get("due_date")),
        related_campaign=_normalize_optional(raw.get("related_campaign")),
        source_quote=_normalize_optional(raw.get("source_quote")),
        confidence=float(confidence) if confidence is not None else None,
    )


def load_golden(path: str = DEFAULT_GOLDEN_PATH) -> tuple[str, list[ActionItem]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "meetings" in data:
        if len(data["meetings"]) != 1:
            raise ValueError("현재 CLI는 단일 meeting golden set만 평가합니다.")
        data = data["meetings"][0]
    meeting_id = data["meeting_id"]
    return meeting_id, [_to_action_item(item) for item in data["action_items"]]


def load_predictions_from_db(meeting_id: str) -> list[ActionItem]:
    from src.database import get_cursor

    with get_cursor() as cur:
        cur.execute(
            """
            SELECT content, assignee, due_date, related_campaign, source_quote, confidence
            FROM mart_action_items
            WHERE meeting_id = %s
            ORDER BY action_item_id
            """,
            (meeting_id,),
        )
        return [_to_action_item(dict(row)) for row in cur.fetchall()]


def match_action_items(
    golden_items: list[ActionItem],
    predicted_items: list[ActionItem],
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> tuple[list[MatchedPair], list[ActionItem], list[ActionItem]]:
    candidates: list[tuple[float, int, int]] = []
    for golden_index, golden in enumerate(golden_items):
        for predicted_index, predicted in enumerate(predicted_items):
            similarity = content_similarity(golden.content, predicted.content)
            if similarity >= threshold:
                candidates.append((similarity, golden_index, predicted_index))

    candidates.sort(reverse=True, key=lambda item: item[0])
    used_golden: set[int] = set()
    used_predicted: set[int] = set()
    matches: list[MatchedPair] = []

    for similarity, golden_index, predicted_index in candidates:
        if golden_index in used_golden or predicted_index in used_predicted:
            continue
        used_golden.add(golden_index)
        used_predicted.add(predicted_index)
        matches.append(
            MatchedPair(
                golden=golden_items[golden_index],
                predicted=predicted_items[predicted_index],
                similarity=similarity,
            )
        )

    unmatched_golden = [
        item for index, item in enumerate(golden_items) if index not in used_golden
    ]
    unmatched_predicted = [
        item for index, item in enumerate(predicted_items) if index not in used_predicted
    ]
    return matches, unmatched_golden, unmatched_predicted


def evaluate_predictions(
    meeting_id: str,
    golden_items: list[ActionItem],
    predicted_items: list[ActionItem],
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> EvaluationResult:
    matches, unmatched_golden, unmatched_predicted = match_action_items(
        golden_items, predicted_items, threshold
    )

    tp = len(matches)
    fp = len(unmatched_predicted)
    fn = len(unmatched_golden)
    precision = _safe_ratio(tp, tp + fp)
    recall = _safe_ratio(tp, tp + fn)
    f1 = _safe_ratio(2 * precision * recall, precision + recall)

    assignee_accuracy = _average([
        pair.golden.assignee == pair.predicted.assignee for pair in matches
    ])
    due_date_accuracy = _average([
        pair.golden.due_date == pair.predicted.due_date for pair in matches
    ])
    campaign_accuracy = _average([
        pair.golden.related_campaign == pair.predicted.related_campaign
        for pair in matches
    ])
    source_quote_match_rate = _average([
        _source_quote_matches(pair.golden.source_quote, pair.predicted.source_quote)
        for pair in matches
    ])

    confidence_values = [
        item.confidence for item in predicted_items if item.confidence is not None
    ]
    low_confidence_ratio = (
        sum(1 for confidence in confidence_values if confidence < 0.7)
        / len(confidence_values)
        if confidence_values
        else None
    )

    return EvaluationResult(
        meeting_id=meeting_id,
        true_positive=tp,
        false_positive=fp,
        false_negative=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        assignee_accuracy=assignee_accuracy,
        due_date_accuracy=due_date_accuracy,
        campaign_accuracy=campaign_accuracy,
        source_quote_match_rate=source_quote_match_rate,
        low_confidence_ratio=low_confidence_ratio,
        matches=matches,
        unmatched_golden=unmatched_golden,
        unmatched_predicted=unmatched_predicted,
    )


def _format_metric(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def format_result(result: EvaluationResult) -> str:
    lines = [
        f"Evaluation result for {result.meeting_id}",
        "",
        "Action item detection",
        f"- precision: {_format_metric(result.precision)}",
        f"- recall:    {_format_metric(result.recall)}",
        f"- f1:        {_format_metric(result.f1)}",
        f"- tp/fp/fn:  {result.true_positive}/{result.false_positive}/{result.false_negative}",
        "",
        "Field accuracy on matched items",
        f"- assignee_accuracy:       {_format_metric(result.assignee_accuracy)}",
        f"- due_date_accuracy:       {_format_metric(result.due_date_accuracy)}",
        f"- campaign_accuracy:       {_format_metric(result.campaign_accuracy)}",
        f"- source_quote_match_rate: {_format_metric(result.source_quote_match_rate)}",
        f"- low_confidence_ratio:    {_format_metric(result.low_confidence_ratio)}",
    ]

    if result.unmatched_golden:
        lines.extend(["", "Unmatched golden items"])
        lines.extend(f"- {item.content}" for item in result.unmatched_golden)

    if result.unmatched_predicted:
        lines.extend(["", "Unmatched predicted items"])
        lines.extend(f"- {item.content}" for item in result.unmatched_predicted)

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate extracted action items against a golden set."
    )
    parser.add_argument("--golden", default=DEFAULT_GOLDEN_PATH)
    parser.add_argument("--threshold", type=float, default=DEFAULT_MATCH_THRESHOLD)
    args = parser.parse_args()

    meeting_id, golden_items = load_golden(args.golden)
    predicted_items = load_predictions_from_db(meeting_id)
    result = evaluate_predictions(
        meeting_id=meeting_id,
        golden_items=golden_items,
        predicted_items=predicted_items,
        threshold=args.threshold,
    )
    print(format_result(result))


if __name__ == "__main__":
    main()
