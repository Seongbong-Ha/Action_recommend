import pytest

from src.action_items import validate_status
from src.transcriber import normalize_expected_speaker_count


def test_validate_status_accepts_known_values():
    assert validate_status("open") == "open"
    assert validate_status("DONE") == "done"
    assert validate_status(" blocked ") == "blocked"


def test_validate_status_rejects_unknown_value():
    with pytest.raises(ValueError):
        validate_status("pending")


def test_normalize_expected_speaker_count_allows_auto_mode():
    assert normalize_expected_speaker_count(None) is None
    assert normalize_expected_speaker_count(0) is None


def test_normalize_expected_speaker_count_rejects_negative_value():
    with pytest.raises(ValueError):
        normalize_expected_speaker_count(-1)
