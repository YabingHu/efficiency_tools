import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src import main
from src.editorial import normalize_engagement
from src.events import annotate_event
from src.models import NewsItem
from src.run_diagnostics import write_editorial_log
from src.seen_ledger import SeenLedger


def article(title, url="https://example.com/models", *, official=True):
    return NewsItem(
        id=url, section="industry" if official else "media", title=title, url=url,
        source="官方" if official else "媒体",
        text="Detailed AI model evaluation and results. " * 8,
        meta={"first_party": official},
    )


def test_release_group_retains_official_source_and_distinct_versions(cfg):
    report = article(
        "Anthropic 发布 Claude Sonnet 4.5", "https://news.example.com/a", official=False,
    )
    same_section = article(
        "Claude 4.5 Sonnet 正式发布", "https://other.example.com/a", official=False,
    )
    same_section.source = "其他媒体"
    official = article("Introducing Claude Sonnet 4.5.")
    other_version = article("Introducing Claude Sonnet 4.6.", "https://example.com/other")

    result = main.collapse_cross_source(cfg, [report, same_section, official, other_version])

    assert result == [official, other_version]
    assert report.meta["selection_stage"] == "merged_event"
    assert {link["url"] for link in official.meta["related_sources"]} == {
        report.url, same_section.url,
    }


def test_joint_gpt_release_merges_media_and_official_post(cfg):
    report = article(
        "GPT-6.2 Astra和Sol王炸双发！3D又危了", "https://news.example.com/a", official=False,
    )
    official = article(
        "@OpenAI：Starting today, GPT-6.2 Astra and Sol are available in ChatGPT Work and Codex.",
        "https://x.com/OpenAI/status/2122750135608528984",
    )
    official.section = "community"
    separate = article("GPT-6.2 Sol API is now available", "https://example.com/sol-api")
    assert main.collapse_cross_source(cfg, [report, official, separate]) == [official, separate]
    assert official.meta["related_sources"] == [{"source": report.source, "url": report.url}]
    assert official.meta["event_key"] == "gpt 6.2 astra + gpt 6.2 sol"


def test_seven_day_release_replay_keeps_material_followups(tmp_path):
    ledger_path = tmp_path / "seen.json"
    start = date(2026, 11, 1)
    editions = [
        (article("OpenAI releases GPT-5.1"), True, []),
        (article("GPT-5.1 发布", "https://news.example.com/a", official=False), False, []),
        (article("OpenAI releases GPT-5.1"), False, []),
        (article("OpenAI releases GPT-5.1"), True, ["开放模型权重"]),
        (article("GPT-5.1 weights are now available"), False, []),
        (article("OpenAI releases GPT-5.2"), True, []),
        (article("GPT-5.2 API is now available"), True, ["开放 API 访问"]),
    ]
    editions[2][0].text = "GPT-5.1 weights are not now available."
    editions[3][0].text = "GPT-5.1 weights are now available."

    for offset, (candidate, should_publish, changes) in enumerate(editions):
        day = start + timedelta(days=offset)
        ledger = SeenLedger(ledger_path, 7)
        annotate_event(candidate)
        selected = ledger.filter_unseen([candidate], day)
        assert bool(selected) == should_publish, candidate.title
        assert [entry["label"] for entry in candidate.meta.get("follow_up_changes", [])] == changes
        if changes:
            prior = start if offset == 3 else day - timedelta(days=1)
            assert candidate.meta["follow_up_date"] == prior.isoformat()
        ledger.record(selected, day)
        ledger.save()


def test_platform_percentile_is_invariant_to_score_scale():
    scores = [("HN", 10), ("HN", 100), ("Reddit", 1000), ("Reddit", 9000)]
    items = [
        NewsItem(str(i), "community", "AI model", "https://example.com", source, score=score)
        for i, (source, score) in enumerate(scores)
    ]
    normalize_engagement(items)
    assert [item.meta["engagement_percentile"] for item in items] == [0.25, 0.75, 0.25, 0.75]


def test_source_health_counts_editions_and_resets_on_valid_empty(cfg, tmp_path, monkeypatch):
    summary = tmp_path / "step-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    start = date(2026, 11, 1)

    def write(day, state):
        diagnostics = {"source_status": {"rss": {"feeds": {"官方": {"status": state}}}}}
        return write_editorial_log(cfg, day, diagnostics, [], [], [], live=True, success=True)

    name = "rss / 官方"
    for offset, state in enumerate(("ok", "failed", "failed", "failed")):
        day = start + timedelta(days=offset)
        assert write(day, state)[name]["consecutive_failures"] == offset
    assert write(day, "failed")[name]["consecutive_failures"] == 3
    assert write(day, "failed")[name]["last_success"] == start.isoformat()
    assert "连续 3 期" in summary.read_text(encoding="utf-8")
    assert write(day + timedelta(days=1), "empty")[name]["consecutive_failures"] == 0


def test_main_logs_final_selection_and_renders_followup(monkeypatch, cfg):
    today = datetime.now(ZoneInfo(cfg["timezone"])).date()
    yesterday = today - timedelta(days=1)
    root = Path(cfg["_root"])
    previous = article("OpenAI releases GPT-5")
    annotate_event(previous)
    ledger = SeenLedger(root / "history" / "seen-items.json", 7)
    ledger.record([previous], yesterday)
    ledger.save()
    official = article("OpenAI releases GPT-5")
    official.text = "GPT-5 weights are now available. " + official.text
    report = article("GPT-5 权重已开放", "https://news.example.com/a", official=False)
    monkeypatch.setattr(main, "load_config", lambda: cfg)
    monkeypatch.setattr(main, "setup_logging", lambda *_: None)
    monkeypatch.setattr(main, "collect_all", lambda *_: ([report, official], {}))
    monkeypatch.setattr("sys.argv", ["digest", "--no-llm"])

    main.main()

    page = (root / cfg["output_dir"] / f"{today}.html").read_text(encoding="utf-8")
    assert "开放模型权重" in page
    assert f'href="{yesterday}.html"' in page
    assert report.url in page
    trace = json.loads((root / "logs" / "editorial" / f"{today}.json").read_text(encoding="utf-8"))
    assert [(row["merged_into"], row["published"]) for row in trace["candidates"]] == [
        (2, False), (None, True),
    ]
    assert not (root / cfg["output_dir"] / "editorial").exists()
