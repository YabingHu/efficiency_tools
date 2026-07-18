from datetime import date
from pathlib import Path

import pytest

from src.history import sync_history


def test_sync_history_keeps_31_days_and_builds_archive(cfg):
    root = Path(cfg["_root"])
    output_dir = root / "output"
    history_dir = root / "history"
    output_dir.mkdir()
    history_dir.mkdir()

    (output_dir / "2026-07-18.html").write_text("today", encoding="utf-8")
    (history_dir / "2026-06-18.html").write_text("cutoff", encoding="utf-8")
    (history_dir / "2026-06-17.html").write_text("expired", encoding="utf-8")
    (history_dir / "notes.html").write_text("leave me", encoding="utf-8")

    dates = sync_history(cfg, date(2026, 7, 18), retention_days=31)

    assert dates == ["2026-07-18", "2026-06-18"]
    assert (history_dir / "2026-07-18.html").read_text(encoding="utf-8") == "today"
    assert not (history_dir / "2026-06-17.html").exists()
    assert (history_dir / "notes.html").exists()
    assert (output_dir / "2026-06-18.html").read_text(encoding="utf-8") == "cutoff"
    archive = (output_dir / "archive.html").read_text(encoding="utf-8")
    assert 'href="2026-07-18.html"' in archive
    assert 'href="2026-06-18.html"' in archive
    assert "2026-06-17" not in archive


def test_sync_history_requires_generated_report(cfg):
    with pytest.raises(FileNotFoundError, match="generated report not found"):
        sync_history(cfg, date(2026, 7, 18))


def test_sync_history_rejects_invalid_retention(cfg):
    with pytest.raises(ValueError, match="at least 1"):
        sync_history(cfg, date(2026, 7, 18), retention_days=0)
