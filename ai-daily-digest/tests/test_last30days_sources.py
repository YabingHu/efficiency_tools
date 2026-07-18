from copy import deepcopy
from datetime import date

from src.collectors import last30days_sources
from src.models import NewsItem


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

    assert {item.source for item in result} == {"微博", "百度热搜"}
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

    assert [item.id for item in result] == ["last30days-cn-bilibili:technical-video"]


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
