import pytest

from src.models import NewsItem
from src.summarizer import Summarizer, _extract_json, _sanitize_comment, _validated_results


def _make_summarizer(tmp_path):
    summarizer = Summarizer.__new__(Summarizer)
    summarizer.model = "test-model"
    summarizer.batch_size = 12
    summarizer.max_input_chars_per_item = 2400
    summarizer.cache_retention_days = 30
    summarizer.cache_path = tmp_path / "history" / "summary-cache.json"
    summarizer._cache, summarizer._cache_dirty = summarizer._load_cache()
    return summarizer


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


@pytest.mark.parametrize(
    "comment",
    ["值得关注。", "标题很吸引人，但正文啥也没有，差评。", "来源未提供更多细节。"],
)
def test_sanitize_comment_hides_low_value_editorializing(comment):
    assert _sanitize_comment(comment) == ""


def test_sanitize_comment_keeps_evidence_based_observation():
    comment = "如果推理成本确实下降，中小团队部署智能体的门槛也会随之降低。"
    assert _sanitize_comment(comment) == comment


def test_failed_batch_is_split_until_individual_items_succeed(tmp_path):
    summarizer = _make_summarizer(tmp_path)
    items = [
        NewsItem(str(index), "industry", f"title {index}", f"https://example.com/{index}", "src")
        for index in range(4)
    ]
    batch_sizes = []

    def fake_chat(_prompt, payload):
        batch_sizes.append(len(payload))
        if len(payload) > 1:
            raise RuntimeError("batch too large")
        return (
            '[{"id":"' + payload[0]["id"]
            + '","summary":"摘要","comment":"","importance":3}]'
        )

    summarizer._chat = fake_chat
    results = summarizer._summarize_batch(items)

    assert set(results) == {"0", "1", "2", "3"}
    assert batch_sizes == [4, 2, 1, 1, 2, 1, 1]


def test_summary_cache_is_reused_across_runs(tmp_path):
    item_args = (
        "same-id", "industry", "same title", "https://example.com/same", "source",
    )
    first = _make_summarizer(tmp_path)
    calls = []

    def fake_chat(_prompt, payload):
        calls.append(payload)
        return (
            '[{"id":"same-id","summary":"缓存摘要",'
            '"comment":"成本下降会扩大可用场景。","importance":4}]'
        )

    first._chat = fake_chat
    first_item = NewsItem(*item_args, text="stable content")
    first.summarize_items([first_item])

    second = _make_summarizer(tmp_path)
    second._chat = lambda *_args: pytest.fail("cache hit should not call the model")
    second_item = NewsItem(*item_args, text="stable content")
    second.summarize_items([second_item])

    assert len(calls) == 1
    assert second_item.summary_zh == "缓存摘要"
    assert second_item.importance == 4
