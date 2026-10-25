from datetime import UTC, datetime
from types import SimpleNamespace

from src.collectors import rss_news


def entry(title, link, published):
    return SimpleNamespace(
        title=title,
        link=link,
        summary=f"summary {title}",
        published_parsed=published.timetuple(),
        updated_parsed=None,
    )


class Response:
    content = b"feed"

    def raise_for_status(self):
        return None


def rss_cfg(cfg):
    cfg["sources"]["rss"]["feeds"] = [
        {"name": "test", "url": "https://feed.example/rss", "section": "industry"}
    ]
    cfg["sources"]["rss"]["workers"] = 1
    cfg["sources"]["rss"]["lookback_hours"] = 48
    cfg["sources"]["rss"]["max_staleness_hours"] = 96
    return cfg


def test_rss_respects_report_date_and_excludes_future(monkeypatch, cfg):
    entries = [
        entry("fresh", "https://example.com/fresh", datetime(2026, 7, 17, tzinfo=UTC)),
        entry("future", "https://example.com/future", datetime(2026, 7, 18, tzinfo=UTC)),
        entry("old", "https://example.com/old", datetime(2026, 7, 10, tzinfo=UTC)),
    ]
    monkeypatch.setattr(rss_news, "http_get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(
        rss_news.feedparser, "parse", lambda content: SimpleNamespace(entries=entries),
    )
    result = rss_news.collect(rss_cfg(cfg), datetime(2026, 7, 17).date())
    assert [value.title for value in result] == ["fresh"]


def test_rss_skips_stale_feed(monkeypatch, cfg):
    entries = [
        entry("stale", "https://example.com/stale", datetime(2026, 7, 1, tzinfo=UTC)),
    ]
    monkeypatch.setattr(rss_news, "http_get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(
        rss_news.feedparser, "parse", lambda content: SimpleNamespace(entries=entries),
    )
    assert rss_news.collect(rss_cfg(cfg), datetime(2026, 7, 17).date()) == []


def test_rss_enriches_short_body_before_quality_filter_with_bounded_requests(monkeypatch, cfg):
    cfg = rss_cfg(cfg)
    cfg["sources"]["rss"]["feeds"][0].update(fetch_content=True, content_selector=".article")
    cfg["sources"]["rss"]["content_fetch_limit"] = 1
    entries = [entry(str(i), f"https://example.com/{i}", datetime(2026, 7, 17, tzinfo=UTC))
               for i in range(3)]
    monkeypatch.setattr(rss_news, "http_get", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(rss_news.feedparser, "parse", lambda _: SimpleNamespace(entries=entries))
    calls = []

    def extract(url, fetch_cfg, **kwargs):
        calls.append((url, kwargs, fetch_cfg["http"]["read_timeout_seconds"]))
        return "AI 模型部署的完整正文，包含配置和实验条件。" * 20

    monkeypatch.setattr(rss_news, "extract_text_from_url", extract)
    result = rss_news.collect(cfg, datetime(2026, 7, 17).date())
    assert len(calls) == 1
    assert calls[0] == ("https://example.com/0", {"min_chars": 160, "selector": ".article"}, 10)
    assert len(result[0].text) > 160
    assert result[0].meta["content_fetch_status"] == "ok"
    assert cfg["_collector_status"]["rss"]["feeds"]["test"]["content_fetch"] == {
        "attempted": 1, "succeeded": 1,
    }


def test_rss_retains_snippet_when_enrichment_is_unavailable(monkeypatch, cfg):
    cfg = rss_cfg(cfg)
    cfg["sources"]["rss"]["feeds"][0]["fetch_content"] = True
    entries = [entry("AI", "https://example.com/ai", datetime(2026, 7, 17, tzinfo=UTC))]
    monkeypatch.setattr(rss_news, "http_get", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(rss_news.feedparser, "parse", lambda _: SimpleNamespace(entries=entries))
    monkeypatch.setattr(rss_news, "extract_text_from_url", lambda *_args, **_kwargs: "")
    result = rss_news.collect(cfg, datetime(2026, 7, 17).date())
    assert result[0].text == "summary AI"
    assert result[0].meta["content_fetch_status"] == "unavailable"


def test_search_link_uses_feed_full_text_and_stable_dedup_url(monkeypatch, cfg):
    search_url = "http://weixin.sogou.com/weixin?type=2&query=AI"
    article = entry("AI 实践", search_url, datetime(2026, 7, 17, tzinfo=UTC))
    article.summary = "<p>AI 实验报告，包含详细配置和可复现代码。</p>" * 20
    monkeypatch.setattr(rss_news, "http_get", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(rss_news.feedparser, "parse", lambda _: SimpleNamespace(entries=[article]))
    result = rss_news.collect(rss_cfg(cfg), datetime(2026, 7, 17).date())
    assert result[0].url == search_url
    assert result[0].meta["link_status"] == "rss_only"
    assert "可复现代码" in result[0].meta["rss_full_text"]


def test_original_article_field_takes_precedence_over_search_url():
    article = SimpleNamespace(link="https://weixin.sogou.com/weixin?type=2&query=AI",
                              feedburner_origlink="https://example.com/original")
    assert rss_news._article_link(article) == "https://example.com/original"
