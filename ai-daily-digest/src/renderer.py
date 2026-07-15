"""Jinja2 渲染 HTML 早报。"""
import logging
import shutil
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .models import NewsItem

log = logging.getLogger(__name__)

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def render(cfg: dict, items: list[NewsItem], overview: list[str],
           report_date: datetime) -> Path:
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=True,
    )
    template = env.get_template("report.html.j2")

    sections = []
    for key, sec_cfg in cfg["sections"].items():
        if not sec_cfg.get("enabled", True):
            continue
        sec_items = [it for it in items if it.section == key]
        sec_items.sort(key=lambda x: (x.importance, x.score), reverse=True)
        sections.append({
            "key": key,
            "title": sec_cfg["title"],
            "subtitle": sec_cfg.get("subtitle", ""),
            "entries": sec_items[:sec_cfg.get("limit", 8)],
        })

    html = template.render(
        date_str=report_date.strftime("%Y-%m-%d"),
        weekday=WEEKDAYS[report_date.weekday()],
        overview=overview,
        sections=sections,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )

    out_dir = Path(cfg["_root"]) / cfg.get("output_dir", "output")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{report_date.strftime('%Y-%m-%d')}.html"
    out_path.write_text(html, encoding="utf-8")
    shutil.copyfile(out_path, out_dir / "latest.html")
    log.info("已生成 %s", out_path)
    return out_path
