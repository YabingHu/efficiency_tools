from datetime import date

from src import main
from src.models import NewsItem
from src.topics import (
    merge_collection_keywords,
    paper_topic_sections,
    route_paper_topics,
)


def paper(item_id, title, text="", section="arxiv"):
    return NewsItem(
        id=item_id, section=section, title=title, url=f"https://arxiv.org/abs/{item_id}",
        source="arXiv", text=text,
    )


def topic_cfg(**overrides):
    cfg = {
        "sections": {
            "papers": {"enabled": True, "title": "p"},
            "arxiv": {"enabled": True, "title": "a"},
            "eval": {"enabled": True, "title": "e"},
            "agent": {"enabled": True, "title": "g"},
        },
        "paper_topics": [
            {"section": "eval", "keywords": ["benchmark", "leaderboard"]},
            {"section": "agent", "keywords": ["agent", "tool use"]},
        ],
    }
    cfg.update(overrides)
    return cfg


def test_routes_matching_arxiv_paper_into_topic_board():
    cfg = topic_cfg()
    items = [
        paper("1", "A new benchmark for reasoning"),
        paper("2", "Scaling laws of pretraining"),
    ]
    route_paper_topics(cfg, items)
    assert items[0].section == "eval"      # 命中 benchmark
    assert items[1].section == "arxiv"     # 未命中，留在通用板


def test_matches_title_only_not_abstract():
    """摘要里提到 benchmark/leaderboard 太常见；只按标题判定，避免误伤方法类论文。"""
    cfg = topic_cfg()
    # 关键词只在摘要出现 -> 不归入专题板
    abstract_only = paper(
        "1", "Scaling laws of pretraining",
        text="We report results on the leaderboard and a benchmark suite.",
    )
    route_paper_topics(cfg, [abstract_only])
    assert abstract_only.section == "arxiv"
    # 关键词在标题出现 -> 归入专题板
    in_title = paper("2", "A leaderboard for code generation")
    route_paper_topics(cfg, [in_title])
    assert in_title.section == "eval"


def test_first_matching_topic_wins():
    cfg = topic_cfg()
    # 同时含 benchmark 和 agent，配置里 eval 在前，应归 eval
    item = paper("1", "A benchmark for LLM agent tool use")
    route_paper_topics(cfg, [item])
    assert item.section == "eval"


def test_hf_papers_are_never_rerouted():
    cfg = topic_cfg()
    item = paper("1", "A benchmark suite", section="papers")
    route_paper_topics(cfg, [item])
    assert item.section == "papers"


def test_disabled_topic_section_leaves_paper_in_arxiv():
    cfg = topic_cfg()
    cfg["sections"]["eval"]["enabled"] = False
    item = paper("1", "A benchmark for reasoning")
    route_paper_topics(cfg, [item])
    assert item.section == "arxiv"


def test_merge_collection_keywords_unions_without_duplicates():
    cfg = topic_cfg()
    merged = merge_collection_keywords(["LLM", "benchmark"], cfg)
    # 全局在前、专题在后，大小写归一，去重
    assert merged[:2] == ["llm", "benchmark"]
    assert merged.count("benchmark") == 1
    assert "leaderboard" in merged
    assert "tool use" in merged


def test_paper_topic_sections_lists_configured_boards():
    assert paper_topic_sections(topic_cfg()) == {"eval", "agent"}


def test_arxiv_collector_runs_when_only_topic_board_enabled(monkeypatch):
    cfg = topic_cfg()
    for key, section in cfg["sections"].items():
        section["enabled"] = key == "eval"   # 通用 arxiv 板关闭，仅开 eval 专题板

    ran = {}

    def fake_arxiv(_cfg, _today):
        ran["called"] = True
        return [paper("1", "A benchmark for reasoning")]

    monkeypatch.setattr(main, "COLLECTORS", {"arxiv": (fake_arxiv, {"arxiv"})})
    items, _ = main.collect_all(cfg, date(2026, 7, 20))
    assert ran.get("called") is True
    assert [item.id for item in items] == ["1"]
