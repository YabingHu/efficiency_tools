"""twscrape 0.20.1 请求日志的白名单适配；原始消息绝不转发或保存。"""
import os
from contextlib import contextmanager


class SafeRequestLog:
    def __init__(self):
        self.events: list[str] = []

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
        yield recorder.events
        return
    previous = queue_client.logger
    queue_client.logger = recorder
    try:
        yield recorder.events
    finally:
        queue_client.logger = previous
