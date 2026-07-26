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
PAPER_BASE_SECTIONS = ("papers", "arxiv")


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


def _section_entries(cfg: dict, sec_cfg: dict, items: list[NewsItem]) -> list[NewsItem]:
    """一个板块最终展示的条目：按 (importance, score) 排序后限流截断。"""
    sec_items = sorted(items, key=lambda x: (x.importance, x.score), reverse=True)
    limit = sec_cfg.get("limit", 8)
    max_per_source = sec_cfg.get("max_per_source")
    if max_per_source:
        sec_items = take_with_source_limit(sec_items, limit, max_per_source)
    return sec_items[:limit]


def _paper_section_keys(cfg: dict) -> list[str]:
    """Return enabled paper-related sections in display order."""
    topic_keys = [
        rule.get("section")
        for rule in cfg.get("paper_topics", []) or []
        if rule.get("section")
    ]
    paper_keys = set(PAPER_BASE_SECTIONS) | set(topic_keys)
    return [
        key for key, sec_cfg in cfg["sections"].items()
        if key in paper_keys and sec_cfg.get("enabled", True)
    ]


def _render_section(cfg: dict, key: str, sec_cfg: dict, items: list[NewsItem]) -> dict:
    limit = sec_cfg.get("limit", 8)
    return {
        "key": key,
        "title": sec_cfg["title"],
        "subtitle": sec_cfg.get("subtitle", ""),
        "entries": _section_entries(cfg, sec_cfg, [it for it in items if it.section == key]),
        "initial_visible": min(cfg.get("initial_visible_items", 4), limit),
    }


def selected_items(cfg: dict, items: list[NewsItem]) -> list[NewsItem]:
    """跨所有启用板块，返回会真正出现在早报里的条目（与 render 选择逻辑一致）。"""
    selected = []
    for key, sec_cfg in cfg["sections"].items():
        if not sec_cfg.get("enabled", True):
            continue
        section_items = [it for it in items if it.section == key]
        selected.extend(_section_entries(cfg, sec_cfg, section_items))
    return selected


def render(cfg: dict, items: list[NewsItem], overview: list[str],
           report_date: datetime, *, update_latest: bool = True) -> Path:
    env = _environment()
    template = env.get_template("report.html.j2")

    paper_keys = _paper_section_keys(cfg)
    paper_key_set = set(paper_keys)
    sections = []
    for key, sec_cfg in cfg["sections"].items():
        if not sec_cfg.get("enabled", True):
            continue
        if key in paper_key_set:
            if key == paper_keys[0]:
                topics = [
                    _render_section(cfg, paper_key, cfg["sections"][paper_key], items)
                    for paper_key in paper_keys
                ]
                topics = [topic for topic in topics if topic["entries"]]
                sections.append({
                    "key": "papers-group",
                    "title": "📚 论文动态",
                    "subtitle": "精选论文、arXiv 新稿与专题论文",
                    "entries": [entry for topic in topics for entry in topic["entries"]],
                    "topics": topics,
                })
            continue
        sections.append(_render_section(cfg, key, sec_cfg, items))

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
