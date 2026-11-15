"""Private per-edition selection logs and source-health summaries."""
import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path

from .models import NewsItem
from .renderer import write_json
from .utils import safe_http_url

log = logging.getLogger(__name__)
HEALTHY = {"ok", "empty", "stale"}
FAILED = {"failed", "partial", "undated", "invalid_credentials"}


def mark_dropped(before: list[NewsItem], after: list[NewsItem], reason: str) -> None:
    kept = {id(item) for item in after}
    for item in before:
        if id(item) not in kept:
            item.meta.setdefault("selection_stage", reason)


def _health_statuses(diagnostics: dict) -> dict[str, str]:
    statuses = {name: "failed" for name in diagnostics.get("failed_collectors", [])}
    statuses.update({
        name: "ok" for name, count in diagnostics.get("collector_counts", {}).items() if count
    })
    for collector, details in diagnostics.get("source_status", {}).items():
        if details.get("status"):
            statuses[collector] = details["status"]
        for group in ("feeds", "sites"):
            for name, entry in details.get(group, {}).items():
                statuses[f"{collector} / {name}"] = entry["status"]
    return {name: state for name, state in statuses.items() if state in HEALTHY | FAILED}


def _source_health(directory: Path, today: date, statuses: dict[str, str]) -> dict:
    """Use prior edition logs so reruns on the same date never double-count."""
    earlier = []
    for offset in range(1, 31):
        day = today - timedelta(days=offset)
        path = directory / f"{day}.json"
        if path.is_file():
            try:
                outcomes = json.loads(path.read_text(encoding="utf-8"))["source_outcomes"]
                if isinstance(outcomes, dict):
                    earlier.append((day, outcomes))
            except (OSError, ValueError, TypeError, KeyError):
                log.warning("无法读取来源记录 %s", path.name)
    health = {}
    for name, state in sorted(statuses.items()):
        streak = int(state in FAILED)
        if streak:
            for _, previous in earlier:
                if previous.get(name) not in FAILED:
                    break
                streak += 1
        last_success = today if state in HEALTHY else next(
            (day for day, previous in earlier if previous.get(name) in HEALTHY), None,
        )
        health[name] = {
            "status": state,
            "consecutive_failures": streak,
            "last_success": last_success.isoformat() if last_success else None,
        }
    return health


def _candidate_rows(items: list[NewsItem], selected: list[NewsItem], must_reads: list[NewsItem]):
    keys = {id(item): index for index, item in enumerate(items, 1)}
    shown = {id(item) for item in selected}
    featured = {id(item) for item in must_reads}
    for item in items:
        meta = item.meta
        merged = meta.get("merged_into")
        while merged in keys:
            target = items[keys[merged] - 1]
            next_target = target.meta.get("merged_into")
            if next_target not in keys:
                break
            merged = next_target
        yield {
            "candidate": keys[id(item)],
            "id": item.id,
            "title": item.title,
            "url": safe_http_url(item.url),
            "source": item.source,
            "section": item.section,
            "event_key": meta.get("event_key"),
            "merged_into": keys.get(merged),
            "raw_score": item.score,
            "engagement_percentile": meta.get("engagement_percentile"),
            "quality_score": meta.get("quality_score"),
            "quality_reasons": meta.get("quality_reasons", []),
            "importance": item.importance or None,
            "summary_status": meta.get("summary_status"),
            "follow_up_date": meta.get("follow_up_date"),
            "outcome": meta.get("selection_stage", "published" if id(item) in shown else "omitted"),
            "published": id(item) in shown,
            "must_read": id(item) in featured,
        }


def write_editorial_log(cfg: dict, today: date, diagnostics: dict, items: list[NewsItem],
                        selected: list[NewsItem], must_reads: list[NewsItem], *,
                        live: bool, success: bool) -> dict:
    root = Path(cfg["_root"])
    health_dir = root / "history" / "editorial"
    directory = health_dir if live else root / "logs" / "editorial"
    statuses = _health_statuses(diagnostics)
    health = _source_health(health_dir, today, statuses) if live else {}
    try:
        write_json(directory / f"{today}.json", {
            "report_date": today.isoformat(),
            "success": success,
            "source_outcomes": statuses,
            "source_health": health,
            "candidates": list(_candidate_rows(items, selected, must_reads)),
        })
    except OSError as exc:
        log.warning("无法写入选稿日志: %s", exc)
    warnings = [name for name, row in health.items() if row["consecutive_failures"] >= 3]
    if warnings:
        log.warning("连续至少 3 次采集异常：%s", "、".join(warnings))
        if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
            try:
                with Path(summary_path).open("a", encoding="utf-8") as handle:
                    handle.write("### 早报来源连续采集异常\n\n")
                    for name in warnings:
                        count = health[name]["consecutive_failures"]
                        label = name.replace("\n", " ").replace("\r", " ")
                        handle.write(f"- {label} · 连续 {count} 期\n")
            except OSError as exc:
                log.warning("无法写入 Actions 摘要: %s", exc)
    return health
