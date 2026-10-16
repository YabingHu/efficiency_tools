from copy import deepcopy
from datetime import date
from pathlib import Path
from subprocess import TimeoutExpired
from types import SimpleNamespace

import pytest

from src.collectors import last30days_sources
from src.models import NewsItem


def test_chinese_search_drops_irrelevant_and_known_outdated_results():
    rows = [
        {"id": "oracle", "title": "【大】的甲骨文金文篆文字形演变含义"},
        {"id": "old", "title": "人工智能研究", "date": "2023-03-19"},
        {"id": "future", "title": "人工智能研究", "date": "2026-10-13"},
        {"id": "recent", "title": "大模型新进展", "published_at": "2026-10-11T12:00:00Z"},
        {"id": "boundary", "title": "LLM 新进展", "date": "2026-10-10"},
        {"id": "unknown", "title": "AI 模型发布"},
    ]
    for row in rows:
        row["url"] = f"https://example.com/{row['id']}"
    result = last30days_sources._chinese_items(
        {"baidu": rows}, {"baidu"}, report_date=date(2026, 10, 12), lookback_days=2,
    )
    assert [entry.url for entry in result] == [
        "https://example.com/recent", "https://example.com/boundary",
        "https://example.com/unknown",
    ]


def test_english_results_map_reddit_and_x_only():
    payload = {
        "results": [
            {
                "candidate_id": "reddit-1",
                "title": "Open model release",
                "source": "reddit",
                "url": "https://www.reddit.com/r/LocalLLaMA/comments/abc",
                "summary": "A technical discussion of the release.",
                "relevance_score": 0.9,
                "engagement": {"score": 120, "num_comments": 35},
            },
            {
                "candidate_id": "x-1",
                "title": "New coding model benchmark",
                "source": "x",
                "url": "https://x.com/example/status/123",
                "summary": "Benchmark results and reactions.",
                "engagement": {"likes": 300, "replies": 20},
            },
            {
                "candidate_id": "hn-1",
                "title": "Duplicate source",
                "source": "hackernews",
                "url": "https://news.ycombinator.com/item?id=1",
            },
        ]
    }

    result = last30days_sources._english_items(payload, {"reddit", "x"})

    assert [item.source for item in result] == ["Reddit", "X"]
    assert all(item.section == "community" for item in result)
    assert result[0].meta["comments"] == 35
    assert result[1].meta["points"] == 300


def test_chinese_platform_arrays_map_to_separate_section():
    payload = {
        "weibo": [{
            "id": "wb-1",
            "title": "大模型新进展",
            "url": "https://s.weibo.com/weibo?q=AI",
            "description": "公开讨论摘要",
            "score": 80,
        }],
        "baidu": [{
            "title": "AI 热点",
            "url": "https://www.baidu.com/s?wd=AI",
            "snippet": "热点详情",
        }],
    }

    result = last30days_sources._chinese_items(payload, {"weibo", "baidu"})

    assert {item.source for item in result} == {"微博", "百度搜索"}
    assert all(item.section == "community_cn" for item in result)


def test_chinese_results_filter_bilibili_paid_course_ads():
    payload = {
        "bilibili": [
            {
                "id": "course-ad",
                "title": "【限时6折】小白玩转AI大模型应用开发",
                "url": "https://www.bilibili.com/cheese/play/ss11176?query_from=0",
                "description": "AI 智能体付费课程",
            },
            {
                "id": "technical-video",
                "title": "从零实现一个大模型 Agent",
                "url": "https://www.bilibili.com/video/BV1example",
                "description": "完整讲解工具调用与状态管理。",
            },
        ]
    }

    result = last30days_sources._chinese_items(payload, {"bilibili"})

    assert [item.url for item in result] == ["https://www.bilibili.com/video/BV1example"]


def test_chinese_ad_filter_requires_strong_commercial_signals():
    assert last30days_sources._is_chinese_community_ad(
        "AI 实战训练营限时优惠", "立即报名，早鸟价立减 300 元", "https://example.com/course"
    )
    assert not last30days_sources._is_chinese_community_ad(
        "新模型限时开放体验", "官方公布最新推理能力。", "https://example.com/release"
    )


def test_english_results_support_youtube_and_bluesky():
    payload = {
        "results": [
            {
                "candidate_id": "yt-1",
                "title": "Model release walkthrough",
                "source": "youtube",
                "url": "https://www.youtube.com/watch?v=abc",
                "summary": "A technical walkthrough.",
                "engagement": {"likes": 400, "comment_count": 20},
            },
            {
                "candidate_id": "bsky-1",
                "title": "Researcher reaction",
                "source": "bluesky",
                "url": "https://bsky.app/profile/example/post/abc",
                "summary": "A researcher discusses the result.",
                "engagement": {"likes": 80, "replies": 12},
            },
        ]
    }

    result = last30days_sources._english_items(payload, {"youtube", "bluesky"})

    assert [item.source for item in result] == ["YouTube", "Bluesky"]
    assert result[0].meta["comments"] == 20


def test_collect_runs_enabled_languages_and_preserves_order(monkeypatch, cfg):
    cfg = deepcopy(cfg)
    cfg["sections"]["community_cn"] = {
        "enabled": True, "title": "中文", "limit": 4,
    }
    cfg["sources"]["last30days"] = {
        "enabled": True,
        "english": {"enabled": True},
        "chinese": {"enabled": True},
    }
    english = NewsItem("en", "community", "English", "https://example.com/en", "X")
    chinese = NewsItem("cn", "community_cn", "中文", "https://example.com/cn", "微博")
    monkeypatch.setattr(
        last30days_sources, "_collect_english", lambda *_args: [english]
    )
    monkeypatch.setattr(
        last30days_sources, "_collect_chinese", lambda *_args: [chinese]
    )

    result = last30days_sources.collect(cfg, date(2026, 7, 18))

    assert result == [english, chinese]


def test_child_environment_does_not_expose_llm_key(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "must-not-leak")
    monkeypatch.setenv("XAI_API_KEY", "x-key")

    env = last30days_sources._child_env()

    assert "LLM_API_KEY" not in env
    assert env["XAI_API_KEY"] == "x-key"
    assert env["FROM_BROWSER"] == "off"
    assert str(last30days_sources.Path(last30days_sources.sys.executable).parent) in env["PATH"]


def practice_row(url="https://example.com/practice", **fields):
    return {
        "id": "ZH1", "title": "Qwen 本地部署实测与故障排查", "url": url,
        "abstract": "使用 vLLM 配置本地 Qwen 模型，对比不同 GPU 的显存占用和吞吐，"
                    "记录报错日志、复现步骤及修复方法。" * 2,
        "date": "2026-10-16", **fields,
    }


@pytest.mark.parametrize("platform,field", [
    ("toutiao", "abstract"), ("zhihu", "excerpt"), ("bilibili", "description"),
])
def test_chinese_preserves_platform_body_and_author(platform, field):
    row = practice_row()
    body = row.pop("abstract")
    row[field] = body
    row["channel_name" if platform == "bilibili" else "author"] = "开发者"
    result = last30days_sources._chinese_items({platform: [row]}, {platform}, practice_only=True)
    assert result[0].text == body
    assert result[0].meta["author"] == "开发者"


def test_weibo_body_is_not_duplicated_as_the_entire_title():
    from src.editorial import has_sufficient_source

    row = practice_row()
    row.pop("title")
    row["text"] = row.pop("abstract")
    result = last30days_sources._chinese_items({"weibo": [row]}, {"weibo"}, practice_only=True)
    assert result[0].title != result[0].text
    assert len(result[0].title) <= 61
    assert has_sufficient_source(result[0], 60)


def test_practice_filter_counts_rejections_without_rejecting_useful_content():
    rows = [
        practice_row(),
        practice_row(
            "https://example.com/intro", title="AI 大模型是什么，一次讲清", abstract="概念介绍",
        ),
        practice_row(
            "https://example.com/hype", title="Qwen 实测太强了", abstract="效果惊艳，快来看看",
        ),
        practice_row("https://example.com/old", date="2023-03-19"),
    ]
    diagnostics = {}
    result = last30days_sources._chinese_items(
        {"toutiao": rows}, {"toutiao"}, practice_only=True,
        report_date=date(2026, 10, 17), diagnostics=diagnostics,
    )
    assert [item.url for item in result] == ["https://example.com/practice"]
    assert diagnostics["toutiao"] == {
        "received": 4, "accepted": 1, "filtered": {"not_practice": 2, "out_of_range": 1},
    }


def test_chinese_uses_global_timeout_and_merges_queries_without_id_collisions(monkeypatch, cfg):
    source_cfg = cfg["sources"]["last30days"]["chinese"]
    source_cfg.update(queries=["Qwen 部署", "Claude Code 实测"], sources=["zhihu"])
    source_cfg["request_timeout_seconds"] = 20  # 兼容旧配置，不能覆盖全局预算。
    monkeypatch.setattr(
        last30days_sources, "_script_path", lambda *_: Path("engine/scripts/main.py"),
    )
    calls = []
    first = practice_row("https://example.com/first")
    second = practice_row("https://example.com/second")  # 上游依然叫 ZH1。
    richer = {**first, "abstract": first["abstract"] + "完整复现命令。"}

    def engine(script, args, timeout):
        calls.append((args, timeout))
        return {"zhihu": [first] if args[0] == "Qwen 部署" else [second, richer]}

    monkeypatch.setattr(last30days_sources, "_run_engine", engine)
    result = last30days_sources._collect_chinese(cfg, date(2026, 10, 17), source_cfg)
    assert {item.url for item in result} == {first["url"], second["url"]}
    assert len({item.id for item in result}) == 2
    assert next(item for item in result if item.url == first["url"]).text == richer["abstract"]
    assert len(calls) == 2
    assert all(args[args.index("--timeout") + 1] == "150" for args, _ in calls)
    assert all(timeout == 160 for _, timeout in calls)
    status = cfg["_collector_status"]["last30days_chinese"]
    assert status["status"] == "ok"
    assert status["duplicate_items"] == 1
    assert status["platforms"]["zhihu"]["received"] == 3


def test_chinese_diagnostics_distinguish_failure_empty_and_filtering(monkeypatch, cfg):
    source_cfg = cfg["sources"]["last30days"]["chinese"]
    source_cfg.update(queries=["Qwen 部署"], sources=["zhihu", "weibo", "baidu"])
    monkeypatch.setattr(
        last30days_sources, "_script_path", lambda *_: Path("engine/scripts/main.py"),
    )
    monkeypatch.setattr(last30days_sources, "_run_engine", lambda *_: {
        "zhihu": [], "zhihu_error": "private upstream error",
        "weibo": [], "baidu": [practice_row(title="AI 概念科普", abstract="没有正文")],
    })
    assert last30days_sources._collect_chinese(cfg, date(2026, 10, 17), source_cfg) == []
    status = cfg["_collector_status"]["last30days_chinese"]
    assert status["status"] == "partial"
    assert status["platforms"]["zhihu"]["status"] == "failed"
    assert status["platforms"]["weibo"]["status"] == "empty"
    assert status["platforms"]["baidu"]["status"] == "ok"
    assert status["platforms"]["baidu"]["filtered"]["not_practice"] == 1
    assert "private upstream error" not in str(status)


def test_chinese_missing_engine_is_reported(monkeypatch, cfg):
    monkeypatch.setattr(last30days_sources, "_script_path", lambda *_: None)
    assert last30days_sources._collect_chinese(
        cfg, date(2026, 10, 17), cfg["sources"]["last30days"]["chinese"],
    ) == []
    assert cfg["_collector_status"]["last30days_chinese"]["status"] == "missing_engine"


@pytest.mark.parametrize("state", ["timeout", "failed", "invalid_json"])
def test_chinese_engine_failure_is_not_reported_as_normal_empty(monkeypatch, cfg, state):
    source_cfg = cfg["sources"]["last30days"]["chinese"]
    source_cfg.update(queries=["Qwen 部署"], sources=["zhihu"])
    monkeypatch.setattr(
        last30days_sources, "_script_path", lambda *_: Path("engine/scripts/main.py"),
    )
    monkeypatch.setattr(last30days_sources, "_run_engine", lambda *_: {"_engine_status": state})
    assert last30days_sources._collect_chinese(cfg, date(2026, 10, 17), source_cfg) == []
    status = cfg["_collector_status"]["last30days_chinese"]
    assert status["status"] == "failed"
    assert status["platforms"]["zhihu"]["query_statuses"] == [state]


def test_run_engine_timeout_and_invalid_output_are_explicit(monkeypatch):
    def timeout(*args, **kwargs):
        raise TimeoutExpired("engine", 150)

    monkeypatch.setattr(last30days_sources.subprocess, "run", timeout)
    script = Path("engine/scripts/main.py")
    assert last30days_sources._run_engine(script, [], 150)["_engine_status"] == "timeout"
    monkeypatch.setattr(last30days_sources.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout="not JSON", stderr="private error",
    ))
    assert last30days_sources._run_engine(script, [], 150)["_engine_status"] == "invalid_json"


def test_engine_platform_errors_are_sanitized_and_survive_valid_json(monkeypatch):
    monkeypatch.setattr(last30days_sources.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout='prefix\n{"weibo": [], "bilibili": []}',
        stderr="[微博] 公共接口搜索失败: HTTP Error 403 secret-cookie\n"
               "[B站] 搜索第 1 页失败: timed out private-url\n"
               "[未知] secret-token\n",
    ))
    payload = last30days_sources._run_engine(Path("engine/scripts/main.py"), [], 150)
    assert payload["_engine_status"] == "ok"
    assert payload["_engine_platform_errors"] == {"weibo": ["http_403"], "bilibili": ["timeout"]}
    assert "secret" not in str(payload)


def test_body_supplement_is_bounded_and_updates_duplicate_links(monkeypatch, cfg):
    cfg["sources"]["last30days"]["chinese"]["content_fetch_limit"] = 1
    first = practice_row(abstract="原文提供 Qwen 部署实测。")
    duplicate = dict(first)
    second = practice_row("https://example.com/other", abstract="原文提供 Qwen 部署实测。")
    payloads = [{"zhihu": [first, second]}, {"zhihu": [duplicate]}]
    calls = []
    body = "Qwen 部署的显存占用和报错修复日志。" * 20

    def extract(url, cfg, min_chars):
        calls.append(url)
        assert cfg["http"]["read_timeout_seconds"] == 10
        return body

    monkeypatch.setattr(last30days_sources, "extract_text_from_url", extract)
    status = last30days_sources._supplement_chinese_content(payloads, {"zhihu"}, cfg)
    assert status == {"attempted": 1, "succeeded": 1}
    assert calls == [first["url"]]
    assert body in first["summary"] and body in duplicate["summary"]
    assert "summary" not in second


def test_body_supplement_failure_keeps_original_material(monkeypatch, cfg):
    row = practice_row(abstract="Qwen 部署实测")
    original = dict(row)
    monkeypatch.setattr(last30days_sources, "extract_text_from_url", lambda *a, **kw: "")
    result = last30days_sources._supplement_chinese_content([{"zhihu": [row]}], {"zhihu"}, cfg)
    assert result == {"attempted": 1, "succeeded": 0}
    assert row == original


def test_stale_results_do_not_consume_body_fetch_budget(monkeypatch, cfg):
    cfg["sources"]["last30days"]["chinese"]["content_fetch_limit"] = 1
    old = practice_row("https://example.com/old", abstract="Qwen 部署实测", date="2023-03-19")
    recent = practice_row(abstract="Qwen 部署实测")
    calls = []
    monkeypatch.setattr(
        last30days_sources, "extract_text_from_url", lambda url, *a, **kw: calls.append(url) or "",
    )
    last30days_sources._supplement_chinese_content(
        [{"zhihu": [old, recent]}], {"zhihu"}, cfg, report_date=date(2026, 10, 17),
    )
    assert calls == [recent["url"]]
