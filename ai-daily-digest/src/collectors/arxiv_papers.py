"""arXiv 新论文采集器（官方 Atom API）。"""
import logging
from datetime import UTC, datetime, timedelta

import feedparser

from ..http_client import get as http_get
from ..models import NewsItem
from ..utils import report_end_utc

log = logging.getLogger(__name__)

API = "https://export.arxiv.org/api/query"
HEADERS = {"User-Agent": "Mozilla/5.0 (daily-report-bot)"}


def collect(cfg: dict, today) -> list[NewsItem]:
    src_cfg = cfg["sources"]["arxiv"]
    cats = src_cfg.get("categories", ["cs.CL"])
    keywords = [k.lower() for k in src_cfg.get("keywords", [])]
    lookback = timedelta(hours=src_cfg.get("lookback_hours", 36))
    max_staleness = timedelta(hours=src_cfg.get("max_staleness_hours", 120))
    as_of = report_end_utc(today, cfg.get("timezone", "Asia/Shanghai"))

    category_query = " OR ".join(f"cat:{c}" for c in cats)
    range_start = as_of - max_staleness
    submitted_range = (
        f"submittedDate:[{range_start.strftime('%Y%m%d%H%M')} "
        f"TO {as_of.strftime('%Y%m%d%H%M')}]"
    )
    query = f"({category_query}) AND {submitted_range}"
    try:
        resp = http_get(
            API,
            cfg=cfg,
            retries=src_cfg.get("retries", 1),
            timeout=(
                cfg.get("http", {}).get("connect_timeout_seconds", 5),
                src_cfg.get("read_timeout_seconds", 20),
            ),
            params={
                "search_query": query,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "max_results": src_cfg.get("max_results", 50),
            },
            headers=HEADERS,
        )
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
            return datetime(*entry.published_parsed[:6], tzinfo=UTC)
        except Exception:
            return None

    # 周末允许回退到最近一批，但绝不越过目标报告日期或最大陈旧阈值。
    newest = max(
        (t for t in (_pub(e) for e in feed.entries) if t and t <= as_of),
        default=None,
    )
    if newest is None:
        return []
    if as_of - newest > max_staleness:
        log.warning("arXiv 最新数据已超过陈旧阈值，跳过")
        return []
    cutoff = newest - lookback
    items = []
    for entry in feed.entries:
        published = _pub(entry)
        if published is None or published < cutoff or published > as_of:
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
