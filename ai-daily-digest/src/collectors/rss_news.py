"""RSS 业界动态采集器。"""
import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import feedparser
from bs4 import BeautifulSoup

from ..content_extractor import extract_text_from_url
from ..http_client import get as http_get
from ..models import NewsItem
from ..utils import report_end_utc, safe_http_url

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) daily-report-bot"}


def _is_search_link(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.hostname in {
        "weixin.sogou.com", "www.baidu.com", "www.bing.com", "cn.bing.com",
    } and parsed.path.rstrip("/") in {"/weixin", "/s", "/search"}


def _article_link(entry) -> str:
    candidates = [getattr(entry, key, None) for key in ("feedburner_origlink", "origlink", "link")]
    candidates.extend(
        link.get("href") for link in getattr(entry, "links", [])
        if isinstance(link, dict) and link.get("rel") == "alternate"
    )
    return next((url for value in candidates if (url := safe_http_url(value or ""))
                 and not _is_search_link(url)), "")


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

    def _collect_feed(feed_cfg: dict) -> tuple[str, list[NewsItem], dict]:
        name, url = feed_cfg["name"], feed_cfg["url"]
        section = feed_cfg.get("section", "industry")
        if section not in enabled_sections:
            return name, [], {"status": "disabled"}
        try:
            resp = http_get(url, cfg=cfg, headers=HEADERS)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
        except Exception as e:
            log.warning("RSS [%s] 拉取失败: %s", name, e)
            return name, [], {"status": "failed"}

        dated = []
        for entry in feed.entries:
            published = _entry_time(entry)
            if published is not None and published <= as_of:
                dated.append((published, entry))
        newest = max((ts for ts, _ in dated), default=None)
        if newest is None:
            log.warning("RSS [%s] 缺少可用发布时间，跳过以避免陈旧内容", name)
            return name, [], {"status": "undated"}
        if as_of - newest > max_staleness:
            log.warning("RSS [%s] 最新内容已陈旧 %s，跳过", name, as_of - newest)
            return name, [], {"status": "stale"}
        cutoff = newest - lookback

        feed_items = []
        for ts, entry in sorted(dated, key=lambda pair: pair[0], reverse=True):
            if ts < cutoff:
                continue
            link = safe_http_url(getattr(entry, "link", ""))
            raw = getattr(entry, "summary", "") or ""
            if not raw:
                raw = " ".join(part.get("value", "") for part in
                               (getattr(entry, "content", []) or []) if isinstance(part, dict))
            text = " ".join(BeautifulSoup(raw, "html.parser").get_text(" ", strip=True).split())
            title = " ".join(getattr(entry, "title", "").split())
            if not title and text:
                # 部分源（如 BAAI link 的公众号镜像）条目无标题，取正文首句
                title = re.split(r"(?<=[。！？!?])", text, maxsplit=1)[0][:80]
            if not link or not title:
                continue
            article_link = _article_link(entry)
            meta = {"published": ts.isoformat()}
            if article_link:
                link = article_link
            elif _is_search_link(link):
                # RSS 只有搜索链接时保留稳定去重键，展示端改为阅读 RSS 全文。
                if len(text) < 160:
                    continue
                paragraphs = [p.get_text(" ", strip=True) for p in
                              BeautifulSoup(raw, "html.parser").find_all("p")]
                full_text = "\n\n".join(p for p in paragraphs if p) or text
                meta.update(link_status="rss_only", rss_full_text=full_text[:20000],
                            rss_truncated=len(full_text) > 20000)
            uid = hashlib.md5(link.encode()).hexdigest()[:12]
            feed_items.append(NewsItem(
                id=f"rss:{uid}",
                section=section,
                title=title,
                url=link,
                source=name,
                text=text[:4000 if section == "media" else 1000],
                meta=meta,
            ))
            if len(feed_items) >= max_items:
                break
        targets = [item for item in feed_items if len(item.text) < 160]
        targets = (
            targets[:src_cfg.get("content_fetch_limit", 6)] if feed_cfg.get("fetch_content") else []
        )
        fetch_cfg = {**cfg, "http": {**cfg.get("http", {}),
                                    "connect_timeout_seconds": 5, "read_timeout_seconds": 10}}

        def enrich(item):
            body = extract_text_from_url(
                item.url, fetch_cfg, min_chars=160, selector=feed_cfg.get("content_selector"),
            )
            if body:
                item.text = body[:4000]
            item.meta["content_fetch_status"] = "ok" if body else "unavailable"
            return bool(body)

        succeeded = 0
        if targets:
            workers = min(src_cfg.get("content_workers", 3), len(targets))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                succeeded = sum(pool.map(enrich, targets))
        status = {"status": "ok" if feed_items else "empty", "received": len(feed_items),
                  "content_fetch": {"attempted": len(targets), "succeeded": succeeded},
                  "rss_only_links": sum(
                      item.meta.get("link_status") == "rss_only" for item in feed_items
                  )}
        log.info("RSS [%s] 收到 %d 条，正文补读 %d/%d，RSS 全文 %d 条",
                 name, len(feed_items), succeeded, len(targets), status["rss_only_links"])
        return name, feed_items, status

    feeds = src_cfg.get("feeds", [])
    workers = min(src_cfg.get("workers", 6), max(1, len(feeds)))
    results = {}
    feed_statuses = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rss") as pool:
        futures = [pool.submit(_collect_feed, feed_cfg) for feed_cfg in feeds]
        for future in as_completed(futures):
            name, feed_items, status = future.result()
            results[name] = feed_items
            feed_statuses[name] = status
    cfg.setdefault("_collector_status", {})["rss"] = {"feeds": feed_statuses}

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
