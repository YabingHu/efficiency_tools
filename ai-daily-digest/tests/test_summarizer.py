import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.models import NewsItem
from src.summarizer import (
    Summarizer,
    SummaryResponseError,
    _extract_json,
    _sanitize_comment,
    _validated_results,
)


def _make_summarizer(tmp_path):
    summarizer = Summarizer.__new__(Summarizer)
    summarizer.model = "test-model"
    summarizer.batch_size = 12
    summarizer.request_timeout_seconds = 60
    summarizer.total_timeout_seconds = 900
    summarizer._deadline = None
    summarizer.budget_exhausted = False
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
    assert second_item.meta["summary_status"] == "generated"


def test_practice_prompt_refresh_invalidates_only_chinese_practice_cache(tmp_path, monkeypatch):
    summarizer = _make_summarizer(tmp_path)
    chinese = NewsItem("cn", "community_cn", "Qwen 部署", "https://example.com/cn", "知乎")
    paper = NewsItem("paper", "papers", "LLM paper", "https://example.com/paper", "arXiv")
    chinese_key, paper_key = summarizer._cache_key(chinese), summarizer._cache_key(paper)
    monkeypatch.setattr("src.summarizer.CHINESE_PRACTICE_SUMMARY_VERSION", 2)
    assert summarizer._cache_key(chinese) != chinese_key
    assert summarizer._cache_key(paper) == paper_key


def test_make_overview_returns_points_and_content_based_thread_titles(tmp_path):
    summarizer = _make_summarizer(tmp_path)
    item = NewsItem(
        "industry-1",
        "industry",
        "OpenAI 发布 GPT-5",
        "https://example.com/gpt-5",
        "OpenAI",
        text="OpenAI 发布 GPT-5，活跃用户达到 10 亿。",
        summary_zh="OpenAI 发布 GPT-5，活跃用户达到 10 亿。",
        importance=5,
    )
    captured = {}

    def fake_chat(_prompt, payload):
        captured["payload"] = payload
        return (
            '{"points":["OpenAI 发布 GPT-5，用户规模达到 10 亿。"],'
            '"threads":[{"topic":"产业动态","title":"OpenAI 发布 GPT-5，用户达 10 亿"}]}'
        )

    summarizer._chat = fake_chat
    points, thread_titles = summarizer.make_overview([item])

    assert points == ["OpenAI 发布 GPT-5，用户规模达到 10 亿。"]
    assert thread_titles == {"产业动态": "OpenAI 发布 GPT-5，用户达 10 亿"}
    assert captured["payload"][0]["topic"] == "产业动态"


def test_make_overview_reserves_candidates_for_non_paper_topics(tmp_path):
    summarizer = _make_summarizer(tmp_path)
    items = [
        NewsItem(
            f"paper-{index}",
            "papers",
            f"LLM paper {index}",
            f"https://example.com/paper/{index}",
            "HF Papers",
            text="LLM paper research details.",
            importance=5,
        )
        for index in range(20)
    ]
    items.extend([
        NewsItem(
            "industry-1", "industry", "OpenAI model release",
            "https://example.com/industry", "OpenAI", text="Official model release.", importance=1,
        ),
        NewsItem(
            "community-1", "community", "Developer discussion about an AI model",
            "https://example.com/community", "社区", text="Community discussion.", importance=1,
        ),
        NewsItem(
            "github-1", "github", "Open source LLM tool",
            "https://example.com/github", "GitHub", text="Open source project.", importance=1,
        ),
    ])
    captured = {}

    def fake_chat(_prompt, payload):
        captured["payload"] = payload
        return '{"points":[],"threads":[]}'

    summarizer._chat = fake_chat
    summarizer.make_overview(items)

    topics = [entry["topic"] for entry in captured["payload"]]
    assert len(captured["payload"]) <= 15
    assert sum(topic != "论文" for topic in topics) >= 3
    assert topics.count("论文") <= 6


def test_community_english_response_is_retried_without_repeating_valid_items(tmp_path):
    summarizer = _make_summarizer(tmp_path)
    items = [
        NewsItem("a", "community", "Model reports", "https://example.com/a", "X"),
        NewsItem("b", "community", "Byte models", "https://example.com/b", "Lobsters"),
    ]
    calls = []

    def fake_chat(prompt, payload):
        calls.append([row["id"] for row in payload])
        assert all(row["section"] == "community" for row in payload)
        assert "40~90" in prompt
        return json.dumps([
            {"id": row["id"], "summary": (
                "English source snippet" if row["id"] == "b" and len(calls) == 1
                else "这条讨论介绍模型的新进展。"
            )} for row in payload
        ])

    summarizer._chat = fake_chat
    summarizer.summarize_items(items)
    assert calls == [["a", "b"], ["b"]]
    assert all(item.summary_zh == "这条讨论介绍模型的新进展。" for item in items)


def test_community_english_cache_is_regenerated(tmp_path):
    summarizer = _make_summarizer(tmp_path)
    item = NewsItem("a", "community", "News", "https://example.com/a", "X")
    key = summarizer._cache_key(item)
    summarizer._cache[key] = {"summary": "English cached snippet", "importance": 3}
    calls = []

    def fake_chat(*args):
        calls.append(True)
        return '[{"id":"a","summary":"这是一条新生成的中文摘要。"}]'

    summarizer._chat = fake_chat
    summarizer.summarize_items([item])
    assert calls == [True]
    assert item.summary_zh == "这是一条新生成的中文摘要。"


@pytest.mark.parametrize("status", [401, 403, 404])
def test_service_configuration_errors_stop_retries_and_keep_cache(tmp_path, monkeypatch, status):
    summarizer = _make_summarizer(tmp_path)
    summarizer.batch_size = 1
    summarizer.max_retries = 2
    summarizer.temperature = 0.3
    summarizer.max_output_tokens = 4096
    items = [
        NewsItem(str(i), "community", "News", f"https://example.com/{i}", "X",
                 text="English content") for i in range(3)
    ]
    summarizer._cache[summarizer._cache_key(items[0])] = {
        "summary": "这是一条已经缓存的中文摘要。", "importance": 3,
    }
    calls = []

    def create(**kwargs):
        calls.append(True)
        error = RuntimeError("private upstream response")
        error.status_code = status
        raise error

    summarizer.client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create),
    ))
    monkeypatch.setattr("src.summarizer.time.sleep", lambda *_: pytest.fail("不应重试"))
    summarizer.summarize_items(items)
    assert calls == [True]
    assert items[0].summary_zh == "这是一条已经缓存的中文摘要。"
    assert all(item.summary_zh == "中文摘要暂未生成，请点击标题查看原文。" for item in items[1:])
    assert all(item.meta["summary_status"] == "fallback" for item in items[1:])
    assert len(summarizer._cache) == 1


@pytest.mark.parametrize("content,finish_reason", [(None, "stop"), ("[", "length")])
def test_empty_and_truncated_responses_split_without_retrying_same_batch(
    tmp_path, monkeypatch, content, finish_reason,
):
    summarizer = _make_summarizer(tmp_path)
    summarizer.max_retries = 2
    summarizer.temperature = 0.3
    summarizer.max_output_tokens = 4096
    calls = []

    def create(**kwargs):
        data = kwargs["messages"][1]["content"].split("<data>\n", 1)[1]
        payload = json.loads(data.rsplit("\n</data>", 1)[0])
        calls.append([row["id"] for row in payload])
        response = content if len(payload) > 1 else json.dumps([
            {"id": payload[0]["id"], "summary": "这是一条完整的中文摘要。"},
        ])
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=response),
            finish_reason=finish_reason if len(payload) > 1 else "stop",
        )])

    summarizer.client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create),
    ))
    monkeypatch.setattr("src.summarizer.time.sleep", lambda *_: pytest.fail("不应原样重试"))
    items = [
        NewsItem(str(i), "industry", "AI news", f"https://example.com/{i}", "src")
        for i in range(2)
    ]
    summarizer.summarize_items(items)
    assert calls == [["0", "1"], ["0"], ["1"]]
    assert all(item.meta["summary_status"] == "generated" for item in items)


def test_transport_retry_uses_remaining_budget_as_request_timeout(tmp_path, monkeypatch):
    summarizer = _make_summarizer(tmp_path)
    summarizer.max_retries = 2
    summarizer.temperature = 0.3
    summarizer.max_output_tokens = 4096
    clock = [0.0]
    summarizer._deadline = 5
    timeouts = []

    def create(**kwargs):
        timeouts.append(kwargs["timeout"])
        if len(timeouts) == 1:
            raise TimeoutError("temporary network failure")
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content='[{"id":"a","summary":"中文摘要"}]'),
        )])

    summarizer.client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create),
    ))
    monkeypatch.setattr("src.summarizer.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("src.summarizer.time.sleep", lambda seconds: clock.__setitem__(
        0, clock[0] + seconds,
    ))
    assert "中文摘要" in summarizer._chat("prompt", [])
    assert timeouts == [5, 3]


def test_deadline_during_split_preserves_successful_child_and_cache(tmp_path, monkeypatch):
    summarizer = _make_summarizer(tmp_path)
    summarizer.total_timeout_seconds = 5
    clock = [0.0]
    monkeypatch.setattr("src.summarizer.time.monotonic", lambda: clock[0])
    items = [
        NewsItem(str(i), "community", "AI news", f"https://example.com/{i}", "src")
        for i in range(5)
    ]
    summarizer._cache[summarizer._cache_key(items[0])] = {
        "summary": "这是一条已经缓存的中文摘要。", "importance": 4,
        "cached_at": datetime.now(UTC).isoformat(),
    }
    calls = []

    def fake_chat(_prompt, payload):
        calls.append([row["id"] for row in payload])
        clock[0] += 2
        if len(payload) > 1:
            raise SummaryResponseError("batch too large")
        return json.dumps([{"id": payload[0]["id"], "summary": "这是一条新的中文摘要。"}])

    summarizer._chat = fake_chat
    summarizer.summarize_items(items)
    assert calls == [["1", "2", "3", "4"], ["1", "2"], ["1"]]
    assert summarizer.budget_exhausted
    assert [item.meta["summary_status"] for item in items] == [
        "generated", "generated", "fallback", "fallback", "fallback",
    ]
    assert len(summarizer._cache) == 2
    restored = _make_summarizer(tmp_path)
    assert len(restored._cache) == 2
    assert all(item.summary_zh == "中文摘要暂未生成，请点击标题查看原文。" for item in items[2:])
