"""Editorial scoring, noise filtering, and lead-story synthesis."""
from __future__ import annotations

import math
import re
from collections import defaultdict

from .models import NewsItem

AI_TERMS = (
    "ai", "llm", "gpt", "agent", "rag", "model", "transformer", "claude",
    "deepseek", "gemini", "qwen", "openai", "anthropic", "inference",
    "embedding", "diffusion", "neural", "machine learning", "multimodal",
    "benchmark", "reasoning", "alignment", "robot", "机器人", "大模型",
    "人工智能", "智能体", "推理", "多模态", "开源模型", "具身智能",
)

SUBSTANCE_TERMS = (
    "release", "launch", "paper", "benchmark", "dataset", "open source",
    "weights", "model", "framework", "agent", "security", "safety",
    "performance", "latency", "evaluation", "study", "research", "发布",
    "开源", "论文", "数据集", "模型", "评测", "安全", "性能", "研究",
)

LOW_SIGNAL_PATTERNS = (
    re.compile(r"来源未提供更多细节|信息不足|描述为空|未提供任何细节"),
    re.compile(r"^.{0,80}(awesome|list|curated list|roadmap|tutorial)$", re.I),
)

SECTION_BASE = {
    "papers": 24,
    "arxiv": 20,
    "eval": 22,
    "agent": 22,
    "industry": 22,
    "github": 15,
    "media": 18,
    "community": 14,
    "community_cn": 14,
}


def _haystack(item: NewsItem) -> str:
    return " ".join(
        [item.title, item.source, item.text, item.summary_zh, item.comment]
    ).lower()


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _score_heat(score: float) -> float:
    if score <= 0:
        return 0
    return min(12, math.log10(score + 1) * 5)


def score_item_quality(item: NewsItem) -> float:
    """Compute a stable editorial quality score and store reasons in metadata."""
    text = _haystack(item)
    score = float(SECTION_BASE.get(item.section, 12))
    reasons: list[str] = []

    if item.importance:
        score += item.importance * 9
        reasons.append(f"重要度 {item.importance}")
    if item.score:
        heat = _score_heat(float(item.score))
        score += heat
        if heat >= 4:
            reasons.append("来源热度高")
    if item.summary_zh and len(item.summary_zh.strip()) >= 80:
        score += 7
        reasons.append("信息量充足")
    elif item.text and len(item.text.strip()) >= 160:
        score += 4
    else:
        score -= 12
        reasons.append("素材偏短")

    if _contains_any(text, AI_TERMS):
        score += 8
        reasons.append("AI 相关性强")
    else:
        score -= 18
        reasons.append("AI 相关性弱")

    if _contains_any(text, SUBSTANCE_TERMS):
        score += 6
        reasons.append("有实质发布/研究信号")

    if item.section == "github":
        if not item.text.strip() and not item.summary_zh.strip():
            score -= 18
            reasons.append("项目描述为空")
        if not item.meta.get("stars_today") and item.score < 50:
            score -= 8
    if item.section in {"community", "community_cn"}:
        comments = item.meta.get("comments") or 0
        if comments:
            score += min(6, math.log10(float(comments) + 1) * 4)
    if any(
        pattern.search(" ".join([item.title, item.text, item.summary_zh]))
        for pattern in LOW_SIGNAL_PATTERNS
    ):
        score -= 20
        reasons.append("低信息密度")

    value = round(max(0, min(100, score)), 1)
    item.meta["quality_score"] = value
    item.meta["quality_reasons"] = reasons[:4]
    return value


def apply_quality_scores(items: list[NewsItem]) -> None:
    for item in items:
        score_item_quality(item)


def filter_noise_items(cfg: dict, items: list[NewsItem], *, stage: str) -> list[NewsItem]:
    """Drop obvious low-signal items while preserving room for sparse sections."""
    quality_cfg = cfg.get("quality", {})
    if not quality_cfg.get("enabled", True):
        apply_quality_scores(items)
        return items

    thresholds = quality_cfg.get("min_score", {})
    default_threshold = thresholds.get("default", 18 if stage == "pre_llm" else 24)
    kept_by_section: dict[str, list[NewsItem]] = defaultdict(list)
    for item in items:
        quality = score_item_quality(item)
        threshold = thresholds.get(item.section, default_threshold)
        if quality >= threshold:
            kept_by_section[item.section].append(item)

    # Keep a small sample per non-empty section, so sparse days do not look broken.
    minimum = quality_cfg.get("min_items_per_section", 1)
    if minimum:
        original_by_section: dict[str, list[NewsItem]] = defaultdict(list)
        for item in items:
            original_by_section[item.section].append(item)
        for section, original in original_by_section.items():
            if kept_by_section.get(section):
                continue
            fallback = sorted(
                original,
                key=lambda item: item.meta.get("quality_score", 0),
                reverse=True,
            )[:minimum]
            kept_by_section[section].extend(fallback)

    filtered = [
        item
        for item in items
        if item in kept_by_section.get(item.section, [])
    ]
    return filtered


def quality_sort_key(item: NewsItem) -> tuple[float, int, float]:
    return (
        float(item.meta.get("quality_score", 0)),
        int(item.importance or 0),
        float(item.score or 0),
    )


def topic_tags(item: NewsItem) -> list[str]:
    text = _haystack(item)
    tags = []
    if item.section in {"papers", "arxiv", "eval", "agent"}:
        tags.append("论文")
    if any(term in text for term in ("agent", "智能体", "tool use", "tool calling")):
        tags.append("智能体")
    if any(term in text for term in ("benchmark", "evaluation", "leaderboard", "评测")):
        tags.append("评测")
    if any(term in text for term in ("open source", "weights", "开源", "github")):
        tags.append("开源")
    if any(term in text for term in ("safety", "security", "alignment", "安全", "治理")):
        tags.append("安全治理")
    if any(term in text for term in ("inference", "latency", "cache", "推理", "性能")):
        tags.append("工程优化")
    if item.section in {"industry", "media"}:
        tags.append("产业动态")
    if item.section in {"community", "community_cn"}:
        tags.append("社区热议")
    return list(dict.fromkeys(tags))[:3]


def primary_topic(item: NewsItem) -> str:
    """Assign one editorial lane so the same item cannot dominate several threads."""
    text = _haystack(item)
    if item.section == "agent" or any(
        term in text for term in ("agent", "智能体", "tool use", "tool calling")
    ):
        return "智能体"
    if item.section == "eval" or any(
        term in text for term in ("benchmark", "evaluation", "leaderboard", "评测")
    ):
        return "评测"
    if any(term in text for term in ("safety", "security", "alignment", "安全", "治理")):
        return "安全治理"
    if any(term in text for term in ("inference", "latency", "cache", "推理", "性能")):
        return "工程优化"
    if any(term in text for term in ("open source", "weights", "开源", "github")):
        return "开源"
    if item.section in {"papers", "arxiv"}:
        return "论文"
    if item.section in {"industry", "media"}:
        return "产业动态"
    if item.section in {"community", "community_cn"}:
        return "社区热议"
    return "其他"


def _short_title(title: str) -> str:
    value = " ".join(title.split())
    return value if len(value) <= 64 else value[:63].rstrip() + "…"


def build_today_threads(items: list[NewsItem], limit: int = 4) -> list[dict]:
    """Create deterministic editorial threads for the top of the digest."""
    buckets: dict[str, list[NewsItem]] = defaultdict(list)
    for item in items:
        buckets[primary_topic(item)].append(item)

    candidates = []
    for tag, tagged in buckets.items():
        ranked = sorted(tagged, key=quality_sort_key, reverse=True)
        if len(ranked) < 2 and ranked[0].meta.get("quality_score", 0) < 60:
            continue
        top = ranked[:3]
        sources = "、".join(list(dict.fromkeys(item.source for item in top))[:3])
        lead = _short_title(top[0].title)
        candidates.append({
            "title": f"{tag}：{lead}",
            "summary": f"{len(ranked)} 条相关内容，主要来自 {sources}。",
            "item_ids": [item.id for item in top],
            "score": round(sum(item.meta.get("quality_score", 0) for item in top), 1),
        })

    candidates.sort(key=lambda thread: thread["score"], reverse=True)
    threads, used_items = [], set()
    for candidate in candidates:
        if used_items & set(candidate["item_ids"]):
            continue
        threads.append(candidate)
        used_items.update(candidate["item_ids"])
        if len(threads) >= limit:
            break
    return threads
