"""RSS 业界动态采集器。"""
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone

import feedparser
import requests
from bs4 import BeautifulSoup

from ..models import NewsItem

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) daily-report-bot"}


def _entry_time(entry):
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def collect(cfg: dict, today) -> list[NewsItem]:
    src_cfg = cfg["sources"]["rss"]
    lookback = timedelta(hours=src_cfg.get("lookback_hours", 36))

    items = []
    for feed_cfg in src_cfg.get("feeds", []):
        name, url = feed_cfg["name"], feed_cfg["url"]
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
        except Exception as e:
            log.warning("RSS [%s] 拉取失败: %s", name, e)
            continue

        # 公司博客周末/节假日不更新，以"现在"为基准的固定回看窗口会落空；
        # 改为以该源最新一篇的发布时间为基准向前取 lookback 窗口
        newest = max((t for t in (_entry_time(e) for e in feed.entries) if t),
                     default=None)
        cutoff = newest - lookback if newest else None

        count = 0
        for entry in feed.entries:
            ts = _entry_time(entry)
            if ts is not None and cutoff is not None and ts < cutoff:
                continue
            link = getattr(entry, "link", "")
            raw = getattr(entry, "summary", "") or ""
            text = " ".join(BeautifulSoup(raw, "html.parser").get_text().split())
            title = " ".join(getattr(entry, "title", "").split())
            if not title and text:
                # 部分源（如 BAAI link 的公众号镜像）条目无标题，取正文首句
                title = re.split(r"(?<=[。！？!?])", text, maxsplit=1)[0][:80]
            if not link or not title:
                continue
            uid = hashlib.md5(link.encode()).hexdigest()[:12]
            items.append(NewsItem(
                id=f"rss:{uid}",
                section="industry",
                title=title,
                url=link,
                source=name,
                text=text[:1000],
                meta={"published": ts.isoformat() if ts else ""},
            ))
            count += 1
        log.info("RSS [%s] 收到 %d 条", name, count)

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
