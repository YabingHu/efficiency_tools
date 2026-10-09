"""使用自己的 X 登录会话采集公开帖子，不调用付费 API。"""
import asyncio
import html
import json
import logging
import math
import os
import re
from contextlib import aclosing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ..models import NewsItem

log = logging.getLogger(__name__)
COOKIE_FILE = "x-cookies.json"


def validate_cookies(value: dict) -> dict[str, str]:
    """只接受两个必需字段；异常不得回显会话内容。"""
    if not isinstance(value, dict):
        raise ValueError("X 登录配置必须是对象")
    result = {}
    for key in ("auth_token", "ct0"):
        token = value.get(key)
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,512}", token):
            raise ValueError("X 登录配置缺少或包含无效的 auth_token / ct0")
        result[key] = token
    return result


def load_cookies(root: Path) -> dict[str, str] | None:
    values = {"auth_token": os.getenv("X_AUTH_TOKEN", ""), "ct0": os.getenv("X_CT0", "")}
    if any(values.values()):
        return validate_cookies(values)
    path = root / ".private" / COOKIE_FILE
    if not path.exists():
        return None
    try:
        return validate_cookies(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise ValueError("无法读取 X 登录配置，请重新运行 python -m src.x_setup") from exc


def _status(cfg: dict, state: str, count: int = 0, **details) -> None:
    cfg.setdefault("_collector_status", {})["x_twscrape"] = {
        "status": state, "count": count, **details,
    }
    log.info("X 免费采集: %s，%d 条", state, count)


def _create_api(root: Path):
    # 禁用依赖的遥测与原始响应日志，凭据数据库只落入私密目录。
    os.environ["TWS_TELEMETRY"] = "0"
    from twscrape import API
    from twscrape.logger import logger

    logger.disable("twscrape")
    private = root / ".private"
    private.mkdir(mode=0o700, exist_ok=True)
    database = private / "x-accounts.db"
    fd = os.open(database, os.O_CREAT | os.O_WRONLY, 0o600)
    os.close(fd)
    return API(str(database), debug=False, raise_when_no_account=True)


def _to_item(tweet, since: datetime, until: datetime) -> NewsItem | None:
    published = getattr(tweet, "date", None)
    if not isinstance(published, datetime) or published.tzinfo is None:
        return None
    if not since <= published <= until or getattr(tweet, "retweetedTweet", None):
        return None
    username = getattr(getattr(tweet, "user", None), "username", "")
    native_id = str(getattr(tweet, "id", ""))
    text = html.unescape(getattr(tweet, "rawContent", "") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", username):
        return None
    if not native_id.isdigit() or not text:
        return None
    points = max(0, int(getattr(tweet, "likeCount", 0) or 0))
    comments = max(0, int(getattr(tweet, "replyCount", 0) or 0))
    reposts = max(0, int(getattr(tweet, "retweetCount", 0) or 0))
    url = f"https://x.com/{username}/status/{native_id}"
    return NewsItem(
        id=f"x:{native_id}", section="community", source="X", url=url,
        title=f"@{username}：{' '.join(text.split())[:180]}", text=text,
        score=min(100, math.log1p(points + comments + reposts) * 10),
        meta={
            "author": username, "points": points, "comments": comments,
            "reposts": reposts, "discussion_url": url,
            "published_at": published.astimezone(UTC).isoformat(),
        },
    )


async def _fetch(cfg: dict, cookies: dict, since: datetime, until: datetime) -> list[NewsItem]:
    source = cfg["sources"]["x_twscrape"]
    items, seen = [], set()
    failures = []
    completed = 0
    try:
        async with asyncio.timeout(source.get("timeout_seconds", 120)):
            api = _create_api(Path(cfg["_root"]))
            await api.pool.add_account_cookies(
                "daily-digest", f"auth_token={cookies['auth_token']}; ct0={cookies['ct0']}",
            )
            # 单账号串行请求；不自动扩容账号或切换代理绕过限流。
            queries = [f"from:{handle}" for handle in source.get("accounts", [])]
            queries += source.get("queries", [])
            for query in queries:
                # 搜索按 UTC 日期粗筛，返回结果再按精确时间范围过滤。
                query = (
                    f"({query}) -filter:retweets since:{since:%Y-%m-%d} "
                    f"until:{until + timedelta(days=1):%Y-%m-%d}"
                )
                try:
                    async with asyncio.timeout(source.get("request_timeout_seconds", 15)):
                        async with aclosing(api.search(
                            query, limit=source.get("max_per_query", 5),
                        )) as tweets:
                            examined = 0
                            async for tweet in tweets:
                                examined += 1
                                item = _to_item(tweet, since, until)
                                if item and item.id not in seen:
                                    seen.add(item.id)
                                    items.append(item)
                                if (examined >= source.get("max_per_query", 5)
                                        or len(items) >= source.get("max_fetch", 40)):
                                    break
                    completed += 1
                except TimeoutError:
                    failures.append("request_timeout")
                except Exception as exc:
                    # 只保留异常类型，不记录可能包含 Cookie 的异常正文。
                    failures.append(type(exc).__name__)
                    break
                if len(items) >= source.get("max_fetch", 40):
                    break
                await asyncio.sleep(source.get("request_delay_seconds", 2))
    except TimeoutError:
        failures.append("total_timeout")
    except ImportError:
        failures.append("dependency_missing")
    except Exception as exc:
        failures.append(type(exc).__name__)
    state = ("partial" if items else "failed") if failures else ("ok" if items else "empty")
    _status(cfg, state, len(items), completed_queries=completed, errors=failures)
    return items


def collect(cfg: dict, report_date) -> list[NewsItem]:
    source = cfg.get("sources", {}).get("x_twscrape", {})
    if not source.get("enabled", False):
        _status(cfg, "disabled")
        return []
    until = datetime.now(UTC)
    if report_date != until.astimezone(ZoneInfo(cfg.get("timezone", "Asia/Shanghai"))).date():
        _status(cfg, "historical_unsupported")
        return []
    try:
        cookies = load_cookies(Path(cfg["_root"]))
    except (OSError, ValueError):
        _status(cfg, "invalid_credentials")
        return []
    if cookies is None:
        _status(cfg, "missing_credentials")
        log.warning("X 尚未配置登录会话：请运行 python -m src.x_setup")
        return []
    since = until - timedelta(hours=source.get("lookback_hours", 48))
    return asyncio.run(_fetch(cfg, cookies, since, until))
