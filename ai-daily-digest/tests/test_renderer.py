from datetime import datetime
from zoneinfo import ZoneInfo

from src.models import NewsItem
from src.renderer import render, write_status


def test_render_escapes_content_and_does_not_overwrite_latest_for_history(cfg):
    for key, section in cfg["sections"].items():
        section["enabled"] = key == "industry"
    news = NewsItem(
        id="x", section="industry", title="<script>alert(1)</script>",
        url="https://example.com", source="source", summary_zh="safe",
        importance=3,
    )
    report_date = datetime(2026, 7, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    path = render(cfg, [news], [], report_date, update_latest=False)
    html = path.read_text(encoding="utf-8")
    assert "&lt;script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert 'href="archive.html"' in html
    assert not (path.parent / "latest.html").exists()


def test_render_updates_latest_atomically(cfg):
    report_date = datetime(2026, 7, 17, tzinfo=ZoneInfo("Asia/Shanghai"))
    path = render(cfg, [], [], report_date, update_latest=True)
    latest = path.parent / "latest.html"
    index = path.parent / "index.html"
    assert latest.read_text(encoding="utf-8") == path.read_text(encoding="utf-8")
    assert index.read_text(encoding="utf-8") == path.read_text(encoding="utf-8")
    assert not list(path.parent.glob("*.tmp"))


def test_status_file_is_machine_readable(cfg):
    path = write_status(cfg, {"status": "success", "collected_items": 3})
    assert '"collected_items": 3' in path.read_text(encoding="utf-8")


def test_render_limits_single_community_source(cfg):
    for key, section in cfg["sections"].items():
        section["enabled"] = key == "community"
    cfg["sections"]["community"]["limit"] = 2
    cfg["sections"]["community"]["max_per_source"] = 1
    items = [
        NewsItem("hn-1", "community", "HN first", "https://example.com/1", "HN", score=100),
        NewsItem("hn-2", "community", "HN second", "https://example.com/2", "HN", score=90),
        NewsItem(
            "lob-1", "community", "Lobsters first", "https://example.com/3",
            "Lobsters", score=10,
        ),
    ]
    path = render(
        cfg, items, [], datetime(2026, 7, 18, tzinfo=ZoneInfo("Asia/Shanghai")),
        update_latest=False,
    )
    html = path.read_text(encoding="utf-8")
    assert "HN first" in html
    assert "Lobsters first" in html
    assert "HN second" not in html


def test_render_collapses_entries_after_configured_initial_count(cfg):
    for key, section in cfg["sections"].items():
        section["enabled"] = key == "industry"
    cfg["sections"]["industry"]["limit"] = 6
    cfg["initial_visible_items"] = 4
    items = [
        NewsItem(
            f"item-{index}", "industry", f"Item {index}",
            f"https://example.com/{index}", "source", importance=3,
        )
        for index in range(6)
    ]

    path = render(
        cfg, items, [], datetime(2026, 7, 18, tzinfo=ZoneInfo("Asia/Shanghai")),
        update_latest=False,
    )
    html = path.read_text(encoding="utf-8")

    assert html.count('class="card is-extra"') == 2
    assert "展开其余 2 条" in html
    assert 'aria-controls="entries-industry"' in html


def test_section_nav_wraps_on_desktop_and_scrolls_on_mobile(cfg):
    path = render(
        cfg, [], [], datetime(2026, 7, 18, tzinfo=ZoneInfo("Asia/Shanghai")),
        update_latest=False,
    )
    html = path.read_text(encoding="utf-8")

    assert ".section-nav {\n    display: flex; flex-wrap: wrap;" in html
    assert "flex-wrap: nowrap; overflow-x: auto; padding-bottom: 16px;" in html


def test_paper_sections_render_as_one_switchable_group(cfg):
    for key, section in cfg["sections"].items():
        section["enabled"] = key in {"papers", "arxiv", "eval", "github"}
    items = [
        NewsItem("paper-1", "papers", "HF paper", "https://example.com/paper", "HF", score=20),
        NewsItem("arxiv-1", "arxiv", "arXiv paper", "https://example.com/arxiv", "arXiv"),
        NewsItem("eval-1", "eval", "Eval paper", "https://example.com/eval", "arXiv"),
    ]

    path = render(
        cfg, items, [], datetime(2026, 7, 18, tzinfo=ZoneInfo("Asia/Shanghai")),
        update_latest=False,
    )
    html = path.read_text(encoding="utf-8")

    nav_html = html.split(
        '<nav class="section-nav" aria-label="日报板块">', 1,
    )[1].split("</nav>", 1)[0]
    assert 'href="#section-papers-group">📚 论文动态 <span class="count">3</span></a>' in nav_html
    assert 'href="#section-papers"' not in nav_html
    assert 'href="#section-arxiv"' not in nav_html
    assert 'href="#section-eval"' not in nav_html
    assert 'data-paper-topic-tab' in html
    assert 'id="paper-topic-papers"' in html
    assert 'id="paper-topic-arxiv"' in html
    assert 'id="paper-topic-eval"' in html


def test_empty_paper_topics_are_hidden_from_switcher(cfg):
    for key, section in cfg["sections"].items():
        section["enabled"] = key in {"papers", "arxiv", "eval", "agent", "github"}
    items = [
        NewsItem("arxiv-1", "arxiv", "arXiv paper", "https://example.com/arxiv", "arXiv"),
    ]

    path = render(
        cfg, items, [], datetime(2026, 7, 18, tzinfo=ZoneInfo("Asia/Shanghai")),
        update_latest=False,
    )
    html = path.read_text(encoding="utf-8")

    nav_html = html.split(
        '<nav class="section-nav" aria-label="日报板块">', 1,
    )[1].split("</nav>", 1)[0]
    assert 'href="#section-papers-group">📚 论文动态 <span class="count">1</span></a>' in nav_html
    assert 'id="paper-topic-arxiv"' in html
    assert 'id="paper-topic-papers"' not in html
    assert 'id="paper-topic-eval"' not in html
    assert 'id="paper-topic-agent"' not in html


def test_render_shows_today_threads_and_quality_badge(cfg):
    for key, section in cfg["sections"].items():
        section["enabled"] = key == "industry"
    news = NewsItem(
        "thread-1", "industry", "OpenAI releases a new LLM safety report",
        "https://example.com/thread", "OpenAI", summary_zh="安全报告摘要",
        importance=4, meta={"quality_score": 88, "quality_reasons": ["AI 相关性强"]},
    )

    path = render(
        cfg, [news], [], datetime(2026, 7, 18, tzinfo=ZoneInfo("Asia/Shanghai")),
        today_threads=[{
            "title": "安全治理：OpenAI releases a new LLM safety report",
            "summary": "1 条相关内容，主要来自 OpenAI。",
            "item_ids": ["thread-1"],
            "score": 88,
        }],
        update_latest=False,
    )
    html = path.read_text(encoding="utf-8")

    assert "🧭 今日主线" in html
    assert "安全治理：OpenAI releases" in html
    assert "质量 88" in html
    assert "AI 相关性强" in html


def test_render_shows_topic_tags_for_paper_and_community_cards(cfg):
    for key, section in cfg["sections"].items():
        section["enabled"] = key in {"papers", "community"}
    items = [
        NewsItem(
            "paper-tag", "papers", "A benchmark paper", "https://example.com/paper",
            "HF Papers", text="A paper about benchmark evaluation.", summary_zh="论文摘要",
        ),
        NewsItem(
            "community-tag", "community", "Developer discussion", "https://example.com/community",
            "Hacker News", text="AI developer discussion.", summary_zh="社区讨论摘要",
        ),
    ]

    path = render(
        cfg, items, [], datetime(2026, 7, 18, tzinfo=ZoneInfo("Asia/Shanghai")),
        update_latest=False,
    )
    html = path.read_text(encoding="utf-8")

    assert 'class="badge tag">论文</span>' in html
    assert 'class="badge tag">社区热议</span>' in html
