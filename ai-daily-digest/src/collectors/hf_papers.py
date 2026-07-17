"""HuggingFace Daily Papers 采集器。"""
import logging
from datetime import date, timedelta

from ..http_client import get as http_get
from ..models import NewsItem

log = logging.getLogger(__name__)

API = "https://huggingface.co/api/daily_papers"
HEADERS = {"User-Agent": "Mozilla/5.0 (daily-report-bot)"}


def collect(cfg: dict, today: date) -> list[NewsItem]:
    src_cfg = cfg["sources"]["hf_papers"]
    max_fetch = src_cfg.get("max_fetch", 16)

    # 时区原因当天可能还没有数据，最多向前回退 3 天
    data = []
    for offset in range(4):
        d = today - timedelta(days=offset)
        try:
            resp = http_get(API, cfg=cfg, params={"date": d.isoformat()},
                            headers=HEADERS)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.warning("HF papers %s 请求失败: %s", d, e)
            continue
        if data:
            log.info("HF papers 使用日期 %s，共 %d 篇", d, len(data))
            break

    items = []
    for entry in data:
        paper = entry.get("paper", {})
        pid = paper.get("id")
        if not pid:
            continue
        items.append(NewsItem(
            id=f"arxiv:{pid}",
            section="papers",
            title=paper.get("title", "").strip(),
            url=f"https://huggingface.co/papers/{pid}",
            source="HF Papers",
            text=(paper.get("summary") or "")[:1500],
            score=float(paper.get("upvotes") or 0),
            meta={"comments": entry.get("numComments", 0)},
        ))

    items.sort(key=lambda x: x.score, reverse=True)
    return items[:max_fetch]
