"""Small, local author-feed experiment using pinned upstream clients.

Run with .external-skills/cn-pilot-venv/Scripts/python.exe -m src.cn_pilot.
Browser profiles and extracted samples stay under .private/cn-pilot.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import importlib.util
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".private/cn-pilot"
MEDIA = ROOT / ".external-skills/mediacrawler-pilot"
NEWS = ROOT / ".external-skills/newscrawler-pilot"
PINS = {
    "mediacrawler-pilot": "8f583999006d5b692272c608440e193ca282e73b",
    "newscrawler-pilot": "25fb3b4a20186905f5ce38f7a7f854050d402253",
}
AUTHORS = {
    "weibo": {"name": "宝玉xp", "id": "1727858283", "url": "https://weibo.com/u/1727858283"},
    "zhihu": {
        "name": "苏剑林",
        "id": "su-jian-lin-22",
        "url": "https://www.zhihu.com/people/su-jian-lin-22",
    },
}
HOMES = {"weibo": "https://m.weibo.cn", "zhihu": "https://www.zhihu.com"}


def text_only(value: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", value or "")).strip()


def normalize(
    platform: str,
    rows: list,
    limit: int = 5,
    *,
    since: datetime | None = None,
    author: str | None = None,
) -> list[dict]:
    """Export only article fields; upstream responses/cookies never reach samples."""
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if platform == "weibo":
            row = row.get("mblog") or {}
            ident = str(row.get("id") or "")
            if not ident.isdigit():
                continue
            body = text_only(row.get("text", ""))
            url = f"https://m.weibo.cn/detail/{ident}"
            title = body[:100]
            try:
                published = parsedate_to_datetime(row.get("created_at", "")).isoformat()
            except (ValueError, TypeError):
                published = ""
        else:
            ident = str(row.get("id") or "")
            if not ident.isdigit():
                continue
            kind = row.get("type")
            if kind == "answer":
                question = row.get("question") or {}
                question_id = str(question.get("id") or "")
                if not question_id.isdigit():
                    continue
                url = f"https://www.zhihu.com/question/{question_id}/answer/{ident}"
                title = question.get("title", "")
            elif kind == "article":
                url, title = f"https://zhuanlan.zhihu.com/p/{ident}", row.get("title", "")
            else:
                continue
            body = text_only(row.get("content") or row.get("excerpt") or "")
            stamp = row.get("created_time") or row.get("created")
            try:
                published = datetime.fromtimestamp(float(stamp), UTC).isoformat()
            except (ValueError, TypeError, OverflowError, OSError):
                published = ""
        if not body or url in seen:
            continue
        if since is not None and (not published or datetime.fromisoformat(published) < since):
            continue
        seen.add(url)
        result.append(
            {
                "platform": platform,
                "author": author or AUTHORS[platform]["name"],
                "title": text_only(title),
                "url": url,
                "published_at": published,
                "text": body[:20000],
            }
        )
        if len(result) >= limit:
            break
    return result


def verify_checkout(path: Path) -> None:
    actual = subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=10,
    ).strip()
    if actual != PINS[path.name]:
        raise RuntimeError("upstream_revision_mismatch")


def prepare_media() -> None:
    verify_checkout(MEDIA)
    sys.path.insert(0, str(MEDIA))
    # PyExecJS requires Node; Playwright ships a private executable we can reuse.
    spec = importlib.util.find_spec("playwright")
    if not shutil.which("node") and spec and spec.origin:
        driver = Path(spec.origin).parent / "driver"
        os.environ["PATH"] = str(driver) + os.pathsep + os.environ.get("PATH", "")


async def browser(platform: str, headless: bool):
    from playwright.async_api import async_playwright

    manager = await async_playwright().start()
    try:
        encoded = os.environ.get("CN_BROWSER_STATE", "")
        if encoded:
            states = json.loads(base64.b64decode(encoded, validate=True))
            instance = await manager.chromium.launch(channel="chrome", headless=headless)
            context = await instance.new_context(storage_state=states.get(platform, {}))
            return manager, context
        profile = PRIVATE / "profiles" / platform
        profile.mkdir(parents=True, exist_ok=True)
        context = await manager.chromium.launch_persistent_context(
            str(profile),
            channel="chrome",
            headless=headless,
            viewport={"width": 1200, "height": 850},
        )
        return manager, context
    except BaseException:
        await manager.stop()
        raise


async def logged_in(context, platform: str) -> bool:
    cookies = await context.cookies([HOMES[platform]])
    required = "SUB" if platform == "weibo" else "z_c0"
    return any(c["name"] == required and c["value"] for c in cookies)


async def login(platform: str, seconds: int) -> dict:
    manager, context = await browser(platform, headless=False)
    try:
        page = context.pages[0] if context.pages else await context.new_page()
        from playwright.async_api import TimeoutError as BrowserTimeout

        # Keep the window open for the user's normal login/verification.
        with contextlib.suppress(BrowserTimeout):
            await page.goto(HOMES[platform], wait_until="domcontentloaded", timeout=30000)
        deadline = asyncio.get_running_loop().time() + seconds
        while asyncio.get_running_loop().time() < deadline:
            if await logged_in(context, platform):
                return {"platform": platform, "status": "session_saved"}
            if not context.pages:
                return {"platform": platform, "status": "login_cancelled"}
            await asyncio.sleep(2)
        return {"platform": platform, "status": "login_timeout"}
    finally:
        await context.close()
        await manager.stop()


async def collect(platform: str, *, author_info: dict | None = None, feed: bool = False) -> dict:
    author_info = author_info or AUTHORS[platform]
    prepare_media()
    manager, context = await browser(platform, headless=True)
    try:
        if not await logged_in(context, platform):
            return {"platform": platform, "status": "login_required", "count": 0}
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(HOMES[platform], wait_until="domcontentloaded", timeout=30000)
        cookies = {c["name"]: c["value"] for c in await context.cookies([HOMES[platform]])}
        cookie_text = "; ".join(f"{k}={v}" for k, v in cookies.items())
        headers = {
            "User-Agent": await page.evaluate("navigator.userAgent"),
            "Referer": HOMES[platform],
            "Origin": HOMES[platform],
        }
        # Suppress upstream diagnostics: some errors contain full HTTP bodies.
        logging.disable(logging.CRITICAL)
        previous_cwd = Path.cwd()
        try:
            os.chdir(MEDIA)  # Zhihu's client loads libs/zhihu.js relative to cwd.
            if platform == "weibo":
                from media_platform.weibo.client import WeiboClient

                headers["Cookie"] = cookie_text
                client = WeiboClient(
                    timeout=15, headers=headers, playwright_page=page, cookie_dict=cookies
                )
                # Disable upstream retry loops for this small diagnostic run.
                from tenacity import stop_after_attempt

                client.request = client.request.retry_with(stop=stop_after_attempt(1)).__get__(
                    client, type(client)
                )
                response = await client.get_notes_by_creator(
                    author_info["id"], "107603" + author_info["id"]
                )
                rows = response.get("cards") or []
                # One page only. Enrich at most three relevant long posts;
                # replies and unrelated posts must not consume the detail budget.
                if feed:
                    from .editorial import has_community_ai_context

                    attempts = 0
                    for row in rows:
                        mblog = row.get("mblog") or {}
                        if not mblog.get("isLongText") or not has_community_ai_context(
                            "", text_only(mblog.get("text", ""))
                        ):
                            continue
                        if attempts >= 3:
                            break
                        attempts += 1
                        await asyncio.sleep(2)
                        try:
                            detail = await client.get_note_info_by_id(str(mblog["id"]))
                            if detail and detail.get("mblog"):
                                row["mblog"] = detail["mblog"]
                        except Exception:
                            break  # A rejected detail request ends enrichment for this author.
            else:
                from media_platform.zhihu.client import ZhiHuClient
                from tenacity import stop_after_attempt

                headers["cookie"] = cookie_text
                client = ZhiHuClient(
                    timeout=15, headers=headers, playwright_page=page, cookie_dict=cookies
                )
                client.request = client.request.retry_with(stop=stop_after_attempt(1)).__get__(
                    client, type(client)
                )
                answers = await client.get_creator_answers(author_info["id"], limit=3)
                await asyncio.sleep(2)
                articles = await client.get_creator_articles(author_info["id"], limit=2)
                rows = (answers.get("data") or []) + (articles.get("data") or [])
            received = normalize(
                platform, rows, limit=20 if feed else 5, author=author_info["name"]
            )
            items = normalize(
                platform,
                rows,
                limit=20 if feed else 5,
                since=datetime.now(UTC) - timedelta(hours=48),
                author=author_info["name"],
            )
        finally:
            os.chdir(previous_cwd)
        if not feed:
            save_samples(platform, items)
        # Keep an explicitly named historical probe to distinguish a working
        # author endpoint from an author with no posts in the current time window.
        if not feed:
            save_samples(f"{platform}-probe", received)
        return {
            "platform": platform,
            "status": "ok" if items else "empty_recent" if received else "empty",
            "count": len(items),
            "received_items": len(rows),
            "valid_items": len(received),
            "latest_published_at": max((r["published_at"] for r in received), default=""),
            **({"items": received} if feed else {}),
        }
    finally:
        await context.close()
        await manager.stop()


def save_samples(platform: str, items: list[dict]) -> None:
    PRIVATE.mkdir(parents=True, exist_ok=True)
    (PRIVATE / f"{platform}-samples.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )


async def render_article(url: str) -> str:
    """Try the normal installed browser once; do not solve verification challenges."""
    from playwright.async_api import TimeoutError as BrowserTimeout

    manager, context = await browser("toutiao", headless=True)
    try:
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_selector("article", timeout=15000)
        except BrowserTimeout:
            return ""
        final = urlsplit(page.url)
        expected = urlsplit(url)
        if (final.scheme, final.hostname, final.path.rstrip("/")) != (
            "https",
            "www.toutiao.com",
            expected.path.rstrip("/"),
        ):
            return ""
        return await page.content()
    finally:
        await context.close()
        await manager.stop()


def toutiao(url: str, *, feed: bool = False) -> dict:
    if not re.fullmatch(r"https://www\.toutiao\.com/article/\d+/?", url):
        raise ValueError("invalid_toutiao_article_url")
    verify_checkout(NEWS)
    scripts = NEWS / ".claude/skills/news-extractor/scripts"
    sys.path.insert(0, str(scripts))
    import requests
    from crawlers.toutiao import RequestHeaders, ToutiaoNewsCrawler

    # Explicitly replace upstream's baked-in Cookie; no shared credentials.
    crawler = ToutiaoNewsCrawler(url, headers=RequestHeaders(cookie=""))
    crawler.logger.disabled = True
    with requests.get(
        url, headers=crawler.headers, timeout=15, allow_redirects=False, stream=True
    ) as response:
        if response.status_code != 200:
            return {"platform": "toutiao", "status": f"http_{response.status_code}", "count": 0}
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > 2 * 1024 * 1024:
                raise ValueError("response_too_large")
            chunks.append(chunk)
        html = b"".join(chunks).decode("utf-8", errors="replace")
    fetch_mode = "http"
    try:
        item = crawler.parse_content(html)
    except ValueError:
        html = asyncio.run(render_article(url))
        if not html:
            return {"platform": "toutiao", "status": "article_unavailable", "count": 0}
        item = crawler.parse_content(html)
        fetch_mode = "browser"
    body = "\n".join(item.texts)
    if len(body) < 160:
        return {"platform": "toutiao", "status": "empty_article", "count": 0}
    items = [
        {
            "platform": "toutiao",
            "title": item.title,
            "url": url,
            "author": item.meta_info.author_name,
            "published_at": item.meta_info.publish_time,
            "text": body[:20000],
        }
    ]
    if not feed:
        save_samples("toutiao", items)
    return {
        "platform": "toutiao",
        "status": "ok",
        "count": 1,
        "body_chars": len(body),
        "fetch_mode": fetch_mode,
        **({"items": items} if feed else {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["doctor", "login", "collect", "toutiao", "feed"])
    parser.add_argument("--platform", choices=list(AUTHORS), default="weibo")
    parser.add_argument("--wait", type=int, default=900, help="Seconds to wait for manual login")
    parser.add_argument("--url", default="https://www.toutiao.com/article/7660109634812559924/")
    args = parser.parse_args()
    PRIVATE.mkdir(parents=True, exist_ok=True)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    request = json.load(sys.stdin) if args.command == "feed" else {}
    try:
        # Never persist upstream output; even tracebacks can contain request data.
        with (
            open(os.devnull, "w") as sink,
            contextlib.redirect_stdout(sink),
            contextlib.redirect_stderr(sink),
        ):
            if args.command == "doctor":
                prepare_media()
                verify_checkout(NEWS)
                from media_platform.weibo.client import WeiboClient  # noqa: F401
                from media_platform.zhihu.client import ZhiHuClient  # noqa: F401

                result = {
                    "status": "ready",
                    "node": bool(shutil.which("node")),
                    "authors": AUTHORS,
                    "revisions": PINS,
                }
            elif args.command == "toutiao":
                result = toutiao(args.url)
            elif args.command == "login":
                result = asyncio.run(login(args.platform, args.wait))
            elif args.command == "feed" and request.get("url"):
                result = toutiao(request["url"], feed=True)
            else:

                async def bounded():
                    return await asyncio.wait_for(
                        collect(
                            args.platform,
                            author_info=request.get("author"),
                            feed=args.command == "feed",
                        ),
                        timeout=90,
                    )

                result = asyncio.run(bounded())
    except Exception as exc:
        # Exception type is safe; exception messages may expose cookies/response bodies.
        result = {
            "platform": args.platform if args.command != "toutiao" else "toutiao",
            "status": "failed",
            "error_type": type(exc).__name__,
        }
    result["checked_at"] = datetime.now(UTC).isoformat()
    print(json.dumps(result, ensure_ascii=False))
    if args.command != "feed":
        (
            PRIVATE / f"{args.command}-{result.get('platform', 'environment')}-status.json"
        ).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["status"] in {"ready", "ok", "empty_recent", "session_saved"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
