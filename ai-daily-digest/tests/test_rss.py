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
