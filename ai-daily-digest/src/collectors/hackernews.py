"""Hacker News 高分讨论采集器（Algolia 搜索 API）。"""
import logging
import time

import requests

from ..models import NewsItem

log = logging.getLogger(__name__)

API = "https://hn.algolia.com/api/v1/search"
HEADERS = {"User-Agent": "Mozilla/5.0 (daily-report-bot)"}


def collect(cfg: dict, today) -> list[NewsItem]:
    src_cfg = cfg["sources"]["hackernews"]
    min_points = src_cfg.get("min_points", 40)
    lookback_h = src_cfg.get("lookback_hours", 30)
    since = int(time.time()) - lookback_h * 3600

    seen = set()
    items = []
    for query in src_cfg.get("queries", ["LLM"]):
        try:
            resp = requests.get(API, params={
                "query": query,
                "tags": "story",
                "numericFilters": f"created_at_i>{since},points>{min_points}",
                "hitsPerPage": 20,
            }, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
        except Exception as e:
            log.warning("HN 查询 [%s] 失败: %s", query, e)
            continue

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
                meta={"hn_url": hn_url,
                      "comments": hit.get("num_comments", 0)},
            ))
    items.sort(key=lambda x: x.score, reverse=True)
    log.info("HN 命中 %d 条", len(items))
    return items
