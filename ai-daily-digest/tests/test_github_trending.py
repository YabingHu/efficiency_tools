from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.collectors import github_trending as github
from src.models import NewsItem


class Response:
    def __init__(self, text="", status=200, headers=None):
        self.text = text
        self.status_code = status
        self.headers = headers or {}
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")

    def iter_content(self, chunk_size):
        content = self.text.encode("utf-8")
        for start in range(0, len(content), chunk_size):
            yield content[start:start + chunk_size]

    def close(self):
        self.closed = True


def test_enrichment_extracts_readme_and_release_without_page_chrome(monkeypatch, cfg):
    responses = [
        Response('<nav>Navigation</nav><article class="markdown-body">'
                 '<h1>LLM tool</h1><p>Run locally with Python.</p><pre>pip install tool</pre>'
                 '<script>ignore this</script></article>'),
        Response('<div class="markdown-body"><p>v2 adds tool calling.</p></div>'),
    ]
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return responses[len(calls) - 1]

    monkeypatch.setattr(github, "http_get", get)
    item = NewsItem("github:org/tool", "github", "org/tool", "https://github.com/org/tool",
                    "GitHub Trending", text="LLM agent tool")
    github._enrich_item(item, cfg)
    assert "README：" in item.text
    assert "pip install tool" in item.text
    assert item.text.startswith("最新 Release：")
    assert "Navigation" not in item.text
    assert "ignore this" not in item.text
    assert item.meta["readme_available"] is True
    assert item.meta["release_available"] is True
    assert all(response.closed for response in responses)
    assert all(call[1]["retries"] == 0 for call in calls)
    assert all(call[1]["allow_redirects"] is False for call in calls)


def test_enrichment_retains_readme_when_release_is_missing(monkeypatch, cfg):
    monkeypatch.setattr(github, "http_get", lambda url, **kw: (
        Response(status=404) if url.endswith("/latest")
        else Response('<article class="markdown-body">AI model usage details.</article>')
    ))
    item = NewsItem("id", "github", "org/tool", "https://github.com/org/tool", "GitHub",
                    text="Original description")
    github._enrich_item(item, cfg)
    assert item.text.startswith("Original description")
    assert "AI model usage" in item.text
    assert item.meta.get("release_available") is None


def test_enrichment_failure_preserves_description(monkeypatch, cfg):
    def fail(*args, **kwargs):
        raise TimeoutError

    monkeypatch.setattr(github, "http_get", fail)
    item = NewsItem("id", "github", "org/tool", "https://github.com/org/tool", "GitHub",
                    text="Original description")
    assert github._enrich_item(item, cfg).text == "Original description"


@pytest.mark.parametrize("location", ["https://example.com/internal", "http://github.com/org/tool"])
def test_page_content_rejects_redirect_outside_https_github(monkeypatch, cfg, location):
    response = Response(status=302, headers={"Location": location})
    calls = []
    monkeypatch.setattr(github, "http_get", lambda *a, **kw: calls.append(True) or response)
    assert github._page_content("https://github.com/org/tool", cfg, "article") == ""
    assert len(calls) == 1
    assert response.closed


def test_page_content_follows_repository_rename(monkeypatch, cfg):
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            return Response(status=301, headers={"Location": "/org/renamed"})
        return Response('<article class="markdown-body">AI tool documentation</article>')

    monkeypatch.setattr(github, "http_get", get)
    assert github._page_content("https://github.com/org/tool", cfg, "article.markdown-body")
    assert calls[-1] == "https://github.com/org/renamed"


def test_page_content_closes_and_discards_oversized_response(monkeypatch, cfg):
    monkeypatch.setattr(github, "MAX_CONTENT_BYTES", 20)
    response = Response('<article class="markdown-body">' + "x" * 100 + '</article>')
    monkeypatch.setattr(github, "http_get", lambda *a, **kw: response)
    assert github._page_content("https://github.com/org/tool", cfg, "article") == ""
    assert response.closed


@pytest.mark.parametrize("text,keyword,expected", [
    ("email client", "ai", False), ("chair design", "ai", False),
    ("langchain-ai/langchain", "ai", True), ("llm inference", "llm", True),
    ("models for ai", "model", True), ("ai agent tool", "agent", True),
])
def test_keywords_use_word_boundaries(text, keyword, expected):
    assert github._matches_keyword(text, keyword) is expected


def test_collect_does_not_fill_with_unrelated_projects_and_bounds_enrichment(monkeypatch, cfg):
    cfg["sources"]["github"]["content_fetch_limit"] = 1
    cfg["sources"]["github"]["keywords"] = ["ai", "llm"]
    html = "".join(
        f'<article class="Box-row"><h2><a href="/{repo}">{repo}</a></h2>'
        f'<p>{desc}</p><span class="d-inline-block float-sm-right">{stars} stars today</span>'
        '</article>'
        for repo, desc, stars in [
            ("org/email", "Email client", 10000),
            ("org/small", "LLM tool", 10),
            ("org/large", "AI coding assistant", 100),
            ("org/large", "AI duplicate", 100),
            ("bad/path/extra", "AI malicious path", 1000),
        ]
    )
    monkeypatch.setattr(github, "http_get", lambda *a, **kw: Response(html))
    enriched = []
    monkeypatch.setattr(github, "_enrich_item", lambda item, cfg: enriched.append(item.id) or item)
    today = datetime.now(ZoneInfo(cfg["timezone"])).date()
    result = github.collect(cfg, today)
    assert [item.id for item in result] == ["github:org/large", "github:org/small"]
    assert enriched == ["github:org/large"]
