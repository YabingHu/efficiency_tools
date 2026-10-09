import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from src import main
from src.collectors import last30days_sources
from src.collectors import x_twscrape as x
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
