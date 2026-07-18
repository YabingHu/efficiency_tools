"""Jinja2 渲染 HTML 早报。"""
import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import NewsItem
from .utils import take_with_source_limit

log = logging.getLogger(__name__)

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=select_autoescape(["html", "htm", "xml", "j2"]),
    )


def check_template() -> None:
    _environment().get_template("report.html.j2")


def _atomic_write_text(path: Path, content: str) -> None:
    """同目录临时文件替换，避免任务中断留下半份日报。"""
    fd, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def write_status(cfg: dict, status: dict) -> Path:
    out_dir = Path(cfg["_root"]) / cfg.get("output_dir", "output")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "run-status.json"
    _atomic_write_text(path, json.dumps(status, ensure_ascii=False, indent=2) + "\n")
    return path


def render_archive(cfg: dict, report_dates: list[str], *, retention_days: int) -> Path:
    """Render the public history index next to the daily reports."""
    template = _environment().get_template("archive.html.j2")
    html = template.render(
        report_dates=report_dates,
        retention_days=retention_days,
        generated_at=datetime.now(
            ZoneInfo(cfg.get("timezone", "Asia/Shanghai"))
        ).strftime("%Y-%m-%d %H:%M %Z"),
    )
    out_dir = Path(cfg["_root"]) / cfg.get("output_dir", "output")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "archive.html"
    _atomic_write_text(path, html)
    return path


def render(cfg: dict, items: list[NewsItem], overview: list[str],
           report_date: datetime, *, update_latest: bool = True) -> Path:
    env = _environment()
    template = env.get_template("report.html.j2")

    sections = []
    for key, sec_cfg in cfg["sections"].items():
        if not sec_cfg.get("enabled", True):
            continue
        sec_items = [it for it in items if it.section == key]
        sec_items.sort(key=lambda x: (x.importance, x.score), reverse=True)
        limit = sec_cfg.get("limit", 8)
        max_per_source = sec_cfg.get("max_per_source")
        if max_per_source:
            sec_items = take_with_source_limit(sec_items, limit, max_per_source)
        sections.append({
            "key": key,
            "title": sec_cfg["title"],
            "subtitle": sec_cfg.get("subtitle", ""),
            "entries": sec_items[:limit],
            "initial_visible": min(cfg.get("initial_visible_items", 4), limit),
        })

    html = template.render(
        date_str=report_date.strftime("%Y-%m-%d"),
        weekday=WEEKDAYS[report_date.weekday()],
        overview=overview,
        sections=sections,
        generated_at=datetime.now(
            ZoneInfo(cfg.get("timezone", "Asia/Shanghai"))
        ).strftime("%Y-%m-%d %H:%M %Z"),
    )

    out_dir = Path(cfg["_root"]) / cfg.get("output_dir", "output")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{report_date.strftime('%Y-%m-%d')}.html"
    _atomic_write_text(out_path, html)
    if update_latest:
        _atomic_write_text(out_dir / "latest.html", html)
        # GitHub Pages serves index.html at the site root. Keep it identical to
        # latest.html so the same output directory works locally and in Pages.
        _atomic_write_text(out_dir / "index.html", html)
    log.info("已生成 %s", out_path)
    return out_path
