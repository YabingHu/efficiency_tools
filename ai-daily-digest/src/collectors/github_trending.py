"""GitHub Trending（日榜）采集器。"""
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from ..http_client import get as http_get
from ..models import NewsItem

log = logging.getLogger(__name__)

URL = "https://github.com/trending?since=daily"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) daily-report-bot"}
MAX_CONTENT_BYTES = 2 * 1024 * 1024


def _page_content(url: str, cfg: dict, selector: str) -> str:
    """仅抓取 GitHub 指定正文节点，限制重定向、响应大小与等待时间。"""
    timeout = cfg["sources"]["github"].get("content_timeout_seconds", 10)
    for _ in range(4):
        response = http_get(
            url, cfg=cfg, headers=HEADERS, stream=True, allow_redirects=False,
            timeout=(5, timeout), retries=0,
        )
        try:
            if 300 <= response.status_code < 400:
                location = response.headers.get("Location")
                if not location:
                    return ""
                target = urljoin(url, location)
                parsed = urlsplit(target)
                if parsed.scheme != "https" or parsed.netloc != "github.com":
                    return ""
                url = target
                continue
            if response.status_code == 404:
                return ""
            response.raise_for_status()
            chunks, total = [], 0
            for chunk in response.iter_content(chunk_size=16384):
                total += len(chunk)
                if total > MAX_CONTENT_BYTES:
                    return ""
                chunks.append(chunk)
            soup = BeautifulSoup(b"".join(chunks).decode("utf-8", errors="replace"), "html.parser")
            article = soup.select_one(selector)
            if article is None:
                return ""
            for node in article.select("script, style, svg, img, nav"):
                node.decompose()
            return article.get_text("\n", strip=True)[:6000]
        finally:
            response.close()
    return ""


def _enrich_item(item: NewsItem, cfg: dict) -> NewsItem:
    # Release 放在前面，避免被摘要输入长度截断；为 README 单独保留足够空间。
    parts = [item.text] if item.text else []
    for name, url, selector, max_chars in (
        ("README", item.url, "article.markdown-body", 3600),
        ("最新 Release", item.url + "/releases/latest", ".markdown-body", 1000),
    ):
        try:
            content = _page_content(url, cfg, selector)
        except Exception as exc:
            log.warning("GitHub %s 补读失败 [%s]: %s", name, item.id, type(exc).__name__)
            continue
        if content:
            item.meta["readme_available" if name == "README" else "release_available"] = True
            block = f"{name}：\n{content[:max_chars]}"
            if name == "README":
                parts.append(block)
            else:
                parts.insert(0, block)
    item.text = "\n\n".join(parts)
    return item


def _matches_keyword(text: str, keyword: str) -> bool:
    if not keyword.isascii():
        return keyword in text
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(keyword) + r"s?(?![a-z])", text))


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
    matched = []
    seen = set()
    for row in rows:
        a = row.select_one("h2 a")
        if not a or not a.get("href"):
            continue
        repo = a["href"].strip("/")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or repo in seen:
            continue
        seen.add(repo)
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
        if any(_matches_keyword(blob, keyword) for keyword in keywords):
            matched.append(item)

    # 不用无关项目补满；仅为有限数量的 AI 候选抓正文，避免放大采集耗时。
    matched.sort(key=lambda item: item.score, reverse=True)
    items = matched[:max_fetch]
    fetch_limit = src_cfg.get("content_fetch_limit", 12)
    candidates = items[:fetch_limit]
    if candidates:
        workers = min(src_cfg.get("content_workers", 3), len(candidates))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(lambda item: _enrich_item(item, cfg), candidates))
    log.info("GitHub Trending 命中 %d 个（关键词匹配 %d）", len(items), len(matched))
    return items
