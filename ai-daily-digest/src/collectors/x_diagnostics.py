"""twscrape 0.20.1 请求日志的白名单适配；原始消息绝不转发或保存。"""
import os
import sys
from contextlib import contextmanager
from urllib.parse import urlsplit


def safe_exception_details(error: BaseException) -> dict:
    """从异常对象提取固定类别和数值，不解析或输出异常正文。"""
    known_types = {
        "HttpStatusError", "HTTPStatusError", "NetworkError", "ConnectError",
        "XClIdAccountError", "XClIdParseError", "TypeError", "ValueError", "KeyError",
        "IndexError", "AttributeError", "RuntimeError", "AssertionError", "ImportError",
        "ModuleNotFoundError", "JSONDecodeError", "DecodingError", "UnicodeDecodeError",
        "ReadTimeout", "ConnectTimeout", "RemoteProtocolError", "LocalProtocolError",
    }
    name = type(error).__name__
    detail = {"exception_type": name if name in known_types else "OtherError"}
    # 只输出已知调用位置，不输出 traceback 的文件路径、源码行或局部变量。
    locations = {
        ("twscrape.xclid", "get_tw_page_text"): "web_page_fetch",
        ("twscrape.xclid", "_find_indices_url"): "signing_script_fetch",
        ("twscrape.xclid", "parse_anim_idx"): "signing_script_parse",
        ("twscrape.xclid", "parse_vk_bytes"): "verification_key_parse",
        ("twscrape.xclid", "parse_anim_arr"): "animation_parse",
        ("twscrape.xclid", "load_keys"): "signing_key_build",
        ("twscrape.xclid", "create"): "web_session_bootstrap",
        ("twscrape.queue_client", "_check_rep"): "search_response_check",
    }
    tb = error.__traceback__
    while tb is not None:
        key = (tb.tb_frame.f_globals.get("__name__"), tb.tb_frame.f_code.co_name)
        if key in locations:
            detail["stage"] = locations[key]
        tb = tb.tb_next
    if name in {"HttpStatusError", "HTTPStatusError"}:
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
        if type(status) is int and 100 <= status <= 599:
            detail["http_status"] = status
        # 查询参数、URL 路径和非白名单域名均不写入日志。
        url = urlsplit(str(getattr(response, "url", "")))
        if url.hostname in {"x.com", "twitter.com", "abs.twimg.com"}:
            detail["endpoint"] = (
                "web_assets" if url.hostname == "abs.twimg.com"
                else "graphql" if url.path.startswith("/i/api/graphql/") else "web_page"
            )
    return detail


class SafeRequestLog:
    def __init__(self):
        self.events: list[str] = []
        self.errors: list[dict] = []

    def _record(self, message, *args, **kwargs):
        if not isinstance(message, str):
            return
        prefixes = {
            "XClIdAccountError: Logged-out X web app": "logged_out_web_page",
            "XClIdAccountError:": "web_session_rejected",
            "XClIdParseError:": "web_signing_parse_failed",
            "Rate limited:": "rate_limit_response",
            "NetworkError;": "network_retries_exhausted",
            "ConnectError;": "connection_retries_exhausted",
            "Blocked by Cloudflare:": "cloudflare_blocked_response",
            "Blocked by HTML:": "html_error_response",
            "Unhandled API response code:": "unexpected_http_status",
            "Unknown error. Account timeouted for 15 minutes.": "unexpected_request_error",
            "Session expired or banned:": "session_rejected",
            "Ban detected:": "account_restricted_response",
            "[DEV] Update required:": "api_features_outdated",
        }
        for prefix, event in prefixes.items():
            if message.startswith(prefix):
                if event not in self.events:
                    self.events.append(event)
                error = sys.exception()
                if error is not None:
                    try:
                        detail = safe_exception_details(error)
                    except Exception:
                        detail = {"exception_type": "diagnostic_unavailable"}
                    if detail not in self.errors and len(self.errors) < 8:
                        self.errors.append(detail)
                break

    debug = trace = info = warning = error = critical = _record


@contextmanager
def capture_request_events():
    """当前采集器串行使用；临时替换请求模块的 logger，退出时恢复。

    不启用 loguru 原始日志或 debug 响应文件。局部适配固定版本的依赖，
    未识别消息一律丢弃，不保存账号、URL、响应正文或异常文本。
    """
    recorder = SafeRequestLog()
    os.environ["TWS_TELEMETRY"] = "0"
    try:
        from twscrape import queue_client
    except ImportError:
        # 由采集器正常报告 dependency_missing。
        yield recorder
        return
    previous = queue_client.logger
    queue_client.logger = recorder
    try:
        yield recorder
    finally:
        queue_client.logger = previous
