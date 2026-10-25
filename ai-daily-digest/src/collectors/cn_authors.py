"""通过隔离浏览器工作进程订阅少量中文作者。"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ..models import NewsItem
from ..utils import report_end_utc

log = logging.getLogger(__name__)
STATES = {
    "ok",
    "empty",
    "empty_recent",
    "login_required",
    "failed",
    "timeout",
    "missing_runtime",
    "invalid_response",
    "article_unavailable",
    "empty_article",
}


def _child_env() -> dict[str, str]:
    # 只传递运行浏览器所需变量，以及本采集器专用的站点会话。
    allowed = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "SSL_CERT_FILE",
        "LD_LIBRARY_PATH",
        "CN_BROWSER_STATE",
        "USERNAME",
        "USER",
        "LOGNAME",
        "COMSPEC",
        "SYSTEMDRIVE",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMW6432",
        "PROGRAMDATA",
        "ALLUSERSPROFILE",
        "PATHEXT",
        "HOMEDRIVE",
        "HOMEPATH",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
    }
    return {
        **{k: v for k, v in os.environ.items() if k.upper() in allowed},
        "PYTHONIOENCODING": "utf-8",
        "NO_COLOR": "1",
    }


def _run_worker(cfg: dict, platform: str, request: dict) -> dict:
    root = Path(cfg["_root"])
    environment = root / ".external-skills/cn-pilot-venv"
    executable = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not executable.is_file():
        return {"status": "missing_runtime"}
    try:
        result = subprocess.run(
            [str(executable), "-m", "src.cn_pilot", "feed", "--platform", platform],
            input=json.dumps(request, ensure_ascii=False),
            cwd=root,
            env=_child_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=cfg.get("sources", {}).get("cn_authors", {}).get("timeout_seconds", 100),
            check=False,
        )
        payload = json.loads(result.stdout)
        return payload if isinstance(payload, dict) else {"status": "invalid_response"}
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    except (OSError, ValueError):
        return {"status": "invalid_response"}


def _diagnostic(payload: dict) -> dict:
    state = payload.get("status")
    status = {"status": state if state in STATES else "failed"}
    for key in ("received_items", "valid_items", "body_chars"):
        value = payload.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 1000000:
            status[key] = value
    # Never copy arbitrary upstream strings (including exception messages) to run-status.
    stamp = payload.get("latest_published_at", "")
    if isinstance(stamp, str):
        with contextlib.suppress(ValueError):
            status["latest_published_at"] = datetime.fromisoformat(stamp).isoformat()
    return status


def _recent_rows(payload: dict, platform: str, cfg: dict, today: date) -> list[dict]:
    now = datetime.now(UTC)
    end = min(now, report_end_utc(today, cfg.get("timezone", "Asia/Shanghai")))
    start = end - timedelta(hours=cfg["sources"]["cn_authors"].get("lookback_hours", 48))
    patterns = {
        "weibo": r"https://m\.weibo\.cn/detail/\d+",
        "zhihu": r"https://(?:www\.zhihu\.com/question/\d+/answer/\d+|zhuanlan\.zhihu\.com/p/\d+)",
    }
    rows = payload.get("items", [])
    result = []
    if not isinstance(rows, list):
        return result
    for raw in rows[:20]:
        if not isinstance(raw, dict) or not re.fullmatch(
            patterns[platform], str(raw.get("url", ""))
        ):
            continue
        try:
            stamp = datetime.fromisoformat(raw.get("published_at", ""))
            if stamp.tzinfo is None or not start <= stamp <= end:
                continue
        except (ValueError, TypeError):
            continue
        if not isinstance(raw.get("text"), str) or not isinstance(raw.get("title"), str):
            continue
        result.append(
            {
                "title": raw["title"][:240],
                "text": raw["text"][:20000],
                "url": raw["url"],
                "published_at": stamp.isoformat(),
            }
        )
    return result


def fetch_toutiao_article(url: str, cfg: dict) -> str:
    """头条候选由原搜索通道发现，本入口只补读正文，不将测试旧文章送入早报。"""
    settings = cfg.get("sources", {}).get("cn_authors", {})
    if not settings.get("enabled", False) or not settings.get("toutiao_content", True):
        return ""
    if not re.fullmatch(r"https://www\.toutiao\.com/article/\d+/?", url):
        return ""
    payload = _run_worker(cfg, "weibo", {"url": url})
    diagnostics = cfg.setdefault("_collector_status", {}).setdefault(
        "toutiao_content",
        {
            "attempted": 0,
            "succeeded": 0,
            "statuses": [],
        },
    )
    diagnostics["attempted"] += 1
    diagnostics["statuses"].append(_diagnostic(payload)["status"])
    rows = payload.get("items")
    if payload.get("status") == "ok" and isinstance(rows, list) and rows:
        row = rows[0]
        if isinstance(row, dict) and row.get("url") == url and isinstance(row.get("text"), str):
            diagnostics["succeeded"] += 1
            return row["text"][:20000]
    return ""


def collect(cfg: dict, today: date) -> list[NewsItem]:
    from .last30days_sources import _chinese_items

    source = cfg.get("sources", {}).get("cn_authors", {})
    statuses = cfg.setdefault("_collector_status", {})
    if not source.get("enabled", False):
        statuses["cn_authors"] = {"status": "disabled", "count": 0}
        return []
    if today != datetime.now(ZoneInfo(cfg.get("timezone", "Asia/Shanghai"))).date():
        statuses["cn_authors"] = {"status": "historical_unsupported", "count": 0}
        return []
    items, authors = [], []
    for author in source.get("authors", []):
        platform = author["platform"]
        payload = _run_worker(cfg, platform, {"author": author})
        status = {"platform": platform, "author": author["name"], **_diagnostic(payload)}
        recent = _recent_rows(payload, platform, cfg, today)
        for row in recent:
            row["author"] = author["name"]
        filtering = {}
        accepted = _chinese_items(
            {platform: recent},
            {platform},
            report_date=today,
            practice_only=source.get("practice_only", True),
            diagnostics=filtering,
        )
        accepted = accepted[: source.get("max_per_author", 5)]
        for item in accepted:
            item.meta["collection_method"] = "author_feed"
        status.update(
            {
                "recent_items": len(recent),
                "accepted": len(accepted),
                "filtered": filtering.get(platform, {}).get("filtered", {}),
            }
        )
        if status["status"] in {"ok", "empty_recent"}:
            status["status"] = "ok" if recent else "empty_recent"
        authors.append(status)
        items.extend(accepted)
    states = {value["status"] for value in authors}
    bad = bool(states - {"ok", "empty", "empty_recent"})
    statuses["cn_authors"] = {
        "status": "partial" if bad and items else "failed" if bad else "ok" if items else "empty",
        "count": len(items),
        "authors": authors,
    }
    log.info("中文作者订阅诊断：%s", statuses["cn_authors"])
    return items
