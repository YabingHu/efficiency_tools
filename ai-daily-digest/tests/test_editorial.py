from src.editorial import (
    apply_quality_scores,
    build_today_threads,
    filter_noise_items,
    quality_sort_key,
    score_item_quality,
)
from src.models import NewsItem


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
