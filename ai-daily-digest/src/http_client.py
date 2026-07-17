"""带连接复用、双超时和有限重试的线程本地 HTTP 客户端。"""
from threading import local

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_local = local()


def _session(retries: int) -> requests.Session:
    cache = getattr(_local, "sessions", None)
    if cache is None:
        cache = _local.sessions = {}
    if retries not in cache:
        retry = Retry(
            total=retries,
            connect=retries,
            read=retries,
            status=retries,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
        session = requests.Session()
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        cache[retries] = session
    return cache[retries]


def get(url: str, *, cfg: dict, **kwargs) -> requests.Response:
    http = cfg.get("http", {})
    retries = kwargs.pop("retries", http.get("retries", 2))
    kwargs.setdefault(
        "timeout",
        (http.get("connect_timeout_seconds", 5), http.get("read_timeout_seconds", 30)),
    )
    return _session(retries).get(url, **kwargs)
