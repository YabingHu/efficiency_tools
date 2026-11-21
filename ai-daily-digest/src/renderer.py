"""Jinja2 渲染 HTML 早报。"""
import hashlib
import json
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .editorial import LOW_SIGNAL_PATTERNS, has_sufficient_source, quality_sort_key, topic_tags
from .models import NewsItem
from .topics import ROUTABLE_SECTIONS, paper_topic_sections
from .utils import canonical_url, safe_http_url, take_with_source_limit

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
    path = out_dir / "run-status.json"
    write_json(path, status)
    return path


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


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
    """一个板块最终展示的条目：按编辑质量分、重要度与来源热度排序后限流截断。"""
    sec_items = sorted(
        items, key=lambda item: (not item.meta.get("coverage_note"), quality_sort_key(item)),
        reverse=True,
    )
    for item in sec_items:
        item.meta["topic_tags"] = topic_tags(item)
    limit = sec_cfg.get("limit", 8)
    max_per_source = sec_cfg.get("max_per_source")
    if max_per_source:
        sec_items = take_with_source_limit(sec_items, limit, max_per_source)
    return sec_items[:limit]


def _paper_section_keys(cfg: dict) -> list[str]:
    """Return enabled paper-related sections in display order."""
    paper_keys = ROUTABLE_SECTIONS | paper_topic_sections(cfg)
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


def _must_read_brief(item: NewsItem) -> str:
    if changes := item.meta.get("follow_up_changes"):
        subject = item.meta.get("event_subject") or item.title
        return f"{subject} 本次进展包括" + "、".join(change["label"] for change in changes) + "。"
    for content in (item.meta.get("brief_zh", ""), item.summary_zh):
        text = " ".join(content.split())
        first = re.split(r"(?<=[。！？!?])\s*|(?<=\.)\s+", text, maxsplit=1)[0]
        if first and len(first) <= 100 and not first.endswith(("…", "...", "，", "、", ",")):
            return first if first.endswith(("。", "！", "？", ".", "!", "?")) else first + "。"
    return ""


def _must_read_source(item: NewsItem) -> tuple[str, str] | None:
    url = safe_http_url(item.url)
    if not url or item.meta.get("link_status") == "rss_only":
        return None
    if paper := re.fullmatch(r"arxiv:(\d{4}\.\d{4,5})", item.id):
        return "论文原文", f"https://arxiv.org/abs/{paper[1]}"
    changes = item.meta.get("follow_up_changes", [])
    if any(not change.get("first_party") for change in changes):
        return None
    if item.meta.get("first_party"):
        for change in changes:
            if change_url := safe_http_url(change.get("url", "")):
                return "进展来源", change_url
        return "官方来源", url
    if item.section == "github" and (
        item.meta.get("readme_available") or item.meta.get("release_available")
    ):
        return "项目原文", url
    if item.meta.get("collection_method") == "author_feed" or (
        item.id.startswith("hn:") and url == item.meta.get("hn_url")
    ):
        return "作者原帖", url
    return None


def must_read_items(cfg: dict, items: list[NewsItem], limit: int = 5) -> list[NewsItem]:
    """先通过质量与素材硬门槛，再从最终展示条目中兼顾板块覆盖。"""
    if limit <= 0:
        return []
    requirements = cfg.get("must_read", {})
    paper_keys = set(_paper_section_keys(cfg))
    ranked = sorted(selected_items(cfg, items), key=quality_sort_key, reverse=True)
    candidates, seen, seen_events = [], set(), set()
    for item in ranked:
        if (
            quality_sort_key(item)[0] < requirements.get("min_quality_score", 65)
            or not has_sufficient_source(item, requirements.get("min_source_chars", 160))
            or not item.summary_zh.strip()
            or item.meta.get("coverage_note")
            or item.meta.get("summary_status") in {"fallback", "raw"}
            or item.meta.get("grounding_status") != "verified"
            or LOW_SIGNAL_PATTERNS[0].search(item.summary_zh)
            or "中文摘要暂未生成" in item.summary_zh
            or not _must_read_brief(item)
            or not _must_read_source(item)
        ):
            continue
        url = canonical_url(item.url)
        event = item.meta.get("event_key")
        if item.id in seen or url in seen or (event and event in seen_events):
            continue
        seen.update((item.id, url))
        if event:
            seen_events.add(event)
        candidates.append(item)
    selected, groups = [], set()
    for item in candidates:
        group = "papers" if item.section in paper_keys else item.section
        if group not in groups and len(selected) < limit:
            selected.append(item)
            groups.add(group)
    selected_ids = {item.id for item in selected}
    selected.extend(item for item in candidates if item.id not in selected_ids)
    return sorted(selected[:limit], key=quality_sort_key, reverse=True)


def render(cfg: dict, items: list[NewsItem], overview: list[str],
           report_date: datetime, *, today_threads: list[dict] | None = None,
           update_latest: bool = True, section_notes: dict[str, str] | None = None,
           rejected: list[dict] | None = None) -> Path:
    env = _environment()
    template = env.get_template("report.html.j2")
    # 保留旧调用参数兼容历史工具，但不再渲染无文章绑定的要点和主线。
    for item in items:
        item.meta["article_id"] = "article-" + hashlib.sha256(item.id.encode()).hexdigest()[:16]
        item.meta["reading_url"] = (
            "#rss-full-" + item.meta["article_id"]
            if item.meta.get("link_status") == "rss_only" else item.url
        )
    must_reads = []
    for item in must_read_items(cfg, items):
        title = " ".join((item.meta.get("headline_zh") or item.title).split())
        source_label, source_url = _must_read_source(item)
        must_reads.append({
            "item": item,
            "title": title if len(title) <= 56 else title[:55].rstrip() + "…",
            "brief": _must_read_brief(item),
            "source_label": source_label,
            "source_url": source_url,
        })

    paper_keys = _paper_section_keys(cfg)
    paper_key_set = set(paper_keys)
    rendered = {
        key: _render_section(cfg, key, sec_cfg, items)
        for key, sec_cfg in cfg["sections"].items() if sec_cfg.get("enabled", True)
    }
    sections = []
    empty_sections = []
    section_notes = section_notes or {}
    rejected_keys = {group["key"] for group in rejected or []}
    for key, section in rendered.items():
        if not section["entries"] and (key not in paper_key_set or key in rejected_keys):
            empty_sections.append((section["title"], section_notes.get(key, "本期无入选内容")))
        if key in paper_key_set:
            if key == paper_keys[0]:
                topics = [
                    rendered[paper_key] for paper_key in paper_keys
                    if rendered[paper_key]["entries"]
                ]
                if topics:
                    sections.append({
                        "key": "papers-group",
                        "title": "📚 论文动态",
                        "subtitle": "精选论文、arXiv 新稿与专题论文",
                        "entries": [entry for topic in topics for entry in topic["entries"]],
                        "topics": topics,
                    })
            continue
        if section["entries"]:
            sections.append(section)

    html = template.render(
        date_str=report_date.strftime("%Y-%m-%d"),
        weekday=WEEKDAYS[report_date.weekday()],
        must_reads=must_reads,
        sections=sections,
        empty_sections=empty_sections,
        rejected=rejected or [],
        rejected_count=sum(len(group["entries"]) for group in rejected or []),
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
