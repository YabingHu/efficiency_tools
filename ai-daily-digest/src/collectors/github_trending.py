"""GitHub Trending（日榜）采集器。"""
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from ..http_client import get as http_get
from ..models import NewsItem

log = logging.getLogger(__name__)

URL = "https://github.com/trending?since=daily"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) daily-report-bot"}


def collect(cfg: dict, today) -> list[NewsItem]:
    current_date = datetime.now(ZoneInfo(cfg.get("timezone", "Asia/Shanghai"))).date()
    if today != current_date:
        log.warning("GitHub Trending 不支持历史回放，跳过报告日期 %s", today)
        return []

    src_cfg = cfg["sources"]["github"]
    keywords = [k.lower() for k in src_cfg.get("keywords", [])]
    max_fetch = src_cfg.get("max_fetch", 15)

    try:
        resp = http_get(URL, cfg=cfg, headers=HEADERS)
        resp.raise_for_status()
    except Exception as e:
        log.warning("GitHub Trending 请求失败: %s", e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    rows = soup.select("article.Box-row")
    matched, others = [], []
    for row in rows:
        a = row.select_one("h2 a")
        if not a or not a.get("href"):
            continue
        repo = a["href"].strip("/")
        desc_el = row.select_one("p")
        desc = " ".join(desc_el.get_text().split()) if desc_el else ""
        stars_today = 0
        star_el = row.select_one("span.d-inline-block.float-sm-right")
        if star_el:
            m = re.search(r"([\d,]+)", star_el.get_text())
            if m:
                stars_today = int(m.group(1).replace(",", ""))
        lang_el = row.select_one('[itemprop="programmingLanguage"]')
        lang = lang_el.get_text().strip() if lang_el else ""

        item = NewsItem(
            id=f"github:{repo}",
            section="github",
            title=repo,
            url=f"https://github.com/{repo}",
            source="GitHub Trending",
            text=desc,
            score=float(stars_today),
            meta={"language": lang, "stars_today": stars_today},
        )
        blob = (repo + " " + desc).lower()
        (matched if any(k in blob for k in keywords) else others).append(item)

    # 关键词命中的优先；不足则用榜单头部补齐
    items = matched[:max_fetch]
    if len(items) < max_fetch:
        items += others[: max_fetch - len(items)]
    log.info("GitHub Trending 命中 %d 个（关键词匹配 %d）", len(items), len(matched))
    return items
