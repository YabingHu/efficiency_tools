"""Official update pages that do not expose a usable RSS feed."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin, urlsplit

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
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
ANTHROPIC_TITLE = 'h2, h3, span[class*="__title"]'
KIMI_LINK = 'a[href^="/en/blog/"]'


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


def _card_date(card, *, visible_text: bool = False) -> datetime | None:
    time_node = card.find("time")
    if time_node and (value := time_node.get("datetime")):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except (TypeError, ValueError):
            pass
    if time_node is None and not visible_text:
        return None
    text = (time_node or card).get_text(" ", strip=True)
    for pattern, fmt in (
        (ISO_DATE, "%Y-%m-%d"), (SLASH_DATE, "%Y/%m/%d"),
        (MONTH_DATE, "%b %d, %Y"), (FULL_MONTH_DATE, "%B %d, %Y"),
    ):
        if (match := pattern.search(text)) and (parsed := _date(match[0], fmt)):
            return parsed
    return None


def _parse_anthropic(soup: BeautifulSoup, base_url: str) -> list[dict]:
    rows = {}
    origin = urlsplit(base_url).netloc
    for anchor in soup.select("a[href]"):
        title = anchor.select_one(ANTHROPIC_TITLE)
        link = urljoin(base_url, anchor["href"])
        parsed = urlsplit(link)
        if (title is None or link in rows or parsed.netloc != origin
                or not parsed.path.startswith(("/news/", "/features/", "/claude-"))):
            continue
        for card in (anchor, *list(anchor.parents)[:3]):
            # A card can have a category link, but never use another headline's date.
            headlines = {
                a["href"] for a in card.select("a[href]") if a.select_one(ANTHROPIC_TITLE)
            }
            if headlines - {anchor["href"]}:
                break
            if published := _card_date(card):
                rows[link] = {
                    "date": published,
                    "title": title.get_text(" ", strip=True),
                    "url": link,
                    "text": card.get_text(" ", strip=True),
                }
                break
    return list(rows.values())


def _parse_kimi(soup: BeautifulSoup, base_url: str) -> list[dict]:
    rows = {}
    for anchor in soup.select(KIMI_LINK):
        link = urljoin(base_url, anchor["href"])
        card = anchor.parent
        # Index navigation has the same links but no per-article date.
        if link in rows or len(card.select(KIMI_LINK)) != 1:
            continue
        heading = card.select_one("h2, h3, h4")
        title = anchor.get("aria-label") or (heading or anchor).get_text(" ", strip=True)
        if title and (published := _card_date(card, visible_text=True)):
            rows[link] = {
                "date": published,
                "title": title.strip(),
                "url": link,
                "text": card.get_text(" ", strip=True),
            }
    return list(rows.values())


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


def _collect_site(cfg: dict, site_cfg: dict, as_of: datetime) -> tuple[str, list[NewsItem], str]:
    name = site_cfg["name"]
    parser = PARSERS[site_cfg["parser"]]
    url = site_cfg["url"]
    try:
        response = http_get(url, cfg=cfg, headers=HEADERS)
        response.raise_for_status()
        rows = parser(BeautifulSoup(response.text, "html.parser"), url)
    except Exception as exc:
        log.warning("官方更新 [%s] 拉取失败: %s", name, exc)
        return name, [], "failed"

    dated = [row for row in rows if row.get("date") and row["date"] <= as_of]
    newest = max((row["date"] for row in dated), default=None)
    if newest is None:
        log.warning("官方更新 [%s] 缺少可用发布时间", name)
        return name, [], "undated"

    source_cfg = cfg["sources"]["official_updates"]
    max_staleness = timedelta(hours=source_cfg.get("max_staleness_hours", 120))
    if as_of - newest > max_staleness:
        log.info("官方更新 [%s] 暂无近期内容", name)
        return name, [], "stale"
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
            meta={"published": row["date"].isoformat(), "first_party": True},
        ))
        if len(items) >= site_cfg.get("max_items", 8):
            break
    log.info("官方更新 [%s] 收到 %d 条", name, len(items))
    return name, items, "ok" if items else "empty"


def collect(cfg: dict, today) -> list[NewsItem]:
    source_cfg = cfg["sources"].get("official_updates", {})
    if not source_cfg.get("enabled", True):
        return []
    if not cfg["sections"].get("industry", {}).get("enabled", True):
        return []
    as_of = report_end_utc(today, cfg.get("timezone", "Asia/Shanghai"))
    items = []
    statuses = {}
    for site_cfg in source_cfg.get("sites", []):
        name, site_items, status = _collect_site(cfg, site_cfg, as_of)
        statuses[name] = {"status": status, "received": len(site_items)}
        items.extend(site_items)
    cfg.setdefault("_collector_status", {})["official_updates"] = {"sites": statuses}
    return items
