"""加载并校验 config.yaml 与 .env。"""
import os
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _positive_int(value, path: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{path} 必须是正整数")
    if maximum is not None and value > maximum:
        raise ValueError(f"{path} 不能大于 {maximum}")
    return value


def _http_url(value, path: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{path} 必须是 URL 字符串")
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{path} 只允许有效的 http/https URL")
    return value.strip()


def validate_config(cfg: dict) -> None:
    """尽早拒绝会导致静默丢数据或危险输出路径的配置。"""
    if not isinstance(cfg, dict):
        raise ValueError("config.yaml 顶层必须是对象")

    try:
        ZoneInfo(cfg.get("timezone", "Asia/Shanghai"))
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"timezone 无效: {cfg.get('timezone')}") from exc

    output_dir = cfg.get("output_dir", "output")
    output_path = Path(output_dir)
    if not isinstance(output_dir, str) or output_path.is_absolute() or ".." in output_path.parts:
        raise ValueError("output_dir 必须是项目目录内的相对路径")

    _positive_int(
        cfg.get("initial_visible_items", 4),
        "initial_visible_items",
        maximum=20,
    )

    dedup = cfg.get("dedup", {})
    if not isinstance(dedup, dict):
        raise ValueError("dedup 必须是对象")
    if not isinstance(dedup.get("enabled", True), bool):
        raise ValueError("dedup.enabled 必须是布尔值")
    _positive_int(dedup.get("window_days", 7), "dedup.window_days", maximum=90)

    sections = cfg.get("sections")
    if not isinstance(sections, dict) or not sections:
        raise ValueError("sections 必须是非空对象")
    for key, section in sections.items():
        if not isinstance(section, dict):
            raise ValueError(f"sections.{key} 必须是对象")
        if not isinstance(section.get("enabled", True), bool):
            raise ValueError(f"sections.{key}.enabled 必须是布尔值")
        if not isinstance(section.get("title"), str) or not section["title"].strip():
            raise ValueError(f"sections.{key}.title 不能为空")
        _positive_int(section.get("limit", 8), f"sections.{key}.limit", maximum=100)
        if "max_per_source" in section:
            _positive_int(
                section["max_per_source"],
                f"sections.{key}.max_per_source",
                maximum=100,
            )

    llm = cfg.get("llm")
    if not isinstance(llm, dict):
        raise ValueError("llm 必须是对象")
    _http_url(llm.get("base_url"), "llm.base_url")
    if not isinstance(llm.get("model"), str) or not llm["model"].strip():
        raise ValueError("llm.model 不能为空")
    _positive_int(llm.get("batch_size", 12), "llm.batch_size", maximum=50)
    _positive_int(llm.get("timeout_seconds", 60), "llm.timeout_seconds", maximum=600)
    _positive_int(llm.get("max_output_tokens", 4096), "llm.max_output_tokens", maximum=32768)
    _positive_int(
        llm.get("max_input_chars_per_item", 2400),
        "llm.max_input_chars_per_item",
        maximum=20000,
    )
    _positive_int(
        llm.get("cache_retention_days", 30),
        "llm.cache_retention_days",
        maximum=365,
    )
    retries = llm.get("max_retries", 2)
    if isinstance(retries, bool) or not isinstance(retries, int) or not 0 <= retries <= 10:
        raise ValueError("llm.max_retries 必须是 0~10 的整数")

    sources = cfg.get("sources")
    if not isinstance(sources, dict):
        raise ValueError("sources 必须是对象")
    rss = sources.get("rss", {})
    feeds = rss.get("feeds", []) if isinstance(rss, dict) else []
    if not isinstance(feeds, list):
        raise ValueError("sources.rss.feeds 必须是数组")
    for index, feed in enumerate(feeds):
        path = f"sources.rss.feeds[{index}]"
        if not isinstance(feed, dict) or not str(feed.get("name", "")).strip():
            raise ValueError(f"{path}.name 不能为空")
        _http_url(feed.get("url"), f"{path}.url")
        section = feed.get("section", "industry")
        if section not in sections:
            raise ValueError(f"{path}.section 引用了不存在的板块: {section}")

    hackernews = sources.get("hackernews", {})
    if isinstance(hackernews, dict):
        _positive_int(
            hackernews.get("content_fetch_limit", 8),
            "sources.hackernews.content_fetch_limit",
            maximum=50,
        )
        _positive_int(
            hackernews.get("min_content_chars", 160),
            "sources.hackernews.min_content_chars",
            maximum=5000,
        )
        if not isinstance(hackernews.get("require_content", True), bool):
            raise ValueError("sources.hackernews.require_content 必须是布尔值")

    last30days = sources.get("last30days")
    if last30days is None:
        last30days = {"enabled": False}
    if not isinstance(last30days, dict):
        raise ValueError("sources.last30days 必须是对象")
    if not isinstance(last30days.get("enabled", True), bool):
        raise ValueError("sources.last30days.enabled 必须是布尔值")
    allowed_sources = {
        "english": {"reddit", "x", "youtube", "bluesky"},
        "chinese": {
            "weibo", "xiaohongshu", "bilibili", "zhihu", "douyin",
            "wechat", "baidu", "toutiao",
        },
    } if last30days.get("enabled", True) else {}
    for language, allowed in allowed_sources.items():
        language_cfg = last30days.get(language, {})
        path = f"sources.last30days.{language}"
        if not isinstance(language_cfg, dict):
            raise ValueError(f"{path} 必须是对象")
        if not isinstance(language_cfg.get("enabled", True), bool):
            raise ValueError(f"{path}.enabled 必须是布尔值")
        topic = language_cfg.get("topic", "")
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError(f"{path}.topic 不能为空")
        selected_sources = language_cfg.get("sources", [])
        if not isinstance(selected_sources, list) or not selected_sources:
            raise ValueError(f"{path}.sources 必须是非空数组")
        unknown = {str(value).lower() for value in selected_sources} - allowed
        if unknown:
            raise ValueError(f"{path}.sources 包含不支持的来源: {', '.join(sorted(unknown))}")
        _positive_int(language_cfg.get("lookback_days", 2), f"{path}.lookback_days", maximum=30)
        _positive_int(
            language_cfg.get("timeout_seconds", 150),
            f"{path}.timeout_seconds",
            maximum=600,
        )
        if language == "english":
            _positive_int(language_cfg.get("max_results", 16), f"{path}.max_results", maximum=100)
            _positive_int(
                language_cfg.get("max_per_source", 8),
                f"{path}.max_per_source",
                maximum=50,
            )
        else:
            _positive_int(
                language_cfg.get("request_timeout_seconds", 20),
                f"{path}.request_timeout_seconds",
                maximum=120,
            )

    official_updates = sources.get("official_updates", {})
    if not isinstance(official_updates, dict):
        raise ValueError("sources.official_updates 必须是对象")
    if not isinstance(official_updates.get("enabled", True), bool):
        raise ValueError("sources.official_updates.enabled 必须是布尔值")
    _positive_int(
        official_updates.get("lookback_hours", 72),
        "sources.official_updates.lookback_hours",
        maximum=720,
    )
    _positive_int(
        official_updates.get("max_staleness_hours", 120),
        "sources.official_updates.max_staleness_hours",
        maximum=2160,
    )
    _positive_int(
        official_updates.get("content_fetch_limit", 4),
        "sources.official_updates.content_fetch_limit",
        maximum=20,
    )
    sites = official_updates.get("sites", [])
    if not isinstance(sites, list):
        raise ValueError("sources.official_updates.sites 必须是数组")
    for index, site in enumerate(sites):
        path = f"sources.official_updates.sites[{index}]"
        if not isinstance(site, dict) or not str(site.get("name", "")).strip():
            raise ValueError(f"{path}.name 不能为空")
        if site.get("parser") not in {"anthropic", "kimi", "qwen", "deepseek"}:
            raise ValueError(f"{path}.parser 不受支持")
        _http_url(site.get("url"), f"{path}.url")
        if not isinstance(site.get("fetch_content", False), bool):
            raise ValueError(f"{path}.fetch_content 必须是布尔值")
        _positive_int(site.get("max_items", 8), f"{path}.max_items", maximum=30)

    collection_workers = cfg.get("collection_workers", 5)
    _positive_int(collection_workers, "collection_workers", maximum=20)

    http = cfg.get("http", {})
    if not isinstance(http, dict):
        raise ValueError("http 必须是对象")
    _positive_int(
        http.get("connect_timeout_seconds", 5),
        "http.connect_timeout_seconds",
        maximum=120,
    )
    _positive_int(
        http.get("read_timeout_seconds", 30),
        "http.read_timeout_seconds",
        maximum=300,
    )
    http_retries = http.get("retries", 2)
    if (
        isinstance(http_retries, bool)
        or not isinstance(http_retries, int)
        or not 0 <= http_retries <= 5
    ):
        raise ValueError("http.retries 必须是 0~5 的整数")


def load_config() -> dict:
    load_dotenv(PROJECT_ROOT / ".env")
    with open(PROJECT_ROOT / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    validate_config(cfg)
    cfg["_root"] = str(PROJECT_ROOT)
    return cfg


def get_api_key() -> str:
    key = os.environ.get("LLM_API_KEY", "").strip()
    if not key or key.startswith("sk-xxxx"):
        raise RuntimeError(
            "未配置 API key：请复制 .env.example 为 .env 并填入 LLM_API_KEY"
        )
    return key
