from datetime import date

from src import main
from src.models import NewsItem


def item(item_id, section="industry", url="https://example.com/post", score=0):
    return NewsItem(
        id=item_id, section=section, title=item_id, url=url,
        source="test", score=score,
    )


def test_deduplicate_filters_disabled_unsafe_and_tracking_urls():
    items = [
        item("first", url="https://example.com/post?utm_source=a"),
        item("duplicate", url="https://example.com/post?utm_source=b"),
        item("unsafe", url="javascript:alert(1)"),
        item("disabled", section="media", url="https://example.com/media"),
    ]
    result = main.deduplicate(items, {"industry"})
    assert [value.id for value in result] == ["first"]


def test_trim_ignores_disabled_sections_and_ranks_scores(cfg):
    cfg["sections"]["industry"]["limit"] = 1
    cfg["sections"]["media"]["enabled"] = False
    items = [
        item("low", score=1), item("high", score=10),
        item("media", section="media", url="https://example.com/media"),
    ]
    assert [value.id for value in main.trim_items(cfg, items)] == ["high", "low"]


def test_rss_runs_when_only_media_is_enabled(monkeypatch, cfg):
    for section in cfg["sections"].values():
        section["enabled"] = False
    cfg["sections"]["media"]["enabled"] = True
    expected = item("media", section="media", url="https://example.com/media")

    def fake_collect(_cfg, _today):
        return [expected]

    monkeypatch.setattr(main, "COLLECTORS", {"rss": (fake_collect, {"industry", "media"})})
    items, _ = main.collect_all(cfg, date(2026, 7, 17))
    assert items == [expected]


def test_collect_all_reports_empty_and_failed_collectors(monkeypatch, cfg):
    def working(_cfg, _today):
        return [item("ok")]

    def silent(_cfg, _today):
        return []

    def broken(_cfg, _today):
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "COLLECTORS", {
        "rss": (working, {"industry"}),
        "arxiv": (silent, {"industry"}),
        "github": (broken, {"industry"}),
    })
    items, diagnostics = main.collect_all(cfg, date(2026, 7, 17))
    assert [value.id for value in items] == ["ok"]
    assert diagnostics["collector_counts"] == {"rss": 1, "arxiv": 0, "github": 0}
    assert diagnostics["failed_collectors"] == ["github"]
    # 静默返回 0 条的采集器必须和真正抛异常的一样可见
    assert diagnostics["empty_collectors"] == ["arxiv", "github"]


def test_no_llm_fallback_shows_source_text():
    news = item("raw")
    news.text = "raw source text"
    main.apply_no_llm_fallback([news])
    assert news.summary_zh == "raw source text"
    assert news.importance == 3


def test_no_llm_fallback_truncates_long_text_with_ellipsis():
    news = item("long")
    news.text = "x" * 500
    main.apply_no_llm_fallback([news])
    assert len(news.summary_zh) == 360
    assert news.summary_zh.endswith("…")


def test_trim_balances_sources_before_filling_remaining_slots(cfg):
    cfg["sections"]["community"]["limit"] = 2
    cfg["sections"]["community"]["max_per_source"] = 1
    items = [
        NewsItem("hn-1", "community", "hn-1", "https://example.com/1", "HN", score=100),
        NewsItem("hn-2", "community", "hn-2", "https://example.com/2", "HN", score=90),
        NewsItem("hn-3", "community", "hn-3", "https://example.com/5", "HN", score=80),
        NewsItem("hn-4", "community", "hn-4", "https://example.com/6", "HN", score=70),
        NewsItem("lob-1", "community", "lob-1", "https://example.com/3", "Lobsters", score=10),
        NewsItem("se-1", "community", "se-1", "https://example.com/4", "Stack", score=5),
    ]
    result = main.trim_items(cfg, items)
    assert [value.id for value in result] == ["hn-1", "hn-2", "lob-1", "se-1"]
