"""Adapters for the optional last30days Chinese and English source engines."""

from __future__ import annotations

import hashlib
import html
import json
import logging
import math
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..models import NewsItem

log = logging.getLogger(__name__)

EN_SOURCE_LABELS = {
    "reddit": "Reddit",
    "x": "X",
    "twitter": "X",
    "youtube": "YouTube",
    "bluesky": "Bluesky",
}
CN_SOURCE_LABELS = {
    "weibo": "微博",
    "xiaohongshu": "小红书",
    "bilibili": "B站",
    "zhihu": "知乎",
    "douyin": "抖音",
    "wechat": "微信",
    "baidu": "百度热搜",
    "toutiao": "今日头条",
}

# 明确的商业落地页可以直接过滤；普通内容只有同时出现促销和交易/课程信号时
# 才会被判定为广告，避免误伤“模型限时开放”等正常行业动态。
_CN_COMMERCIAL_URL_PATTERNS = (
    re.compile(r"(?:^|\.)bilibili\.com/cheese/(?:play|play/|$)", re.IGNORECASE),
)
_CN_PROMOTION_PATTERN = re.compile(
    r"限时\s*\d*\s*折|\d+(?:\.\d+)?\s*折(?:起|优惠)?|限时优惠|"
    r"特价|秒杀|领券|优惠券|早鸟价|拼团|低至|立减|免费领取"
)
_CN_TRANSACTION_PATTERN = re.compile(
    r"立即(?:购买|报名|抢购|下单)|点击(?:购买|报名|领取)|"
    r"报名(?:入口|通道|截止)|付费(?:课|课程|专栏)|"
    r"训练营|实战课|系统课|精品课|课程购买|购课"
)


def _is_chinese_community_ad(title: str, summary: str, url: str) -> bool:
    """识别中文社区中的明显课程广告和促销内容。"""
    normalized_url = url.lower().split("?", 1)[0].rstrip("/") + "/"
    if any(pattern.search(normalized_url) for pattern in _CN_COMMERCIAL_URL_PATTERNS):
        return True

    content = f"{title} {summary}"
    return bool(
        _CN_PROMOTION_PATTERN.search(content)
        and _CN_TRANSACTION_PATTERN.search(content)
    )


def _script_path(cfg: dict, language: str) -> Path | None:
    """Find either a locally installed skill or the workflow-pinned checkout."""
    root = Path(cfg["_root"])
    if language == "en":
        env_name, local_name = "LAST30DAYS_EN_SKILL_DIR", "last30days-en"
    else:
        env_name, local_name = "LAST30DAYS_CN_SKILL_DIR", "last30days-cn"

    candidates = []
    configured = os.environ.get(env_name, "").strip()
    if configured:
        candidates.append(Path(configured))
    candidates.extend([
        root / ".external-skills" / local_name / "skills" / "last30days",
        Path.home() / ".codex" / "skills" / local_name,
    ])
    for candidate in candidates:
        script = (
            candidate
            if candidate.name == "last30days.py"
            else candidate / "scripts" / "last30days.py"
        )
        if script.is_file():
            return script.resolve()
    return None


def _child_env() -> dict[str, str]:
    """Keep X credentials available without sharing the digest model key."""
    env = os.environ.copy()
    env.pop("LLM_API_KEY", None)
    executable_dir = str(Path(sys.executable).resolve().parent)
    env["PATH"] = os.pathsep.join(filter(None, [executable_dir, env.get("PATH", "")]))
    env.update({
        "FROM_BROWSER": "off",
        "NO_COLOR": "1",
        "PYTHONIOENCODING": "utf-8",
        "LAST30DAYS_NATIVE_SEARCH": "1",
    })
    return env


def _decode_json(stdout: str) -> dict:
    """Accept clean JSON and tolerate a short diagnostic prefix on stdout."""
    try:
        value = json.loads(stdout)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        start = stdout.find("{")
        if start < 0:
            return {}
        try:
            value, _ = json.JSONDecoder().raw_decode(stdout[start:])
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}


def _run_engine(script: Path, args: list[str], timeout: int) -> dict:
    command = [sys.executable, str(script), *args]
    try:
        result = subprocess.run(
            command,
            cwd=script.parent.parent,
            env=_child_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        log.warning("%s 采集超时（%ds），本次跳过", script.parent.parent.name, timeout)
        return {}
    except OSError as exc:
        log.warning("无法启动 %s: %s", script, exc)
        return {}

    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-1200:]
        log.warning("%s 返回 %d：%s", script.parent.parent.name, result.returncode, detail)
        return {}
    payload = _decode_json(result.stdout)
    if not payload:
        log.warning("%s 未返回有效 JSON", script.parent.parent.name)
    return payload


def _numeric(value) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    if isinstance(value, str):
        try:
            return max(0.0, float(value.replace(",", "").strip()))
        except ValueError:
            return 0.0
    return 0.0


def _engagement(item: dict) -> tuple[float, int, int]:
    engagement = item.get("engagement")
    values = engagement if isinstance(engagement, dict) else {}
    points = max(
        [_numeric(item.get("score"))]
        + [_numeric(value) for key, value in values.items() if key.lower() in {
            "score", "likes", "like_count", "upvotes", "points", "reposts", "shares",
        }]
    )
    comments = max(
        [_numeric(item.get("comments"))]
        + [_numeric(value) for key, value in values.items() if any(
            token in key.lower() for token in ("comment", "repl")
        )]
    )
    total = sum(_numeric(value) for value in values.values())
    return total, int(points), int(comments)


def _rank_score(item: dict) -> tuple[float, int, int]:
    engagement, points, comments = _engagement(item)
    relevance = _numeric(item.get("relevance_score"))
    if relevance <= 1:
        relevance *= 100
    return relevance + min(40.0, math.log1p(engagement) * 5), points, comments


def _stable_id(prefix: str, item: dict, url: str) -> str:
    native = item.get("candidate_id") or item.get("id")
    if native:
        return f"{prefix}:{native}"
    digest = hashlib.sha256(url.encode("utf-8", errors="ignore")).hexdigest()[:20]
    return f"{prefix}:{digest}"


def _first_text(item: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(html.unescape(value).split())
    return ""


def _english_items(payload: dict, allowed_sources: set[str]) -> list[NewsItem]:
    items = []
    for raw in payload.get("results", []):
        if not isinstance(raw, dict):
            continue
        source_key = str(raw.get("source", "")).lower().strip()
        source_key = "x" if source_key == "twitter" else source_key
        if source_key not in allowed_sources:
            continue
        url = _first_text(raw, ("url", "discussion_url"))
        title = _first_text(raw, ("title", "text", "summary"))
        if not url or not title:
            continue
        summary = _first_text(raw, ("summary", "text", "description")) or title
        score, points, comments = _rank_score(raw)
        items.append(NewsItem(
            id=_stable_id(f"last30days-{source_key}", raw, url),
            section="community",
            title=title[:240],
            url=url,
            source=EN_SOURCE_LABELS.get(source_key, source_key.title()),
            text=summary,
            score=score,
            meta={
                "points": points,
                "comments": comments,
                "discussion_url": url,
                "published_at": raw.get("published_at", ""),
            },
        ))
    return items


def _platform_rows(payload: dict, platform: str) -> list[dict]:
    value = payload.get(platform, [])
    if isinstance(value, dict):
        value = value.get("results") or value.get("items") or []
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _chinese_items(payload: dict, allowed_sources: set[str]) -> list[NewsItem]:
    items = []
    for platform in allowed_sources:
        for raw in _platform_rows(payload, platform):
            url = _first_text(raw, ("url", "link", "source_url"))
            title = _first_text(raw, ("title", "text", "name", "summary"))
            if not url or not title:
                continue
            summary = _first_text(
                raw, ("summary", "description", "desc", "excerpt", "snippet", "text")
            ) or title
            if _is_chinese_community_ad(title, summary, url):
                log.info("过滤中文社区广告：[%s] %s", platform, title[:100])
                continue
            score, points, comments = _rank_score(raw)
            items.append(NewsItem(
                id=_stable_id(f"last30days-cn-{platform}", raw, url),
                section="community_cn",
                title=title[:240],
                url=url,
                source=CN_SOURCE_LABELS.get(platform, platform),
                text=summary,
                score=score,
                meta={
                    "points": points,
                    "comments": comments,
                    "discussion_url": url,
                    "published_at": raw.get("published_at") or raw.get("date") or "",
                },
            ))
    return items


def _collect_english(cfg: dict, report_date, source_cfg: dict) -> list[NewsItem]:
    script = _script_path(cfg, "en")
    if script is None:
        log.warning("未找到 last30days 英文 skill，跳过英文扩展社区来源")
        return []
    sources = {str(value).lower() for value in source_cfg.get(
        "sources", ["reddit", "x", "youtube", "bluesky"]
    )}
    topic = source_cfg.get("topic", "LLM OR GPT OR Claude OR Gemini OR DeepSeek")
    plan = {
        "intent": "breaking_news",
        "freshness_mode": "strict_recent",
        "cluster_mode": "story",
        "subqueries": [{
            "label": "ai-community",
            "search_query": topic,
            "ranking_query": "What AI and LLM developments are gaining meaningful discussion?",
            "sources": sorted(sources),
            "weight": 1.0,
        }],
    }
    payload = _run_engine(script, [
        topic,
        "--emit", "json",
        "--json-profile", "agent",
        "--quick",
        "--days", str(source_cfg.get("lookback_days", 2)),
        "--as-of", report_date.isoformat(),
        "--search", ",".join(sorted(sources)),
        "--max-results", str(source_cfg.get("max_results", 16)),
        "--max-per-source", str(source_cfg.get("max_per_source", 8)),
        "--no-browser-cookies",
        "--plan", json.dumps(plan, ensure_ascii=False, separators=(",", ":")),
    ], source_cfg.get("timeout_seconds", 150))
    status = payload.get("source_status", {})
    if isinstance(status, dict):
        for source in sorted(sources):
            source_status = status.get(source)
            if source_status:
                log.info(
                    "%s 来源状态: %s", EN_SOURCE_LABELS.get(source, source), source_status,
                )
    return _english_items(payload, sources)


def _collect_chinese(cfg: dict, report_date, source_cfg: dict) -> list[NewsItem]:
    script = _script_path(cfg, "cn")
    if script is None:
        log.warning("未找到 last30days 中文 skill，跳过中文社区扩展来源")
        return []
    sources = {str(value).lower() for value in source_cfg.get(
        "sources", ["weibo", "bilibili", "zhihu", "baidu", "toutiao"]
    )}
    topic = source_cfg.get("topic", "大模型 人工智能 AI")
    payload = _run_engine(script, [
        topic,
        "--emit", "json",
        "--quick",
        "--days", str(source_cfg.get("lookback_days", 2)),
        "--as-of", report_date.isoformat(),
        "--timeout", str(source_cfg.get("request_timeout_seconds", 20)),
        "--search", ",".join(sorted(sources)),
        "--no-cache",
    ], source_cfg.get("timeout_seconds", 150))
    return _chinese_items(payload, sources)


def collect(cfg: dict, report_date) -> list[NewsItem]:
    source_cfg = cfg.get("sources", {}).get("last30days", {})
    if not source_cfg.get("enabled", True):
        return []

    jobs = {}
    english_cfg = source_cfg.get("english", {})
    chinese_cfg = source_cfg.get("chinese", {})
    enabled_sections = {
        key for key, value in cfg.get("sections", {}).items() if value.get("enabled", True)
    }
    if english_cfg.get("enabled", True) and "community" in enabled_sections:
        jobs["english"] = (_collect_english, english_cfg)
    if chinese_cfg.get("enabled", True) and "community_cn" in enabled_sections:
        jobs["chinese"] = (_collect_chinese, chinese_cfg)

    results = {}
    with ThreadPoolExecutor(max_workers=max(1, len(jobs)), thread_name_prefix="last30days") as pool:
        futures = {
            pool.submit(fn, cfg, report_date, language_cfg): name
            for name, (fn, language_cfg) in jobs.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception:
                log.exception("last30days %s 采集异常，跳过", name)
                results[name] = []
    return [item for name in jobs for item in results.get(name, [])]
