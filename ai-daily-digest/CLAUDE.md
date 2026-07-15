# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

LLM 每日早报生成器 — a daily pipeline that scrapes AI/LLM news sources (HuggingFace Daily Papers, arXiv, GitHub Trending, company blog RSS, Hacker News), summarizes them in Chinese via an OpenAI-compatible LLM API, and renders an HTML morning report to `output/YYYY-MM-DD.html` (also copied to `output/latest.html`). All user-facing content, prompts, comments, and logs are in Chinese.

## Commands

Uses the local venv directly (no activation needed). There are no tests or linters.

```powershell
# Install deps
.venv\Scripts\python.exe -m pip install -r requirements.txt

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

Logs: `logs/run.log` (application), `logs/task.log` (scheduled-task stdout).

## Architecture

Pipeline in `src/main.py`, executed in five stages: collect → dedup → pre-trim → LLM summarize → render.

- **`src/models.py`** — `NewsItem` dataclass is the single data contract flowing through every stage. `id` must be globally unique: it drives cross-section dedup and is how LLM batch results are matched back to items. `section` must equal a key in `config.yaml`'s `sections`.
- **`src/collectors/`** — one module per source, each exposing `collect(cfg, today: date) -> list[NewsItem]`. Registered in the `COLLECTORS` dict in `main.py`, keyed by section name. Collectors catch their own network errors and return `[]`/partial results; `main.py` additionally wraps each call so one failing source never kills the run. HF Papers and arXiv deliberately share the `arxiv:<id>` id format so the same paper dedups across sections (the `papers` section wins).
- **`src/summarizer.py`** — batches items (`batch_size` per LLM call), prompts demand a strict JSON array, `_extract_json` tolerantly strips markdown fences. On failure a batch degrades to showing raw source text (`importance=3`) rather than aborting. Also generates the 3–5 bullet "今日要点" overview from the top-ranked items.
- **`src/renderer.py`** — Jinja2 (`src/templates/report.html.j2`), sorts each section by `(importance, score)` and truncates to the section's `limit`.
- **`src/config.py`** — merges `config.yaml` + `.env` (`LLM_API_KEY` only); injects the project root as `cfg["_root"]`.

### Adding a new source

1. New module in `src/collectors/` implementing `collect(cfg, today)`; give items a unique `id` prefix and set `score` if the source has a popularity signal (used for ranking).
2. Register it in `COLLECTORS` in `src/main.py`.
3. Add a matching key under both `sections` (title/limit) and `sources` (fetch params) in `config.yaml`.

### Conventions & gotchas

- Ranking convention: items with `score` are sorted by it during pre-trim; scoreless sources (arXiv) rely on collection order (newest first). Final display order is `(importance, score)`.
- `text` fed to the LLM is truncated (~800–1500 chars) to control token spend; pre-trim caps each section at `limit*2` items before summarization.
- Windows encoding: stdout is reconfigured to UTF-8 in `setup_logging` (console defaults to GBK and garbles Chinese); always pass `encoding="utf-8"` when opening files.
- arXiv publishes nothing on weekends/holidays, so its lookback window anchors to the newest entry in the feed, not to "now".
- Timezone comes from `config.yaml` (`Asia/Shanghai`) via `zoneinfo` — don't use naive `datetime.now()` for report dating.
