# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

LLM 每日早报生成器 — a daily pipeline that scrapes AI/LLM news sources (HuggingFace Daily Papers, arXiv, GitHub Trending, company blog RSS, Hacker News), summarizes them in Chinese via an OpenAI-compatible LLM API, and renders an HTML morning report to `output/YYYY-MM-DD.html` (also copied to `output/latest.html`). All user-facing content, prompts, comments, and logs are in Chinese.

## Commands

Uses the local venv directly (no activation needed). Pytest and Ruff are configured in `pyproject.toml`.

```powershell
# Install runtime + development deps
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

# Health check, tests, lint
.venv\Scripts\python.exe -m src.main --check --no-llm
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check src tests

# Full run (needs LLM_API_KEY in .env — copy from .env.example)
.venv\Scripts\python.exe -m src.main

# Test collectors + rendering WITHOUT calling the LLM (no key needed) — preferred for development
.venv\Scripts\python.exe -m src.main --no-llm

# Generate for a specific date
.venv\Scripts\python.exe -m src.main --date 2026-07-10

# Register / remove the daily Windows scheduled task (08:00 default)
powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1 -Time 08:00
Unregister-ScheduledTask -TaskName LLM-Daily-Report -Confirm:$false
```

Logs: rotating `logs/run.log` (application). Machine-readable latest run status: `output/run-status.json`.

## Architecture

Pipeline in `src/main.py`, executed in five stages: collect → dedup → pre-trim → LLM summarize → render.

- **`src/models.py`** — `NewsItem` dataclass is the single data contract flowing through every stage. `id` must be globally unique: it drives cross-section dedup and is how LLM batch results are matched back to items. `section` must equal a key in `config.yaml`'s `sections`.
- **`src/collectors/`** — one module per source, each exposing `collect(cfg, today: date) -> list[NewsItem]`. `COLLECTORS` is keyed by source and declares every section it can populate, so shared RSS collection is independent from the `industry`/`media` toggles. Top-level sources, RSS feeds, and HN queries run concurrently. HF Papers and arXiv deliberately share the `arxiv:<id>` ID format so the same paper dedups across sections (the `papers` section wins).
- **`src/http_client.py`** — thread-local `requests.Session` instances with connection reuse, separate connect/read timeouts, and bounded GET retries.
- **`src/summarizer.py`** — batches items (`batch_size` per LLM call), keeps external content in an untrusted-data user message, validates every returned ID/field, and falls back per item to source text. Also generates the 3–5 bullet "今日要点" overview.
- **`src/renderer.py`** — Jinja2 (`src/templates/report.html.j2`) with explicit autoescape, atomic writes, current-day-only `latest.html`, and atomic `run-status.json`.
- **`src/config.py`** — merges `config.yaml` + `.env`, validates sections/URLs/limits/timeouts/output path, and injects the project root as `cfg["_root"]`.

### Adding a new source

1. New module in `src/collectors/` implementing `collect(cfg, today)`; give items a unique `id` prefix and set `score` if the source has a popularity signal (used for ranking).
2. Register it in `COLLECTORS` in `src/main.py` with the set of sections it can populate.
3. Add the relevant `sections` (title/limit) and `sources` fetch parameters in `config.yaml`.

### Conventions & gotchas

- Ranking convention: items with `score` are sorted by it during pre-trim; scoreless sources (arXiv) rely on collection order (newest first). Final display order is `(importance, score)`.
- `text` fed to the LLM is truncated (~800–1500 chars) to control token spend; pre-trim caps each section at `limit*2` items before summarization.
- Windows encoding: stdout is reconfigured to UTF-8 in `setup_logging` (console defaults to GBK and garbles Chinese); always pass `encoding="utf-8"` when opening files.
- Every historical-capable collector uses the requested report date as its upper bound. GitHub Trending has no historical endpoint and is intentionally skipped for historical reports.
- arXiv/RSS may anchor a short weekend lookback to the newest entry at or before the report date, but sources older than `max_staleness_hours` are rejected.
- Only a current-day report updates `latest.html`; backfills never overwrite it.
- Timezone comes from `config.yaml` (`Asia/Shanghai`) via `zoneinfo` — don't use naive `datetime.now()` for report dating.
