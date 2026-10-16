import pytest

from src.editorial import (
    apply_quality_scores,
    build_today_threads,
    filter_noise_items,
    has_community_ai_context,
    primary_topic,
    quality_sort_key,
    score_item_quality,
)
from src.models import NewsItem


@pytest.mark.parametrize("stage", ["pre_llm", "post_llm"])
@pytest.mark.parametrize("section", ["community", "community_cn"])
def test_community_relevance_cannot_be_overridden_by_heat_or_section_floor(stage, section):
    candidate = item(
        "oracle", section=section,
        title="【大】的甲骨文金文篆文字形演变含义 - 甲骨文研究网",
        text="发布于2023年3月19日，研究汉字的字形演变。", score=100000,
    )
    candidate.importance = 5
    candidate.source = "AI 社区"
    candidate.summary_zh = "人工智能相关研究" * 20
    cfg = {"quality": {"min_items_per_section": 1, "min_score": {"default": 0}}}
    assert filter_noise_items(cfg, [candidate], stage=stage) == []


@pytest.mark.parametrize("title,text,expected", [
    ("Daily news", "He said the model railway is ready.", False),
    ("字形演变", "@OpenAI https://example.com/ai/llm", False),
    ("字形演变", "Lobsters AI 社区：5 分，0 条评论。标签：ai。", False),
    ("人工智能辅助甲骨文识别", "研究字形演变", True),
    ("LLMs for coding", "", True),
    ("GPT4 release", "", True),
    ("DeepSeek-V4 update", "", True),
])
def test_community_relevance_uses_content_and_word_boundaries(title, text, expected):
    assert has_community_ai_context(title, text) is expected


def test_community_does_not_fill_with_items_below_quality_threshold():
    candidate = item("low", section="community_cn", title="AI", text="")
    candidate.importance = 1
    cfg = {"quality": {"min_items_per_section": 1, "min_score": {"default": 90}}}
    assert filter_noise_items(cfg, [candidate], stage="post_llm") == []


def item(item_id, section="github", title="LLM agent framework", text=None, score=0):
    return NewsItem(
        item_id,
        section,
        title,
        f"https://example.com/{item_id}",
        "source",
        text=text if text is not None else "An AI model release with benchmark details.",
        score=score,
        importance=3,
    )


def test_quality_score_rewards_ai_relevance_and_substance():
    strong = item("strong", title="Open source LLM inference model release", score=300)
    weak = item("weak", title="Tiny shell theme", text="")

    assert score_item_quality(strong) > score_item_quality(weak)
    assert strong.meta["quality_score"] > 50
    assert "AI 相关性强" in strong.meta["quality_reasons"]


def test_filter_noise_items_keeps_best_fallback_for_sparse_section():
    cfg = {
        "quality": {
            "enabled": True,
            "min_items_per_section": 1,
            "min_score": {"default": 90},
        },
    }
    noisy = item("noisy", title="No details", text="")
    better = item("better", title="LLM benchmark paper", text="benchmark " * 40)

    filtered = filter_noise_items(cfg, [noisy, better], stage="post_llm")

    assert [value.id for value in filtered] == ["better"]


def test_filter_noise_items_uses_looser_pre_llm_threshold():
    cfg = {
        "quality": {
            "enabled": True,
            "min_items_per_section": 0,
            "min_score": {
                "pre_llm": {"default": 0},
                "post_llm": {"default": 100},
            },
        },
    }
    candidate = item("candidate", section="industry", title="LLM model release")

    pre_llm = filter_noise_items(cfg, [candidate], stage="pre_llm")
    post_llm = filter_noise_items(cfg, [candidate], stage="post_llm")

    assert len(pre_llm) >= len(post_llm)
    assert [value.id for value in pre_llm] == ["candidate"]
    assert post_llm == []


def test_quality_sort_key_prioritizes_editorial_score():
    low_importance = item("quality", title="OpenAI LLM safety benchmark", score=0)
    low_importance.importance = 2
    high_importance = item("generic", title="Generic project", text="")
    high_importance.importance = 5
    apply_quality_scores([low_importance, high_importance])

    ranked = sorted([high_importance, low_importance], key=quality_sort_key, reverse=True)

    assert ranked[0].id == "quality"


def test_build_today_threads_groups_related_high_quality_items():
    items = [
        item(
            "a", section="arxiv", title="LLM agent benchmark for tool use",
            text="agent benchmark " * 20,
        ),
        item(
            "b", section="github", title="Open source agent framework",
            text="agent open source " * 20,
        ),
        item("c", section="media", title="AI safety policy", text="AI safety governance " * 20),
    ]
    apply_quality_scores(items)

    threads = build_today_threads(items)

    assert threads
    assert any("智能体" in thread["title"] for thread in threads)
    assert all("LLM agent benchmark for tool use" not in thread["title"] for thread in threads)


def test_primary_topic_is_exclusive_for_overlapping_paper_signals():
    paper = item(
        "paper", section="papers",
        title="Agent benchmark for LLM inference cache",
        text="agent benchmark inference " * 20,
    )

    assert primary_topic(paper) == "智能体"


def test_today_threads_do_not_repeat_the_same_lead_item_across_topics():
    items = [
        item(
            "overlap", section="papers",
            title="Agent benchmark for LLM inference cache",
            text="agent benchmark inference " * 20,
        ),
        item(
            "agent", section="agent",
            title="Tool calling agent orchestration",
            text="agent tool calling " * 20,
        ),
        item(
            "safety", section="media",
            title="AI safety governance release",
            text="AI safety governance " * 20,
        ),
        item(
            "security", section="community",
            title="Security discussion for AI systems",
            text="AI security discussion " * 20,
        ),
    ]
    apply_quality_scores(items)

    threads = build_today_threads(items)
    lead_titles = [thread["title"] for thread in threads]

    assert len(lead_titles) == len(set(lead_titles))
    assert all("Agent benchmark" not in title for title in lead_titles)


def test_today_threads_avoid_overview_lead_items():
    items = [
        item(
            "anthropic", section="media",
            title="Anthropic reveals Claude security incident in real companies",
            text="Claude security governance incident " * 20,
            score=300,
        ),
        item(
            "openai", section="industry",
            title="OpenAI宣布全球活跃用户突破10亿",
            text="OpenAI product growth 用户 10 亿 " * 20,
            score=250,
        ),
        item(
            "agent", section="agent",
            title="Agent workflow orchestration benchmark",
            text="agent tool calling orchestration " * 20,
            score=200,
        ),
    ]
    apply_quality_scores(items)
    overview = [
        "Anthropic 披露 Claude 安全事件，引发真实公司系统风险担忧。",
        "OpenAI 全球活跃用户突破 10 亿，成为 AI 行业规模化标志。",
    ]

    threads = build_today_threads(items, overview_points=overview)
    lead_ids = {thread["item_ids"][0] for thread in threads}

    assert "anthropic" not in lead_ids
    assert "openai" not in lead_ids
    assert any("智能体" in thread["title"] for thread in threads)


def test_today_threads_use_theme_titles_instead_of_news_titles():
    items = [
        item(
            "safety", section="media",
            title="Anthropic reveals Claude security incident in real companies",
            text="Claude security hack incident " * 20,
            score=300,
        ),
        item(
            "security", section="community",
            title="Security discussion around autonomous AI systems",
            text="AI security governance " * 20,
            score=150,
        ),
    ]
    apply_quality_scores(items)

    threads = build_today_threads(items)

    assert threads[0]["title"] == "安全治理：模型自主行动能力正在逼近真实系统风险"
