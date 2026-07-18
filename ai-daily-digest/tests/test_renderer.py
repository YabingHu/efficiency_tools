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
