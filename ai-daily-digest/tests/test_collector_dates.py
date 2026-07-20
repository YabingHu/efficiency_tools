from datetime import UTC, date, datetime
from types import SimpleNamespace

from src.collectors import arxiv_papers, github_trending, hackernews
from src.utils import report_end_utc


class Response:
    content = b"feed"

    def __init__(self, data=None):
        self.data = data or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


def test_github_skips_historical_report(monkeypatch, cfg):
    monkeypatch.setattr(
        github_trending,
        "http_get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应请求当天榜单")),
    )
    assert github_trending.collect(cfg, date(2020, 1, 1)) == []


def test_hackernews_uses_report_date_for_time_range(monkeypatch, cfg):
    captured = {}
    cfg["sources"]["hackernews"]["queries"] = ["LLM"]
    cfg["sources"]["hackernews"]["workers"] = 1

    def fake_get(*args, **kwargs):
        captured.update(kwargs["params"])
        return Response({"hits": []})

    monkeypatch.setattr(hackernews, "http_get", fake_get)
    report_date = date(2026, 7, 10)
    hackernews.collect(cfg, report_date)
    until = int(report_end_utc(report_date, cfg["timezone"]).timestamp())
    assert f"created_at_i<={until}" in captured["numericFilters"]


def test_hackernews_uses_self_post_body(monkeypatch, cfg):
    cfg["sources"]["hackernews"]["queries"] = ["LLM"]
    cfg["sources"]["hackernews"]["workers"] = 1

    def fake_get(*args, **kwargs):
        return Response({"hits": [{
            "objectID": "42",
            "title": "Ask HN: LLM testing",
            "url": None,
            "story_text": "<p>Detailed self post about evaluation and testing.</p>",
            "points": 100,
            "num_comments": 20,
        }]})

    monkeypatch.setattr(hackernews, "http_get", fake_get)
    result = hackernews.collect(cfg, date(2026, 7, 18))
    assert [item.id for item in result] == ["hn:42"]
    assert "Detailed self post" in result[0].text
    assert result[0].meta["content_available"] is True


def test_hackernews_fetches_external_body_and_drops_unavailable(monkeypatch, cfg):
    cfg["sources"]["hackernews"]["queries"] = ["LLM"]
    cfg["sources"]["hackernews"]["workers"] = 1

    def fake_get(*args, **kwargs):
        return Response({"hits": [
            {
                "objectID": "good", "title": "Good article",
                "url": "https://example.com/good", "story_text": None,
                "points": 90, "num_comments": 10,
            },
            {
                "objectID": "bad", "title": "Blocked article",
                "url": "https://example.com/bad", "story_text": None,
                "points": 80, "num_comments": 9,
            },
        ]})

    monkeypatch.setattr(hackernews, "http_get", fake_get)
    monkeypatch.setattr(
        hackernews,
        "extract_text_from_url",
        lambda url, *args, **kwargs: "Substantial article body." if url.endswith("/good") else "",
    )
    result = hackernews.collect(cfg, date(2026, 7, 18))
    assert [item.id for item in result] == ["hn:good"]
    assert "Substantial article body" in result[0].text


def test_arxiv_query_and_filter_are_anchored_to_report_date(monkeypatch, cfg):
    captured = {}
    published = datetime(2026, 7, 10, 8, tzinfo=UTC)
    entry = SimpleNamespace(
        id="https://arxiv.org/abs/2607.01234v1",
        title="LLM test paper",
        summary="language model research",
        published_parsed=published.timetuple(),
    )

    def fake_get(*args, **kwargs):
        captured.update(kwargs["params"])
        return Response()

    monkeypatch.setattr(arxiv_papers, "http_get", fake_get)
    monkeypatch.setattr(
        arxiv_papers.feedparser,
        "parse",
        lambda content: SimpleNamespace(entries=[entry]),
    )
    result = arxiv_papers.collect(cfg, date(2026, 7, 10))
    assert "submittedDate:" in captured["search_query"]
    assert "20260710" in captured["search_query"]
    assert [item.id for item in result] == ["arxiv:2607.01234"]


def _rss_entry(announce_type="new", published=None, arxiv_id="2607.15280"):
    published = published or datetime(2026, 7, 20, 4, tzinfo=UTC)
    return SimpleNamespace(
        id=f"oai:arXiv.org:{arxiv_id}v1",
        link=f"https://arxiv.org/abs/{arxiv_id}",
        title="LLM agent benchmark",
        summary=(
            f"arXiv:{arxiv_id}v1 Announce Type: {announce_type} "
            "Abstract: A large language model study."
        ),
        published_parsed=published.timetuple(),
        arxiv_announce_type=announce_type,
    )


def test_arxiv_falls_back_to_rss_when_api_fails(monkeypatch, cfg):
    requested = []

    def fake_get(url, *args, **kwargs):
        requested.append(url)
        if url.startswith(arxiv_papers.API):
            raise RuntimeError("429 Too Many Requests")
        return Response()

    monkeypatch.setattr(arxiv_papers, "http_get", fake_get)
    monkeypatch.setattr(
        arxiv_papers.feedparser,
        "parse",
        lambda content: SimpleNamespace(entries=[
            _rss_entry("new"),
            _rss_entry("replace", arxiv_id="2607.99999"),
        ]),
    )
    result = arxiv_papers.collect(cfg, date(2026, 7, 20))
    assert any(url.startswith(arxiv_papers.RSS) for url in requested)
    # 只保留新提交，排除对已有论文的修订
    assert [item.id for item in result] == ["arxiv:2607.15280"]
    # 送模型的正文不应残留 RSS 的 Announce Type 前缀
    assert result[0].text == "A large language model study."
    assert result[0].url == "https://arxiv.org/abs/2607.15280"


def test_arxiv_rss_fallback_skips_historical_backfill(monkeypatch, cfg):
    """RSS 只有当期公告；回补历史日期时公告日晚于 as_of，必须过滤为空。"""
    def fake_get(url, *args, **kwargs):
        if url.startswith(arxiv_papers.API):
            raise RuntimeError("429 Too Many Requests")
        return Response()

    monkeypatch.setattr(arxiv_papers, "http_get", fake_get)
    monkeypatch.setattr(
        arxiv_papers.feedparser,
        "parse",
        lambda content: SimpleNamespace(entries=[_rss_entry("new")]),
    )
    assert arxiv_papers.collect(cfg, date(2026, 7, 10)) == []


def test_arxiv_keeps_api_result_without_calling_rss(monkeypatch, cfg):
    published = datetime(2026, 7, 20, 8, tzinfo=UTC)
    entry = SimpleNamespace(
        id="https://arxiv.org/abs/2607.01234v1",
        title="LLM test paper",
        summary="language model research",
        published_parsed=published.timetuple(),
    )

    def fake_get(url, *args, **kwargs):
        assert not url.startswith(arxiv_papers.RSS), "API 有结果时不应触发兜底"
        return Response()

    monkeypatch.setattr(arxiv_papers, "http_get", fake_get)
    monkeypatch.setattr(
        arxiv_papers.feedparser, "parse", lambda content: SimpleNamespace(entries=[entry]),
    )
    assert [item.id for item in arxiv_papers.collect(cfg, date(2026, 7, 20))] == [
        "arxiv:2607.01234"
    ]
