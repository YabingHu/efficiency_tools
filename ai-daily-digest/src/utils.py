"""跨采集器复用的时间与 URL 工具。"""
from datetime import UTC, date, datetime, time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def report_end_utc(today: date, timezone_name: str) -> datetime:
    """返回报告日期在配置时区中的日末，转换为 UTC。"""
    local_end = datetime.combine(today, time.max, tzinfo=ZoneInfo(timezone_name))
    return local_end.astimezone(UTC)


def safe_http_url(url: str) -> str | None:
    """仅接受具有主机名的 HTTP(S) 链接。"""
    if not isinstance(url, str):
        return None
    value = url.strip()
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return value


def canonical_url(url: str) -> str:
    """移除片段和常见追踪参数，用于跨来源去重。"""
    parsed = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMS
    ]
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, urlencode(query), ""))
