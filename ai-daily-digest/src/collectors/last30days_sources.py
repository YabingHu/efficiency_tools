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
from datetime import date, timedelta
from pathlib import Path

from ..content_extractor import extract_text_from_url
from ..editorial import has_community_ai_context
from ..models import NewsItem
from ..utils import canonical_url, safe_http_url

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
    "baidu": "百度搜索",
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
_CN_PRACTICE_PATTERN = re.compile(
    r"实测|评测|对比|部署|踩坑|复盘|排查|故障|调优|本地运行|实践|benchmark", re.I,
)
_CN_EVIDENCE_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*(?:GB|GiB|MB|ms|秒|分钟|小时|%|tokens?|t/s)|"
    r"配置|命令|日志|报错|修复|复现|测试集|数据集|显存|吞吐|延迟|"
    r"Docker|vLLM|Ollama|SGLang|ComfyUI|GPU|CUDA|pip install", re.I,
)


def _is_chinese_practice(title: str, text: str) -> bool:
    """实践选题须有实测/排障等信号，并在原始素材中提供具体依据。"""
    return bool(
        _CN_PRACTICE_PATTERN.search(f"{title} {text}")
        and _CN_EVIDENCE_PATTERN.search(text)
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
    env.pop("X_AUTH_TOKEN", None)
    env.pop("X_CT0", None)
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


def _platform_errors(stderr: str) -> dict[str, list[str]]:
    """上游部分模块只在 stderr 报错；仅保留已知平台的固定诊断类别。"""
    errors = {}
    for source, label in CN_SOURCE_LABELS.items():
        categories = set()
        for line in stderr.splitlines():
            if not line.startswith(f"[{label}]") and not (
                source == "baidu" and line.startswith("[百度]")
            ):
                continue
            if not re.search(r"失败|安全验证|验证码|timed out|TimeoutError|HTTP Error", line):
                continue
            known = re.search(
                r"\b(login_required|non_json_response|empty_data|invalid_response|"
                r"search_results_unavailable|network_error)\b", line,
            )
            if known:
                categories.add(known[1])
                continue
            code = re.search(r"(?:\b|http_)([45]\d\d)\b", line)
            categories.add(
                f"http_{code[1]}" if code else
                "timeout" if re.search(r"超时|timed out|TimeoutError", line) else
                "request_failed"
            )
        if categories:
            errors[source] = sorted(categories)
    return errors


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
        return {"_engine_status": "timeout"}
    except OSError as exc:
        log.warning("无法启动 %s: %s", script, exc)
        return {"_engine_status": "start_failed"}

    if result.returncode:
        log.warning("%s 返回 %d", script.parent.parent.name, result.returncode)
        timed_out = "[超时] 全局超时" in result.stderr
        return {"_engine_status": "timeout" if timed_out else "failed"}
    payload = _decode_json(result.stdout)
    if not payload:
        log.warning("%s 未返回有效 JSON", script.parent.parent.name)
    return {
        **payload, "_engine_status": "ok" if payload else "invalid_json",
        "_engine_platform_errors": _platform_errors(result.stderr),
    }


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
    relevance = _numeric(item.get("relevance_score", item.get("relevance")))
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


def _chinese_material(raw: dict) -> tuple[str, str]:
    title = _first_text(raw, ("title", "name"))
    body = _first_text(raw, (
        "summary", "description", "abstract", "desc", "excerpt", "snippet", "text",
    ))
    if not title:
        title = body[:60] + ("…" if len(body) > 60 else "")
    return title, body or title


def _supplement_chinese_content(
    payloads: list[dict], sources: set[str], cfg: dict, *, report_date: date | None = None,
) -> dict:
    """为有实践选题但素材薄弱的候选补读公开原文，同一链接只请求一次。"""
    candidates = {}
    source_cfg = cfg["sources"]["last30days"]["chinese"]
    for payload in payloads:
        for source in sorted(sources):
            for raw in _platform_rows(payload, source):
                title, text = _chinese_material(raw)
                url = _first_text(raw, ("url", "link", "source_url"))
                published = raw.get("published_at") or raw.get("date")
                if report_date and isinstance(published, str):
                    try:
                        published_date = date.fromisoformat(published[:10])
                    except ValueError:
                        published_date = None
                    if published_date and not (
                        report_date - timedelta(days=source_cfg.get("lookback_days", 2))
                        <= published_date <= report_date
                    ):
                        continue
                if (
                    not safe_http_url(url) or not has_community_ai_context(title, text)
                    or not _CN_PRACTICE_PATTERN.search(f"{title} {text}")
                    or _is_chinese_community_ad(title, text, url)
                    or (
                        text != title and len(re.sub(r"\s+", "", text)) >= 60
                        and _is_chinese_practice(title, text)
                    )
                ):
                    continue
                candidates.setdefault(canonical_url(url), []).append(raw)
    selected = list(candidates.items())[:source_cfg.get("content_fetch_limit", 4)]
    # 使用独立超时配置，避免改变其他采集器共享的 HTTP 参数。
    fetch_cfg = {**cfg, "http": {
        **cfg.get("http", {}), "connect_timeout_seconds": 5, "read_timeout_seconds": 10,
    }}
    succeeded = 0
    if selected:
        def fetch(entry):
            if "toutiao" in sources and "toutiao.com/article/" in entry[0]:
                from .cn_authors import fetch_toutiao_article

                body = fetch_toutiao_article(entry[0], cfg)
                if body:
                    return body
            return extract_text_from_url(entry[0], fetch_cfg, min_chars=60)

        with ThreadPoolExecutor(max_workers=min(3, len(selected))) as pool:
            bodies = pool.map(fetch, selected)
            for (_, rows), body in zip(selected, bodies, strict=True):
                if not body:
                    continue
                succeeded += 1
                for raw in rows:
                    _, original = _chinese_material(raw)
                    raw["summary"] = original + "\n" + body[:5000]
    return {"attempted": len(selected), "succeeded": succeeded}


def _chinese_items(
    payload: dict, allowed_sources: set[str], *, report_date: date | None = None,
    lookback_days: int = 2, practice_only: bool = False,
    diagnostics: dict | None = None,
) -> list[NewsItem]:
    items = []
    for platform in sorted(allowed_sources):
        stats = {"received": 0, "accepted": 0, "filtered": {}}
        if diagnostics is not None:
            diagnostics[platform] = stats
        for raw in _platform_rows(payload, platform):
            stats["received"] += 1
            url = _first_text(raw, ("url", "link", "source_url"))
            title, summary = _chinese_material(raw)
            if not safe_http_url(url) or not title:
                stats["filtered"]["invalid_fields"] = stats["filtered"].get("invalid_fields", 0) + 1
                continue
            if _is_chinese_community_ad(title, summary, url):
                stats["filtered"]["advertisement"] = stats["filtered"].get("advertisement", 0) + 1
                log.info("过滤中文社区广告：[%s] %s", platform, title[:100])
                continue
            if not has_community_ai_context(title, summary):
                stats["filtered"]["irrelevant"] = stats["filtered"].get("irrelevant", 0) + 1
                log.info("过滤中文社区无关内容：[%s] %s", platform, title[:100])
                continue
            published = raw.get("published_at") or raw.get("date") or ""
            if report_date and isinstance(published, str):
                try:
                    published_date = date.fromisoformat(published[:10])
                except ValueError:
                    published_date = None
                if published_date and not (
                    report_date - timedelta(days=lookback_days) <= published_date <= report_date
                ):
                    log.info("过滤中文社区过期内容：[%s] %s", platform, title[:100])
                    stats["filtered"]["out_of_range"] = stats["filtered"].get("out_of_range", 0) + 1
                    continue
            if practice_only and not _is_chinese_practice(title, summary):
                stats["filtered"]["not_practice"] = stats["filtered"].get("not_practice", 0) + 1
                continue
            score, points, comments = _rank_score(raw)
            items.append(NewsItem(
                # 上游的 WB1/ZH1 等 ID 会在每次查询重置；以链接生成跨查询稳定 ID。
                id=_stable_id(f"last30days-cn-{platform}", {}, canonical_url(url)),
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
                    "published_at": published,
                    "author": _first_text(raw, (
                        "author", "author_handle", "channel_name", "source_name",
                    )),
                },
            ))
            stats["accepted"] += 1
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
    statuses = cfg.setdefault("_collector_status", {})
    sources = {str(value).lower() for value in source_cfg.get(
        "sources", ["weibo", "bilibili", "zhihu", "baidu", "toutiao"]
    )}
    script = _script_path(cfg, "cn")
    if script is None:
        log.warning("未找到 last30days 中文 skill，跳过中文社区扩展来源")
        statuses["last30days_chinese"] = {
            "status": "missing_engine", "count": 0,
            "platforms": {source: {"status": "not_attempted"} for source in sorted(sources)},
        }
        return []
    queries = source_cfg.get("queries") or [source_cfg.get("topic", "大模型 开发实践")]
    timeout = source_cfg.get("timeout_seconds", 150)

    def search(query):
        runner = Path(__file__).resolve().parents[1] / "cn_engine_runner.py"
        return _run_engine(runner, [
            str(script), query, "--emit", "json", "--quick",
            "--days", str(source_cfg.get("lookback_days", 2)),
            "--as-of", report_date.isoformat(),
            "--timeout", str(timeout),  # 上游参数是整个引擎的全局超时。
            "--search", ",".join(sorted(sources)), "--no-cache",
        ], timeout + 10)  # 留出引擎退出与结果输出的时间。

    with ThreadPoolExecutor(
        max_workers=min(3, len(queries)), thread_name_prefix="cn-query",
    ) as pool:
        payloads = list(pool.map(search, queries))
    content_fetch = _supplement_chinese_content(payloads, sources, cfg, report_date=report_date)
    platforms = {
        source: {"received": 0, "accepted": 0, "filtered": {}, "query_statuses": [], "errors": []}
        for source in sorted(sources)
    }
    candidates = []
    for payload in payloads:
        diagnostics = {}
        candidates.extend(_chinese_items(
            payload, sources, report_date=report_date,
            lookback_days=source_cfg.get("lookback_days", 2),
            practice_only=source_cfg.get("practice_only", True), diagnostics=diagnostics,
        ))
        engine_status = payload.get("_engine_status", "ok" if payload else "invalid_json")
        for source, stats in diagnostics.items():
            target = platforms[source]
            target["received"] += stats["received"]
            target["accepted"] += stats["accepted"]
            for reason, count in stats["filtered"].items():
                target["filtered"][reason] = target["filtered"].get(reason, 0) + count
            if engine_status != "ok":
                state = engine_status
            elif (
                payload.get(f"{source}_error")
                or payload.get("_engine_platform_errors", {}).get(source)
            ):
                state = "partial" if stats["received"] else "failed"
            elif source not in payload:
                state = "not_reported"
            else:
                state = "ok" if stats["received"] else "empty"
            target["query_statuses"].append(state)
            target["errors"] = sorted(set(
                target["errors"] + payload.get("_engine_platform_errors", {}).get(source, [])
            ))
    for stats in platforms.values():
        states = stats["query_statuses"]
        good = any(state in {"ok", "empty"} for state in states)
        bad = any(state not in {"ok", "empty"} for state in states)
        stats["status"] = (
            "partial" if bad and (good or stats["received"]) else
            "failed" if bad else "ok" if stats["received"] else "empty"
        )
    # 同一链接可能命中多个查询；保留素材更完整的版本，顺序与并发完成先后无关。
    unique = {}
    for item in candidates:
        key = canonical_url(item.url)
        if key not in unique or len(item.text) > len(unique[key].text):
            unique[key] = item
    items = list(unique.values())
    states = {stats["status"] for stats in platforms.values()}
    state = "partial" if states & {"failed", "partial"} else "ok" if items else "empty"
    if states == {"failed"}:
        state = "failed"
    statuses["last30days_chinese"] = {
        "status": state, "count": len(items), "query_count": len(queries),
        "duplicate_items": len(candidates) - len(items), "platforms": platforms,
        "content_fetch": content_fetch,
    }
    log.info("中文开发者实践：%s，%d 条候选，各平台诊断：%s", state, len(items), platforms)
    return items


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
