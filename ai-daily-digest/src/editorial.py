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

SECTION_PRIORITY = {
    "papers": 9,
    "eval": 8,
    "agent": 8,
    "arxiv": 7,
    "industry": 6,
    "media": 5,
    "github": 5,
    "community": 4,
    "community_cn": 3,
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
    stage_thresholds = thresholds.get(stage) if isinstance(thresholds, dict) else None
    if isinstance(stage_thresholds, dict):
        thresholds = stage_thresholds
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


def _significant_terms(text: str) -> set[str]:
    normalized = text.lower()
    terms = {
        term
        for term in re.findall(r"[a-z][a-z0-9-]{2,}", normalized)
        if term not in {"the", "and", "for", "with", "from", "into", "using"}
    }
    cjk = re.findall(r"[\u4e00-\u9fff]", text)
    terms.update("".join(cjk[i:i + 2]) for i in range(max(0, len(cjk) - 1)))
    return terms


def near_duplicate_similarity(left: NewsItem, right: NewsItem) -> float:
    """计算两条资讯标题与摘要有效词的 Jaccard 相似度。"""
    left_body = left.summary_zh.strip() or left.text.strip()
    right_body = right.summary_zh.strip() or right.text.strip()
    left_terms = _significant_terms(f"{left.title} {left_body}")
    right_terms = _significant_terms(f"{right.title} {right_body}")
    if min(len(left_terms), len(right_terms)) < 3:
        return 0.0
    overlap = left_terms & right_terms
    if len(overlap) < 3:
        return 0.0
    return len(overlap) / len(left_terms | right_terms)


def _near_duplicate_rank(item: NewsItem) -> tuple[float, int, float, int]:
    quality = item.meta.get("quality_score")
    quality_score = float(quality) if quality is not None else -1.0
    return (
        quality_score,
        int(item.importance or 0),
        float(item.score or 0),
        SECTION_PRIORITY.get(item.section, 0),
    )


def collapse_near_duplicates(items: list[NewsItem], *, similarity: float = 0.6) -> list[NewsItem]:
    """折叠不同板块的近似资讯，保留质量更高的条目。"""
    kept: list[NewsItem] = []
    for item in items:
        duplicate_index = next(
            (
                index for index, existing in enumerate(kept)
                if item.section != existing.section
                and near_duplicate_similarity(item, existing) >= similarity
            ),
            None,
        )
        if duplicate_index is None:
            kept.append(item)
            continue
        if _near_duplicate_rank(item) > _near_duplicate_rank(kept[duplicate_index]):
            kept[duplicate_index] = item
    return kept


def _covered_by_overview(item: NewsItem, overview_points: list[str]) -> bool:
    if not overview_points:
        return False
    title_terms = _significant_terms(item.title)
    if not title_terms:
        return False
    overview_terms = _significant_terms(" ".join(overview_points))
    overlap = title_terms & overview_terms
    return len(overlap) >= 2 and len(overlap) / len(title_terms) >= 0.22


def _thread_theme_title(tag: str, lead: NewsItem) -> str:
    text = _haystack(lead)
    if tag == "安全治理":
        if any(term in text for term in ("hack", "breach", "入侵", "失控", "security")):
            return "安全治理：模型自主行动能力正在逼近真实系统风险"
        return "安全治理：模型能力扩张带来新的对齐与监管压力"
    if tag == "智能体":
        if any(term in text for term in ("gui", "browser", "computer", "移动", "网页")):
            return "智能体：通用界面操作能力成为产品化竞争焦点"
        if any(term in text for term in ("multi-agent", "多智能体", "orchestration")):
            return "智能体：多智能体协作从固定流程走向自适应编排"
        return "智能体：工具调用和任务规划继续向真实工作流推进"
    if tag == "评测":
        return "评测：新基准正在重新衡量模型记忆、推理与可靠性"
    if tag == "工程优化":
        return "工程优化：推理成本、延迟和缓存继续成为落地关键"
    if tag == "开源":
        return "开源：开放权重和开发工具继续压低实验门槛"
    if tag == "产业动态":
        if any(term in text for term in ("user", "用户", "融资", "funding")):
            return "产业动态：头部 AI 产品进入规模与资本双重竞速"
        return "产业动态：平台公司继续围绕模型能力重排产品线"
    if tag == "社区热议":
        return "社区热议：开发者讨论集中在工具体验和工程取舍"
    if tag == "论文":
        return "论文：模型架构与训练方法仍在快速迭代"
    return f"{tag}：{_short_title(lead.title)}"


def build_today_threads(
    items: list[NewsItem],
    limit: int = 4,
    *,
    overview_points: list[str] | None = None,
    thread_titles: dict[str, str] | None = None,
) -> list[dict]:
    """生成日报顶部的主线；模型标题缺失时回退到确定性的本地标题。"""
    overview_points = overview_points or []
    thread_titles = thread_titles or {}
    buckets: dict[str, list[NewsItem]] = defaultdict(list)
    for item in items:
        buckets[primary_topic(item)].append(item)

    candidates = []
    for tag, tagged in buckets.items():
        ranked = sorted(tagged, key=quality_sort_key, reverse=True)
        if len(ranked) < 2 and ranked[0].meta.get("quality_score", 0) < 60:
            continue
        lead = next(
            (item for item in ranked if not _covered_by_overview(item, overview_points)),
            None,
        )
        if lead is None:
            continue
        top = [lead] + [item for item in ranked if item.id != lead.id][:2]
        sources = "、".join(list(dict.fromkeys(item.source for item in top))[:3])
        candidates.append({
            "title": thread_titles.get(tag) or _thread_theme_title(tag, lead),
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
