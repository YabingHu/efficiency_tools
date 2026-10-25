import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from src.collectors import cn_authors
from src.config import validate_config
from src.main import deduplicate


def payload(when):
    return {
        "status": "ok",
        "received_items": 1,
        "items": [
            {
                "title": "Claude Code 本地部署实测",
                "text": "Claude Code 本地部署实测：配置命令与日志，"
                + "修复报错并测得延迟 10 ms，吞吐提升 20%。" * 8,
                "url": "https://m.weibo.cn/detail/123456",
                "published_at": when.isoformat(),
            }
        ],
    }


def test_author_feed_uses_existing_practice_filter_and_stable_ids(cfg, monkeypatch):
    now = datetime.now(UTC)
    cfg["sources"]["cn_authors"]["authors"] = cfg["sources"]["cn_authors"]["authors"][:1]
    monkeypatch.setattr(cn_authors, "_run_worker", lambda *a: payload(now - timedelta(hours=1)))
    today = now.astimezone(cn_authors.ZoneInfo(cfg["timezone"])).date()
    first = cn_authors.collect(cfg, today)
    second = cn_authors.collect(cfg, today)
    assert len(first) == 1
    assert first[0].source == "微博"
    assert first[0].meta["author"] == "宝玉xp"
    assert first[0].meta["collection_method"] == "author_feed"
    assert len(deduplicate(first + second, {"community_cn"})) == 1


def test_rejects_old_future_undated_and_unexpected_host(cfg):
    now = datetime.now(UTC)
    old = payload(now - timedelta(days=10))["items"][0]
    future = payload(now + timedelta(hours=1))["items"][0]
    undated = {**old, "published_at": ""}
    unsafe = {**payload(now)["items"][0], "url": "https://evil.example/123"}
    today = now.astimezone(cn_authors.ZoneInfo(cfg["timezone"])).date()
    assert (
        cn_authors._recent_rows({"items": [old, future, undated, unsafe]}, "weibo", cfg, today)
        == []
    )


def test_empty_recent_is_healthy_and_failure_does_not_leak_payload(cfg, monkeypatch):
    replies = iter(
        [
            {"status": "empty_recent", "received_items": 5, "valid_items": 5},
            {"status": "failed", "message": "Cookie=secret", "error_type": "secret"},
        ]
    )
    monkeypatch.setattr(cn_authors, "_run_worker", lambda *a: next(replies))
    cn_authors.collect(cfg, datetime.now(cn_authors.ZoneInfo(cfg["timezone"])).date())
    status = cfg["_collector_status"]["cn_authors"]
    assert status["authors"][0]["status"] == "empty_recent"
    assert status["authors"][1]["status"] == "failed"
    assert "secret" not in json.dumps(status)


def test_historical_run_does_not_use_current_session(cfg, monkeypatch):
    monkeypatch.setattr(cn_authors, "_run_worker", lambda *a: pytest.fail("no historical network"))
    assert cn_authors.collect(cfg, (datetime.now(UTC) - timedelta(days=7)).date()) == []
    assert cfg["_collector_status"]["cn_authors"]["status"] == "historical_unsupported"


def test_worker_receives_only_cn_credentials(cfg, monkeypatch, tmp_path):
    runtime = (
        tmp_path
        / ".external-skills/cn-pilot-venv"
        / ("Scripts/python.exe" if cn_authors.os.name == "nt" else "bin/python")
    )
    runtime.parent.mkdir(parents=True)
    runtime.touch()
    monkeypatch.setenv("LLM_API_KEY", "secret")
    monkeypatch.setenv("X_AUTH_TOKEN", "secret")
    monkeypatch.setenv("CN_BROWSER_STATE", "allowed-state")

    def fake_run(command, **kwargs):
        assert kwargs["env"]["CN_BROWSER_STATE"] == "allowed-state"
        assert "LLM_API_KEY" not in kwargs["env"] and "X_AUTH_TOKEN" not in kwargs["env"]
        assert "allowed-state" not in str(command)
        return SimpleNamespace(stdout='{"status":"empty_recent"}', returncode=0)

    monkeypatch.setattr(cn_authors.subprocess, "run", fake_run)
    assert cn_authors._run_worker(cfg, "zhihu", {"author": {}})["status"] == "empty_recent"


def test_toutiao_enrichment_is_only_for_discovered_article(cfg, monkeypatch):
    called = []

    def run(_cfg, platform, request):
        called.append(request["url"])
        return {"status": "ok", "items": [{"url": request["url"], "text": "正文" * 100}]}

    monkeypatch.setattr(cn_authors, "_run_worker", run)
    assert cn_authors.fetch_toutiao_article("https://evil.example/123", cfg) == ""
    assert cn_authors.fetch_toutiao_article("https://www.toutiao.com/article/123/", cfg)
    assert called == ["https://www.toutiao.com/article/123/"]


def test_discovered_toutiao_candidate_uses_browser_body_bridge(cfg, monkeypatch):
    from src.collectors.last30days_sources import _supplement_chinese_content

    url = "https://www.toutiao.com/article/123/"
    body = "Claude Code 实测的命令配置和延迟日志。" * 20
    monkeypatch.setattr(
        cn_authors,
        "_run_worker",
        lambda *a: {
            "status": "ok",
            "items": [{"url": a[2]["url"], "text": body}],
        },
    )
    row = {"title": "Claude Code 部署实测", "url": url}
    result = _supplement_chinese_content([{"toutiao": [row]}], {"toutiao"}, cfg)
    assert result == {"attempted": 1, "succeeded": 1}
    assert body in row["summary"]
    assert cfg["_collector_status"]["toutiao_content"]["succeeded"] == 1


@pytest.mark.parametrize(
    "change",
    [
        {"max_per_author": 100},
        {"authors": [{"platform": "zhihu", "id": "../../x", "name": "x"}]},
    ],
)
def test_validates_limits_and_author_identifiers(cfg, change):
    invalid = deepcopy(cfg)
    invalid["sources"]["cn_authors"].update(change)
    with pytest.raises(ValueError, match="cn_authors"):
        validate_config(invalid)
