"""Persist and publish a rolling window of generated daily reports."""
from __future__ import annotations

import argparse
import logging
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import load_config
from .renderer import render_archive

log = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 31


def _report_date(path: Path) -> date | None:
    try:
        return date.fromisoformat(path.stem)
    except ValueError:
        return None


def sync_history(
    cfg: dict,
    report_date: date,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> list[str]:
    """Save today's report, prune old reports, and prepare the Pages artifact."""
    if retention_days < 1:
        raise ValueError("retention_days must be at least 1")

    root = Path(cfg["_root"])
    output_dir = root / cfg.get("output_dir", "output")
    history_dir = root / "history"
    report_name = f"{report_date.isoformat()}.html"
    source = output_dir / report_name
    if not source.is_file():
        raise FileNotFoundError(f"generated report not found: {source}")

    history_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, history_dir / report_name)

    cutoff = report_date - timedelta(days=retention_days - 1)
    retained: list[tuple[date, Path]] = []
    for path in history_dir.glob("*.html"):
        parsed_date = _report_date(path)
        if parsed_date is None:
            continue
        if parsed_date < cutoff:
            path.unlink()
            log.info("已清理过期日报 %s", path.name)
            continue
        retained.append((parsed_date, path))

    retained.sort(key=lambda entry: entry[0], reverse=True)
    for _, path in retained:
        shutil.copyfile(path, output_dir / path.name)

    report_dates = [item_date.isoformat() for item_date, _ in retained]
    render_archive(cfg, report_dates, retention_days=retention_days)
    log.info("已准备最近 %d 天归档，共 %d 份", retention_days, len(report_dates))
    return report_dates


def main() -> None:
    parser = argparse.ArgumentParser(description="更新云端日报历史归档")
    parser.add_argument("--date", help="报告日期，格式 YYYY-MM-DD；默认使用配置时区当天")
    parser.add_argument("--retention-days", type=int, default=DEFAULT_RETENTION_DAYS)
    args = parser.parse_args()

    cfg = load_config()
    if args.date:
        report_date = date.fromisoformat(args.date)
    else:
        report_date = datetime.now(ZoneInfo(cfg.get("timezone", "Asia/Shanghai"))).date()
    sync_history(cfg, report_date, retention_days=args.retention_days)


if __name__ == "__main__":
    main()
