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
