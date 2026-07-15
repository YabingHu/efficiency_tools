"""arXiv 新论文采集器（官方 Atom API）。"""
import logging
from datetime import datetime, timedelta, timezone

import feedparser
import requests

from ..models import NewsItem

log = logging.getLogger(__name__)

API = "https://export.arxiv.org/api/query"
HEADERS = {"User-Agent": "Mozilla/5.0 (daily-report-bot)"}


def collect(cfg: dict, today) -> list[NewsItem]:
    src_cfg = cfg["sources"]["arxiv"]
    cats = src_cfg.get("categories", ["cs.CL"])
    keywords = [k.lower() for k in src_cfg.get("keywords", [])]
    lookback = timedelta(hours=src_cfg.get("lookback_hours", 36))

    query = " OR ".join(f"cat:{c}" for c in cats)
    try:
        resp = requests.get(API, params={
            "search_query": query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": src_cfg.get("max_results", 80),
        }, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        log.warning("arXiv 请求失败: %s", e)
        return []

    feed = feedparser.parse(resp.content)
    if not feed.entries:
        log.warning("arXiv 返回空 feed")
        return []

    def _pub(entry):
        try:
            return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        except Exception:
            return None

    # arXiv 周末/节假日不发布新论文，固定回看窗口会落空；
    # 改为以 feed 中最新一批论文的时间为基准向前取 lookback 窗口
    newest = max((t for t in (_pub(e) for e in feed.entries) if t), default=None)
    if newest is None:
        return []
    cutoff = newest - lookback
    items = []
    for entry in feed.entries:
        published = _pub(entry)
        if published is None or published < cutoff:
            continue
        blob = (entry.title + " " + entry.summary).lower()
        if keywords and not any(k in blob for k in keywords):
            continue
        arxiv_id = entry.id.split("/abs/")[-1].split("v")[0]
        items.append(NewsItem(
            id=f"arxiv:{arxiv_id}",
            section="arxiv",
            title=" ".join(entry.title.split()),
            url=f"https://arxiv.org/abs/{arxiv_id}",
            source="arXiv",
            text=" ".join(entry.summary.split())[:1500],
            meta={"published": published.isoformat()},
        ))
    log.info("arXiv 命中 %d 篇", len(items))
    return items
