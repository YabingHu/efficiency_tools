import pytest

from src.summarizer import _extract_json, _validated_results


def test_extract_json_accepts_fenced_response():
    assert _extract_json('```json\n[{"id":"a"}]\n```') == [{"id": "a"}]


def test_validated_results_rejects_unknown_and_deduplicates():
    data = [
        {"id": "a", "summary": "first", "comment": 123, "importance": 99},
        {"id": "a", "summary": "second", "importance": 1},
        {"id": "unknown", "summary": "bad", "importance": 3},
        {"id": "b", "summary": "", "importance": 3},
    ]
    assert _validated_results(data, {"a", "b"}) == {
        "a": {"summary": "first", "comment": "", "importance": 5}
    }


def test_validated_results_requires_array():
    with pytest.raises(ValueError):
        _validated_results({}, {"a"})
