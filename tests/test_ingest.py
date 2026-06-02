from datetime import datetime

from src.ingest import coerce_utterance_timestamp


def test_coerce_utterance_timestamp_converts_audio_offset_seconds():
    assert coerce_utterance_timestamp("0.19", "2026-06-02") == datetime(
        2026, 6, 2, 0, 0, 0, 190000
    )


def test_coerce_utterance_timestamp_preserves_iso_timestamp():
    assert coerce_utterance_timestamp(
        "2026-06-01T10:00:05Z",
        "2026-06-02",
    ) == datetime.fromisoformat(
        "2026-06-01T10:00:05+00:00",
    )


def test_coerce_utterance_timestamp_allows_empty_timestamp():
    assert coerce_utterance_timestamp(None, "2026-06-02") is None
    assert coerce_utterance_timestamp("", "2026-06-02") is None
