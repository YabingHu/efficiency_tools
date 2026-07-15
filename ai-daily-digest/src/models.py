"""统一的资讯条目数据结构。"""
from dataclasses import dataclass, field


@dataclass
class NewsItem:
    id: str            # 全局唯一（用于去重与摘要结果回填）
    section: str       # papers | arxiv | github | industry | community
    title: str
    url: str
    source: str        # 来源名，如 "HF Papers" / "OpenAI Blog"
    text: str = ""     # 原始摘要/描述，供大模型总结用
    score: float = 0.0 # 来源侧热度（点赞/star/points），用于排序参考
    summary_zh: str = ""
    comment: str = ""
    importance: int = 0  # 1-5，由大模型评估
    meta: dict = field(default_factory=dict)
