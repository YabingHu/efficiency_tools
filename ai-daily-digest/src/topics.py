"""论文专题分流：把命中主题关键词的 arXiv 论文归入专属板块。

通用机制，不硬编码具体主题——主题在 config.yaml 的 paper_topics 里声明，
加新主题（agent / RAG / 多模态…）只改配置。分流只作用于 arxiv 板的论文，
HF「今日论文精选」（papers 板）保持不动：已上社区高赞榜的论文留在精选里。

一篇论文只属于一个板块（NewsItem.section 是单值，也是跨板去重的依据），所以
命中专题的论文是「移入」专题板，而不是同时出现在两个板，与现有去重逻辑一致。

关键词只匹配**标题**，不匹配摘要：几乎每篇 arXiv 摘要都会写「在 XX benchmark 上
评测」，按摘要匹配会把半数论文误判成测评论文；而真正以测评为贡献的论文，标题里
基本都会点明（"XBench: A Benchmark for..."）。标题匹配精度远高于摘要匹配。
"""
from __future__ import annotations

import logging

from .models import NewsItem

log = logging.getLogger(__name__)

# 只对这些板的论文做专题分流；HF 精选板（papers）保持原样。
ROUTABLE_SECTIONS = {"arxiv"}


def paper_topic_rules(cfg: dict) -> list[tuple[str, list[str]]]:
    """返回 [(板块 key, 小写关键词列表), ...]，保持配置顺序（首个命中胜出）。"""
    rules = []
    for rule in cfg.get("paper_topics", []) or []:
        section = rule.get("section")
        keywords = [k.lower() for k in rule.get("keywords", []) if isinstance(k, str)]
        if section and keywords:
            rules.append((section, keywords))
    return rules


def paper_topic_sections(cfg: dict) -> set[str]:
    return {section for section, _ in paper_topic_rules(cfg)}


def merge_collection_keywords(base_keywords: list[str], cfg: dict) -> list[str]:
    """采集端放宽到 全局关键词 ∪ 所有专题关键词，否则只含专题词的论文进不来。"""
    merged, seen = [], set()
    for keyword in [k.lower() for k in base_keywords] + [
        keyword for _, keywords in paper_topic_rules(cfg) for keyword in keywords
    ]:
        if keyword not in seen:
            merged.append(keyword)
            seen.add(keyword)
    return merged


def route_paper_topics(cfg: dict, items: list[NewsItem]) -> None:
    """就地把 arxiv 板中命中专题的论文改归专题板；仅路由到已启用的专题板。"""
    rules = paper_topic_rules(cfg)
    if not rules:
        return
    enabled = {
        key for key, section in cfg["sections"].items()
        if section.get("enabled", True)
    }
    active = [(section, keywords) for section, keywords in rules if section in enabled]
    if not active:
        return

    counts: dict[str, int] = {}
    for item in items:
        if item.section not in ROUTABLE_SECTIONS:
            continue
        title = item.title.lower()
        for section, keywords in active:
            if any(keyword in title for keyword in keywords):
                item.section = section
                counts[section] = counts.get(section, 0) + 1
                break
    for section, count in counts.items():
        log.info("论文专题分流：%d 篇归入 [%s]", count, section)
