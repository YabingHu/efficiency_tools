"""Official update pages that do not expose a usable RSS feed."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..content_extractor import extract_text_from_url
from ..http_client import get as http_get
from ..models import NewsItem
from ..utils import report_end_utc, safe_http_url

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "ai-daily-digest/1.0 (official updates)"}
MONTH_DATE = re.compile(
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}"
)
FULL_MONTH_DATE = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+\d{1,2},\s+\d{4}"
)
SLASH_DATE = re.compile(r"\d{4}/\d{2}/\d{2}")


def _date(value: str, fmt: str) -> datetime | None:
    try:
        return datetime.strptime(value, fmt).replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _ancestor_text_with_date(node, pattern: re.Pattern, levels: int = 6) -> str:
    current = node
    for _ in range(levels):
        if current is None:
            break
        text = " ".join(current.get_text(" ", strip=True).split())
        if pattern.search(text):
            return text
        current = current.parent
    return ""


def _parse_anthropic(soup: BeautifulSoup, base_url: str) -> list[dict]:
    rows = []
    for anchor in soup.select('a[href^="/news/"], a[href^="/features/"]'):
        time_node = anchor.find("time")
        date_text = time_node.get_text(" ", strip=True) if time_node else ""
        date_match = MONTH_DATE.search(date_text)
        title_node = anchor.select_one('span[class*="__title"]')
        title = title_node.get_text(" ", strip=True) if title_node else ""
        if not date_match or not title:
            continue
        rows.append({
            "date": _date(date_match.group(0), "%b %d, %Y"),
            "title": title,
            "url": urljoin(base_url, anchor.get("href", "")),
            "text": anchor.get_text(" ", strip=True),
        })
    return rows


def _parse_kimi(soup: BeautifulSoup, base_url: str) -> list[dict]:
    rows = []
    for anchor in soup.select('a[href^="/en/blog/"]'):
        title = str(anchor.get("aria-label") or anchor.get_text(" ", strip=True)).strip()
        context = _ancestor_text_with_date(anchor, SLASH_DATE)
        date_match = SLASH_DATE.search(context)
        if not title or not date_match:
            continue
        rows.append({
            "date": _date(date_match.group(0), "%Y/%m/%d"),
            "title": title,
            "url": urljoin(base_url, anchor.get("href", "")),
            "text": context,
        })
    return rows


def _parse_qwen(soup: BeautifulSoup, base_url: str) -> list[dict]:
    rows = []
    for anchor in soup.select('a[href*="/blog/"]'):
        date_match = MONTH_DATE.search(anchor.get_text(" ", strip=True))
        title_node = anchor.find(["h2", "h3"])
        if not date_match or title_node is None:
            continue
        summary_node = anchor.find("p")
        summary = summary_node.get_text(" ", strip=True) if summary_node else ""
        rows.append({
            "date": _date(date_match.group(0), "%b %d, %Y"),
            "title": title_node.get_text(" ", strip=True),
            "url": urljoin(base_url, anchor.get("href", "")),
            "text": summary,
        })
    return rows


def _parse_deepseek(soup: BeautifulSoup, base_url: str) -> list[dict]:
    rows = []
    for anchor in soup.find_all("a"):
        if anchor.get_text(" ", strip=True) != "Model Card":
            continue
        context = _ancestor_text_with_date(anchor, FULL_MONTH_DATE)
        date_match = FULL_MONTH_DATE.search(context)
        title_match = re.search(r"DeepSeek-[A-Za-z0-9.]+", context)
        if not date_match or not title_match:
            continue
        rows.append({
            "date": _date(date_match.group(0), "%B %d, %Y"),
            "title": f"{title_match.group(0)} released",
            "url": urljoin(base_url, anchor.get("href", "")),
            "text": context,
        })
    return rows


PARSERS = {
    "anthropic": _parse_anthropic,
    "kimi": _parse_kimi,
    "qwen": _parse_qwen,
    "deepseek": _parse_deepseek,
}


def _collect_site(cfg: dict, site_cfg: dict, as_of: datetime) -> tuple[str, list[NewsItem]]:
    name = site_cfg["name"]
    parser = PARSERS[site_cfg["parser"]]
    url = site_cfg["url"]
    try:
        response = http_get(url, cfg=cfg, headers=HEADERS)
        response.raise_for_status()
        rows = parser(BeautifulSoup(response.text, "html.parser"), url)
    except Exception as exc:
        log.warning("官方更新 [%s] 拉取失败: %s", name, exc)
        return name, []

    dated = [row for row in rows if row.get("date") and row["date"] <= as_of]
    newest = max((row["date"] for row in dated), default=None)
    if newest is None:
        log.warning("官方更新 [%s] 缺少可用发布时间", name)
        return name, []

    source_cfg = cfg["sources"]["official_updates"]
    max_staleness = timedelta(hours=source_cfg.get("max_staleness_hours", 120))
    if as_of - newest > max_staleness:
        log.info("官方更新 [%s] 暂无近期内容", name)
        return name, []
    cutoff = newest - timedelta(hours=source_cfg.get("lookback_hours", 72))

    items = []
    seen_urls = set()
    content_limit = source_cfg.get("content_fetch_limit", 4)
    for row in sorted(dated, key=lambda value: value["date"], reverse=True):
        if row["date"] < cutoff:
            continue
        link = safe_http_url(row["url"])
        if not link or link in seen_urls:
            continue
        seen_urls.add(link)
        text = row["text"]
        if len(items) < content_limit and site_cfg.get("fetch_content", False):
            text = extract_text_from_url(link, cfg, min_chars=120) or text
        uid = hashlib.sha256(link.encode()).hexdigest()[:16]
        items.append(NewsItem(
            id=f"official:{site_cfg['parser']}:{uid}",
            section="industry",
            title=row["title"],
            url=link,
            source=name,
            text=text[:1600],
            score=1,
            meta={"published": row["date"].isoformat()},
        ))
        if len(items) >= site_cfg.get("max_items", 8):
            break
    log.info("官方更新 [%s] 收到 %d 条", name, len(items))
    return name, items


def collect(cfg: dict, today) -> list[NewsItem]:
    source_cfg = cfg["sources"].get("official_updates", {})
    if not source_cfg.get("enabled", True):
        return []
    if not cfg["sections"].get("industry", {}).get("enabled", True):
        return []
    as_of = report_end_utc(today, cfg.get("timezone", "Asia/Shanghai"))
    items = []
    for site_cfg in source_cfg.get("sites", []):
        _, site_items = _collect_site(cfg, site_cfg, as_of)
        items.extend(site_items)
    return items
