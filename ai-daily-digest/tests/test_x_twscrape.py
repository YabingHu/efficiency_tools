import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from src import main
from src.collectors import last30days_sources
from src.collectors import x_twscrape as x
from src.collectors.x_diagnostics import (
    SafeRequestLog,
    capture_request_events,
    safe_exception_details,
)
from src.config import validate_config
from src.x_setup import save_cookies

COOKIES = {"auth_token": "a" * 40, "ct0": "b" * 64}
NOW = datetime(2026, 10, 9, 2, tzinfo=UTC)


def tweet(native_id=123, **overrides):
    values = dict(
        id=native_id, user=SimpleNamespace(username="example"),
        rawContent="New open LLM benchmark &amp; reproducible code", date=NOW,
        likeCount=10, replyCount=2, retweetCount=3, retweetedTweet=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeAPI:
    def __init__(self, batches):
        self.batches = iter(batches)
        self.queries = []
        self.closed = 0
        self.pool = self

    async def add_account_cookies(self, name, cookies):
        self.cookies = cookies

    async def search(self, query, limit):
        self.queries.append(query)
        try:
            batch = next(self.batches)
            for value in batch:
                if isinstance(value, Exception):
                    raise value
                yield value
        finally:
            self.closed += 1


@pytest.fixture
def x_cfg(cfg, monkeypatch):
    monkeypatch.delenv("X_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("X_CT0", raising=False)
    cfg["sources"]["x_twscrape"].update(
        accounts=["example", "other"], request_delay_seconds=0,
    )
    return cfg


def fetch(cfg):
    return asyncio.run(x._fetch(cfg, COOKIES, NOW - timedelta(hours=48), NOW))


def test_missing_and_partial_credentials_do_not_start_network(x_cfg, monkeypatch, caplog):
    monkeypatch.setattr(x, "_create_api", lambda *_: pytest.fail("不应联网"))
    today = datetime.now(UTC).astimezone(x.ZoneInfo("Asia/Shanghai")).date()
    assert x.collect(x_cfg, today) == []
    assert x_cfg["_collector_status"]["x_twscrape"]["status"] == "missing_credentials"
    monkeypatch.setenv("X_AUTH_TOKEN", COOKIES["auth_token"])
    assert x.collect(x_cfg, today) == []
    assert x_cfg["_collector_status"]["x_twscrape"]["status"] == "invalid_credentials"
    assert COOKIES["auth_token"] not in caplog.text


def test_disabled_and_historical_reports_do_not_load_credentials(x_cfg, monkeypatch):
    monkeypatch.setattr(x, "load_cookies", lambda *_: pytest.fail("不应读取凭据"))
    assert x.collect(x_cfg, NOW.date() - timedelta(days=365)) == []
    assert x_cfg["_collector_status"]["x_twscrape"]["status"] == "historical_unsupported"
    x_cfg["sources"]["x_twscrape"]["enabled"] = False
    assert x.collect(x_cfg, NOW.date()) == []
    assert x_cfg["_collector_status"]["x_twscrape"]["status"] == "disabled"


def test_mapping_dedup_and_time_filters(x_cfg, monkeypatch):
    api = FakeAPI([
        [tweet(), tweet(124, date=NOW - timedelta(days=3)), tweet(125, retweetedTweet=True)],
        [tweet(), tweet(126), tweet(127, date=NOW + timedelta(seconds=1))],
    ])
    monkeypatch.setattr(x, "_create_api", lambda *_: api)
    result = fetch(x_cfg)
    assert [item.id for item in result] == ["x:123", "x:126"]
    assert result[0].text == "New open LLM benchmark & reproducible code"
    assert result[0].meta["author"] == "example"
    assert result[0].meta["points"] == 10
    assert result[0].meta["comments"] == 2
    assert result[0].url == "https://x.com/example/status/123"
    assert all("since:2026-10-07 until:2026-10-10" in query for query in api.queries)
    assert x_cfg["_collector_status"]["x_twscrape"]["status"] == "ok"
    status = x_cfg["_collector_status"]["x_twscrape"]
    assert status["attempted_queries"] == status["completed_queries"] == 2
    assert status["received_items"] == 6
    assert status["discarded_items"] == 4


def test_failure_preserves_partial_results_and_does_not_leak_secrets(x_cfg, monkeypatch, caplog):
    api = FakeAPI([[tweet()], [RuntimeError(COOKIES["auth_token"])]])
    monkeypatch.setattr(x, "_create_api", lambda *_: api)
    assert len(fetch(x_cfg)) == 1
    status = x_cfg["_collector_status"]["x_twscrape"]
    assert status["status"] == "partial"
    assert status["errors"] == ["RuntimeError"]
    assert COOKIES["auth_token"] not in str(status) + caplog.text


def test_caps_close_generator_even_if_upstream_ignores_limit(x_cfg, monkeypatch):
    x_cfg["sources"]["x_twscrape"].update(max_per_query=2, max_fetch=3)
    api = FakeAPI([[tweet(i) for i in range(10)], [tweet(i) for i in range(10, 20)]])
    monkeypatch.setattr(x, "_create_api", lambda *_: api)
    assert len(fetch(x_cfg)) == 3
    assert api.closed == 2


def test_timeout_preserves_received_posts(x_cfg, monkeypatch):
    class SlowAPI(FakeAPI):
        async def search(self, query, limit):
            yield tweet()
            await asyncio.sleep(10)

    x_cfg["sources"]["x_twscrape"].update(
        accounts=["example"], request_timeout_seconds=0.01,
    )
    monkeypatch.setattr(x, "_create_api", lambda *_: SlowAPI([]))
    assert len(fetch(x_cfg)) == 1
    assert x_cfg["_collector_status"]["x_twscrape"]["errors"] == ["request_timeout"]


def test_total_timeout_includes_authentication(x_cfg, monkeypatch):
    class SlowAPI(FakeAPI):
        async def add_account_cookies(self, *_):
            await asyncio.sleep(10)

    x_cfg["sources"]["x_twscrape"]["timeout_seconds"] = 0.01
    monkeypatch.setattr(x, "_create_api", lambda *_: SlowAPI([]))
    assert fetch(x_cfg) == []
    assert x_cfg["_collector_status"]["x_twscrape"]["errors"] == ["total_timeout"]


def test_private_cookie_storage_and_env_precedence(x_cfg, tmp_path, monkeypatch):
    save_cookies(tmp_path, COOKIES)
    assert x.load_cookies(tmp_path) == COOKIES
    assert not (tmp_path / "output").exists()
    replacement = {"auth_token": "c" * 40, "ct0": "d" * 64}
    monkeypatch.setenv("X_AUTH_TOKEN", replacement["auth_token"])
    monkeypatch.setenv("X_CT0", replacement["ct0"])
    assert x.load_cookies(tmp_path) == replacement
    child = last30days_sources._child_env()
    assert "X_AUTH_TOKEN" not in child and "X_CT0" not in child


def test_real_dependency_accepts_cookies_offline(tmp_path):
    api = x._create_api(tmp_path)
    asyncio.run(api.pool.add_account_cookies(
        "test", f"auth_token={COOKIES['auth_token']}; ct0={COOKIES['ct0']}",
    ))
    assert (tmp_path / ".private" / "x-accounts.db").exists()


def test_pipeline_includes_x_diagnostics(x_cfg, monkeypatch):
    monkeypatch.setattr(main, "COLLECTORS", {"x_twscrape": (x.collect, {"community"})})
    today = datetime.now(UTC).astimezone(x.ZoneInfo("Asia/Shanghai")).date()
    items, diagnostics = main.collect_all(x_cfg, today)
    assert items == []
    assert diagnostics["source_status"]["x_twscrape"]["status"] == "missing_credentials"


@pytest.mark.parametrize("key,value", [
    ("accounts", ["name OR from:someone"]), ("accounts", "example"),
    ("max_fetch", 10000), ("timeout_seconds", 0), ("queries", [""]),
])
def test_invalid_x_configuration_is_rejected(cfg, key, value):
    cfg["sources"]["x_twscrape"][key] = value
    with pytest.raises(ValueError, match="x_twscrape"):
        validate_config(cfg)


@pytest.mark.parametrize("active,error,locked,reason,code", [
    (False, "(32) Could not authenticate you", False, "authentication_failed", 32),
    (False, "(326) Authorization: Denied by access control", False, "access_denied", 326),
    (False, "(88) Rate limit exceeded", False, "rate_limit_reported", 88),
    (False, "", False, "account_inactive", None),
    (True, "", True, "account_cooldown", None),
    (True, "", False, "unknown", None),
])
def test_account_failure_diagnostics_are_safe(
    x_cfg, monkeypatch, caplog, active, error, locked, reason, code,
):
    class NoAccountError(Exception):
        pass

    class AccountAPI(FakeAPI):
        async def get(self, name):
            return SimpleNamespace(
                active=active, error_msg=error + COOKIES["auth_token"],
                locks={COOKIES["ct0"]: datetime.now(UTC) + timedelta(minutes=15)}
                if locked else {},
                cookies=COOKIES, username="private-account-name",
            )

    api = AccountAPI([[NoAccountError(str(COOKIES))]])
    monkeypatch.setattr(x, "_create_api", lambda *_: api)
    assert fetch(x_cfg) == []
    status = x_cfg["_collector_status"]["x_twscrape"]
    diagnostic = status["account_diagnostic"]
    assert status["errors"] == ["NoAccountError"]
    assert status["attempted_queries"] == 1
    assert status["completed_queries"] == 0
    assert status["failure_stage"] == "search"
    assert diagnostic["reason"] == reason
    assert diagnostic.get("upstream_error_code") == code
    assert ("cooldown_until" in diagnostic) == locked
    assert reason in caplog.text
    for secret in (*COOKIES.values(), "private-account-name"):
        assert secret not in str(status) + caplog.text


def test_diagnostic_read_failure_does_not_lose_partial_results(x_cfg, monkeypatch, caplog):
    class BrokenAPI(FakeAPI):
        async def get(self, name):
            raise RuntimeError(str(COOKIES))

    monkeypatch.setattr(x, "_create_api", lambda *_: BrokenAPI([
        [tweet()], [RuntimeError(str(COOKIES))],
    ]))
    assert len(fetch(x_cfg)) == 1
    status = x_cfg["_collector_status"]["x_twscrape"]
    assert status["status"] == "partial"
    assert status["account_diagnostic"]["reason"] == "unavailable"
    for secret in COOKIES.values():
        assert secret not in str(status) + caplog.text


def test_real_dependency_exposes_safe_diagnostic_state(tmp_path):
    async def run():
        api = x._create_api(tmp_path)
        await api.pool.add_account_cookies(
            "daily-digest", f"auth_token={COOKIES['auth_token']}; ct0={COOKIES['ct0']}",
        )
        await api.pool.mark_inactive(
            "daily-digest", "(32) Could not authenticate you " + COOKIES["auth_token"],
        )
        return await x._account_diagnostics(api)

    result = asyncio.run(run())
    assert result["reason"] == "authentication_failed"
    assert result["account_active"] is False
    assert COOKIES["auth_token"] not in str(result)


@pytest.mark.parametrize("message,event", [
    ("XClIdAccountError: Logged-out X web app", "logged_out_web_page"),
    ("Rate limited: 429", "rate_limit_response"),
    ("NetworkError; username=private", "network_retries_exhausted"),
    ("ConnectError; username=private", "connection_retries_exhausted"),
    ("Blocked by Cloudflare: 403", "cloudflare_blocked_response"),
    ("XClIdParseError: unexpected HTML", "web_signing_parse_failed"),
    ("Unhandled API response code: 503", "unexpected_http_status"),
    ("Unknown error. Account timeouted for 15 minutes.", "unexpected_request_error"),
])
def test_upstream_log_only_retains_fixed_categories(message, event, capsys):
    recorder = SafeRequestLog()
    for _ in range(3):
        recorder.warning(message + str(COOKIES))
    recorder.error("unrecognized " + str(COOKIES))
    assert recorder.events == [event]
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_upstream_logger_restored_on_failure():
    from twscrape import queue_client

    previous = queue_client.logger
    with pytest.raises(RuntimeError), capture_request_events():
        assert queue_client.logger is not previous
        raise RuntimeError("test failure")
    assert queue_client.logger is previous


def test_real_queue_retains_cooldown_cause(x_cfg, tmp_path, monkeypatch, caplog, capsys):
    from twscrape import queue_client
    from twscrape.xclid import XClIdAccountError

    async def rejected_request(*args, **kwargs):
        raise XClIdAccountError("Logged-out X web app " + str(COOKIES))

    api = x._create_api(tmp_path)
    previous = queue_client.logger
    monkeypatch.setattr(x, "_create_api", lambda *_: api)
    monkeypatch.setattr(queue_client.Ctx, "req", rejected_request)
    assert fetch(x_cfg) == []
    status = x_cfg["_collector_status"]["x_twscrape"]
    assert status["errors"] == ["NoAccountError"]
    assert status["account_diagnostic"]["reason"] == "account_cooldown"
    assert status["upstream_events"] == ["logged_out_web_page"]
    assert queue_client.logger is previous
    captured = capsys.readouterr()
    for secret in COOKIES.values():
        assert secret not in str(status) + caplog.text + captured.out + captured.err


def test_unknown_http_error_retains_status_and_stage(x_cfg, tmp_path, monkeypatch, caplog):
    import httpx
    from twscrape import queue_client
    from twscrape.http import Response
    from twscrape.xclid import get_tw_page_text

    class RejectedWebClient:
        async def get(self, url):
            return Response(httpx.Response(
                403, text=str(COOKIES),
                request=httpx.Request("GET", "https://x.com/tesla?token=" + COOKIES["ct0"]),
            ))

    async def rejected_request(*args, **kwargs):
        return await get_tw_page_text("https://x.com/tesla", RejectedWebClient())

    api = x._create_api(tmp_path)
    monkeypatch.setattr(x, "_create_api", lambda *_: api)
    monkeypatch.setattr(queue_client.Ctx, "req", rejected_request)
    assert fetch(x_cfg) == []
    status = x_cfg["_collector_status"]["x_twscrape"]
    assert status["upstream_events"] == ["unexpected_request_error"]
    assert status["upstream_errors"] == [{
        "exception_type": "HttpStatusError", "http_status": 403,
        "stage": "web_page_fetch", "endpoint": "web_page",
    }]
    for secret in COOKIES.values():
        assert secret not in str(status) + caplog.text


def test_non_http_exception_details_never_include_message():
    recorder = SafeRequestLog()
    try:
        raise TypeError(str(COOKIES))
    except TypeError:
        recorder.warning("Unknown error. Account timeouted for 15 minutes. " + str(COOKIES))
    assert recorder.errors == [{"exception_type": "TypeError"}]
    private_error_type = type(COOKIES["auth_token"], (Exception,), {})
    assert safe_exception_details(private_error_type(str(COOKIES))) == {
        "exception_type": "OtherError",
    }


def test_homepage_bootstrap_rewrites_only_fixed_url_and_restores(monkeypatch):
    from twscrape import xclid

    seen = []
    client = object()

    async def get_page(url, passed_client):
        assert passed_client is client
        seen.append(url)
        return "page"

    monkeypatch.setattr(xclid, "get_tw_page_text", get_page)
    with pytest.raises(RuntimeError, match="test"), x._homepage_bootstrap():
        for url in ("https://x.com/tesla", "https://x.com/x/migrate"):
            assert asyncio.run(xclid.get_tw_page_text(url, client)) == "page"
        raise RuntimeError("test")
    assert seen == ["https://x.com/", "https://x.com/x/migrate"]
    assert xclid.get_tw_page_text is get_page


def test_real_signing_initialization_uses_homepage(monkeypatch):
    from twscrape import xclid

    class Client:
        closed = False

        async def aclose(self):
            self.closed = True

    client = Client()
    urls = []

    async def get_page(url, passed_client):
        urls.append(url)
        assert passed_client is client
        return "<html></html>"

    async def load_keys(soup, passed_client):
        return [1, 2, 3], "animation"

    monkeypatch.setattr(xclid, "get_tw_page_text", get_page)
    monkeypatch.setattr(xclid, "_make_client", lambda **kwargs: client)
    monkeypatch.setattr(xclid, "load_keys", load_keys)
    with x._homepage_bootstrap():
        result = asyncio.run(xclid.XClIdGen.create(cookies=COOKIES))
    assert urls == ["https://x.com/"]
    assert result.vk_bytes == [1, 2, 3]
    assert client.closed
