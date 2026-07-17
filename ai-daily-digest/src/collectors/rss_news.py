"""RSS 业界动态采集器。"""
import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta

import feedparser
from bs4 import BeautifulSoup

from ..http_client import get as http_get
from ..models import NewsItem
from ..utils import report_end_utc, safe_http_url

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) daily-report-bot"}


def _entry_time(entry):
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            return datetime(*t[:6], tzinfo=UTC)
    return None


def collect(cfg: dict, today) -> list[NewsItem]:
    src_cfg = cfg["sources"]["rss"]
    lookback = timedelta(hours=src_cfg.get("lookback_hours", 36))
    max_staleness = timedelta(hours=src_cfg.get("max_staleness_hours", 96))
    max_items = src_cfg.get("max_items_per_feed", 20)
    as_of = report_end_utc(today, cfg.get("timezone", "Asia/Shanghai"))
    enabled_sections = {
        key for key, section in cfg["sections"].items()
        if section.get("enabled", True)
    }

    def _collect_feed(feed_cfg: dict) -> tuple[str, list[NewsItem]]:
        name, url = feed_cfg["name"], feed_cfg["url"]
        section = feed_cfg.get("section", "industry")
        if section not in enabled_sections:
            return name, []
        try:
            resp = http_get(url, cfg=cfg, headers=HEADERS)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
        except Exception as e:
            log.warning("RSS [%s] 拉取失败: %s", name, e)
            return name, []

        dated = []
        for entry in feed.entries:
            published = _entry_time(entry)
            if published is not None and published <= as_of:
                dated.append((published, entry))
        newest = max((ts for ts, _ in dated), default=None)
        if newest is None:
            log.warning("RSS [%s] 缺少可用发布时间，跳过以避免陈旧内容", name)
            return name, []
        if as_of - newest > max_staleness:
            log.warning("RSS [%s] 最新内容已陈旧 %s，跳过", name, as_of - newest)
            return name, []
        cutoff = newest - lookback

        feed_items = []
        for ts, entry in sorted(dated, key=lambda pair: pair[0], reverse=True):
            if ts < cutoff:
                continue
            link = safe_http_url(getattr(entry, "link", ""))
            raw = getattr(entry, "summary", "") or ""
            text = " ".join(BeautifulSoup(raw, "html.parser").get_text().split())
            title = " ".join(getattr(entry, "title", "").split())
            if not title and text:
                # 部分源（如 BAAI link 的公众号镜像）条目无标题，取正文首句
                title = re.split(r"(?<=[。！？!?])", text, maxsplit=1)[0][:80]
            if not link or not title:
                continue
            uid = hashlib.md5(link.encode()).hexdigest()[:12]
            feed_items.append(NewsItem(
                id=f"rss:{uid}",
                section=section,
                title=title,
                url=link,
                source=name,
                text=text[:1000],
                meta={"published": ts.isoformat() if ts else ""},
            ))
            if len(feed_items) >= max_items:
                break
        log.info("RSS [%s] 收到 %d 条", name, len(feed_items))
        return name, feed_items

    feeds = src_cfg.get("feeds", [])
    workers = min(src_cfg.get("workers", 6), max(1, len(feeds)))
    results = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rss") as pool:
        futures = [pool.submit(_collect_feed, feed_cfg) for feed_cfg in feeds]
        for future in as_completed(futures):
            name, feed_items = future.result()
            results[name] = feed_items

    items = []
    for feed_cfg in feeds:
        items.extend(results.get(feed_cfg["name"], []))

    # 各 feed 内按时间倒序后轮流交错排列：既照顾时效，
    # 又避免高产 feed（如公众号镜像）在预裁剪时霸占版面
    by_feed: dict[str, list[NewsItem]] = {}
    for it in items:
        by_feed.setdefault(it.source, []).append(it)
    for lst in by_feed.values():
        lst.sort(key=lambda x: x.meta.get("published", ""), reverse=True)
    interleaved = []
    while any(by_feed.values()):
        for lst in by_feed.values():
            if lst:
                interleaved.append(lst.pop(0))
    return interleaved
