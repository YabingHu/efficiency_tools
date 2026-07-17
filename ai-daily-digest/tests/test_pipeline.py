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
    assert main.collect_all(cfg, date(2026, 7, 17)) == [expected]


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
