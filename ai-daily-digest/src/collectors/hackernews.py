"""Hacker News 高分讨论采集器（Algolia 搜索 API）。"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta

from ..http_client import get as http_get
from ..models import NewsItem
from ..utils import report_end_utc

log = logging.getLogger(__name__)

API = "https://hn.algolia.com/api/v1/search"
HEADERS = {"User-Agent": "Mozilla/5.0 (daily-report-bot)"}


def collect(cfg: dict, today) -> list[NewsItem]:
    src_cfg = cfg["sources"]["hackernews"]
    min_points = src_cfg.get("min_points", 40)
    lookback_h = src_cfg.get("lookback_hours", 30)
    as_of = report_end_utc(today, cfg.get("timezone", "Asia/Shanghai"))
    since = int((as_of - timedelta(hours=lookback_h)).timestamp())
    until = int(as_of.timestamp())

    seen = set()
    items = []

    def _search(query: str):
        try:
            resp = http_get(API, cfg=cfg, params={
                "query": query,
                "tags": "story",
                "numericFilters": (
                    f"created_at_i>={since},created_at_i<={until},points>={min_points}"
                ),
                "hitsPerPage": 20,
            }, headers=HEADERS)
            resp.raise_for_status()
            return query, resp.json().get("hits", [])
        except Exception as e:
            log.warning("HN 查询 [%s] 失败: %s", query, e)
            return query, []

    queries = src_cfg.get("queries", ["LLM"])
    results = {}
    workers = min(src_cfg.get("workers", 5), max(1, len(queries)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="hn") as pool:
        futures = [pool.submit(_search, query) for query in queries]
        for future in as_completed(futures):
            query, hits = future.result()
            results[query] = hits

    # 按配置顺序合并，确保并发不会改变相同分数下的稳定顺序。
    for query in queries:
        hits = results.get(query, [])
        for hit in hits:
            oid = hit.get("objectID")
            if not oid or oid in seen:
                continue
            seen.add(oid)
            hn_url = f"https://news.ycombinator.com/item?id={oid}"
            items.append(NewsItem(
                id=f"hn:{oid}",
                section="community",
                title=hit.get("title", ""),
                url=hit.get("url") or hn_url,
                source="Hacker News",
                text=f"{hit.get('points', 0)} points, "
                     f"{hit.get('num_comments', 0)} comments. 讨论: {hn_url}",
                score=float(hit.get("points") or 0),
                meta={
                    "hn_url": hn_url,
                    "discussion_url": hn_url,
                    "points": hit.get("points", 0),
                    "comments": hit.get("num_comments", 0),
                },
            ))
    items.sort(key=lambda x: x.score, reverse=True)
    log.info("HN 命中 %d 条", len(items))
    return items
