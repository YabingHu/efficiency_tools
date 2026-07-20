"""arXiv 新论文采集器（官方 Atom API，失败时回退到 CDN RSS）。"""
import logging
import re
from datetime import UTC, datetime, timedelta

import feedparser

from ..http_client import get as http_get
from ..models import NewsItem
from ..utils import report_end_utc

log = logging.getLogger(__name__)

API = "https://export.arxiv.org/api/query"
# export.arxiv.org 对云端 IP 限流激进（GitHub Actions runner 常年被拒），
# rss.arxiv.org 走 CDN，作为兜底通道。
RSS = "https://rss.arxiv.org/rss/"
HEADERS = {"User-Agent": "Mozilla/5.0 (daily-report-bot)"}
# RSS 兜底只要新提交和跨类新收录，排除对已有论文的修订（replace / replace-cross）。
RSS_ANNOUNCE_TYPES = {"new", "cross"}
# RSS 摘要带有 "arXiv:2607.15280v1 Announce Type: new Abstract: ..." 前缀，送模型前剥掉。
RSS_SUMMARY_PREFIX = re.compile(
    r"^\s*arXiv:\S+\s*Announce Type:\s*\S+\s*(?:Abstract:\s*)?", re.I
)


def _published(entry) -> datetime | None:
    try:
        return datetime(*entry.published_parsed[:6], tzinfo=UTC)
    except Exception:
        return None


def _arxiv_id(entry) -> str:
    """API 的 id 是 abs 链接，RSS 的 id 是 oai:arXiv.org:<id>；统一从链接取。"""
    raw = getattr(entry, "link", "") or getattr(entry, "id", "")
    return raw.split("/abs/")[-1].split(":")[-1].split("v")[0].strip()


def _make_item(entry, published: datetime, keywords: list[str]) -> NewsItem | None:
    title = " ".join(entry.title.split())
    summary = RSS_SUMMARY_PREFIX.sub("", " ".join(entry.summary.split()))
    if keywords and not any(k in f"{title} {summary}".lower() for k in keywords):
        return None
    arxiv_id = _arxiv_id(entry)
    if not arxiv_id:
        return None
    return NewsItem(
        id=f"arxiv:{arxiv_id}",
        section="arxiv",
        title=title,
        url=f"https://arxiv.org/abs/{arxiv_id}",
        source="arXiv",
        text=summary[:1500],
        meta={"published": published.isoformat()},
    )


def _timeout(cfg: dict, src_cfg: dict) -> tuple[int, int]:
    return (
        cfg.get("http", {}).get("connect_timeout_seconds", 5),
        src_cfg.get("read_timeout_seconds", 20),
    )


def _collect_from_api(
    cfg: dict, src_cfg: dict, as_of: datetime, keywords: list[str]
) -> list[NewsItem]:
    lookback = timedelta(hours=src_cfg.get("lookback_hours", 36))
    max_staleness = timedelta(hours=src_cfg.get("max_staleness_hours", 120))
    cats = src_cfg.get("categories", ["cs.CL"])

    category_query = " OR ".join(f"cat:{c}" for c in cats)
    range_start = as_of - max_staleness
    submitted_range = (
        f"submittedDate:[{range_start.strftime('%Y%m%d%H%M')} "
        f"TO {as_of.strftime('%Y%m%d%H%M')}]"
    )
    try:
        resp = http_get(
            API,
            cfg=cfg,
            retries=src_cfg.get("retries", 1),
            timeout=_timeout(cfg, src_cfg),
            params={
                "search_query": f"({category_query}) AND {submitted_range}",
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "max_results": src_cfg.get("max_results", 50),
            },
            headers=HEADERS,
        )
        resp.raise_for_status()
    except Exception as e:
        log.warning("arXiv API 请求失败: %s", e)
        return []

    feed = feedparser.parse(resp.content)
    if not feed.entries:
        log.warning("arXiv API 返回空 feed")
        return []

    # 周末允许回退到最近一批，但绝不越过目标报告日期或最大陈旧阈值。
    newest = max(
        (t for t in (_published(e) for e in feed.entries) if t and t <= as_of),
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
        published = _published(entry)
        if published is None or published < cutoff or published > as_of:
            continue
        item = _make_item(entry, published, keywords)
        if item is not None:
            items.append(item)
    log.info("arXiv API 命中 %d 篇", len(items))
    return items


def _collect_from_rss(
    cfg: dict, src_cfg: dict, as_of: datetime, keywords: list[str]
) -> list[NewsItem]:
    """CDN 兜底通道。只有当期公告，没有历史，所以回补历史日期时会自然返回空。"""
    max_staleness = timedelta(hours=src_cfg.get("max_staleness_hours", 120))
    categories = "+".join(src_cfg.get("categories", ["cs.CL"]))
    try:
        resp = http_get(
            RSS + categories,
            cfg=cfg,
            retries=src_cfg.get("retries", 1),
            timeout=_timeout(cfg, src_cfg),
            headers=HEADERS,
        )
        resp.raise_for_status()
    except Exception as e:
        log.warning("arXiv RSS 兜底请求失败: %s", e)
        return []

    feed = feedparser.parse(resp.content)
    if not feed.entries:
        log.warning("arXiv RSS 返回空 feed")
        return []

    items = []
    for entry in feed.entries:
        if getattr(entry, "arxiv_announce_type", "new") not in RSS_ANNOUNCE_TYPES:
            continue
        published = _published(entry)
        if published is None or published > as_of or as_of - published > max_staleness:
            continue
        item = _make_item(entry, published, keywords)
        if item is not None:
            items.append(item)
    items = items[:src_cfg.get("max_results", 50)]
    log.info("arXiv RSS 兜底命中 %d 篇", len(items))
    return items


def collect(cfg: dict, today) -> list[NewsItem]:
    src_cfg = cfg["sources"]["arxiv"]
    keywords = [k.lower() for k in src_cfg.get("keywords", [])]
    as_of = report_end_utc(today, cfg.get("timezone", "Asia/Shanghai"))

    items = _collect_from_api(cfg, src_cfg, as_of, keywords)
    if items:
        return items
    log.warning("arXiv API 无可用结果，回退到 RSS 通道")
    return _collect_from_rss(cfg, src_cfg, as_of, keywords)
