"""大模型每日早报生成器 — 流水线入口。

用法:
    python -m src.main             # 完整流程（需要 .env 中的 LLM_API_KEY）
    python -m src.main --no-llm    # 跳过大模型摘要，仅测试抓取和渲染
    python -m src.main --date 2026-07-10
"""
import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo

from .collectors import (
    arxiv_papers,
    community_sources,
    github_trending,
    hackernews,
    hf_papers,
    last30days_sources,
    rss_news,
)
from .config import get_api_key, load_config
from .renderer import check_template, render, write_status
from .summarizer import Summarizer
from .utils import canonical_url, safe_http_url, take_with_source_limit

COLLECTORS = {
    "hf_papers": (hf_papers.collect, {"papers"}),
    "arxiv": (arxiv_papers.collect, {"arxiv"}),
    "github": (github_trending.collect, {"github"}),
    "rss": (rss_news.collect, {"industry", "media"}),
    "hackernews": (hackernews.collect, {"community"}),
    "community_sources": (community_sources.collect, {"community"}),
    "last30days": (last30days_sources.collect, {"community", "community_cn"}),
}


def setup_logging(root: Path):
    # Windows 控制台默认 GBK，中文日志会乱码
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    log_dir = root / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            RotatingFileHandler(
                log_dir / "run.log", maxBytes=5 * 1024 * 1024,
                backupCount=5, encoding="utf-8",
            ),
        ],
        force=True,
    )


def collect_all(cfg: dict, report_date) -> list:
    """并发执行独立数据源，并按注册顺序稳定合并结果。"""
    log = logging.getLogger("main")
    enabled = {
        key for key, section in cfg["sections"].items()
        if section.get("enabled", True)
    }
    selected = {
        name: collect
        for name, (collect, sections) in COLLECTORS.items()
        if sections & enabled
    }
    results = {}
    workers = min(cfg.get("collection_workers", 5), max(1, len(selected)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="collector") as pool:
        futures = {
            pool.submit(collect, cfg, report_date): (name, perf_counter())
            for name, collect in selected.items()
        }
        for future in as_completed(futures):
            name, started = futures[future]
            try:
                got = future.result()
                results[name] = got
                log.info("[%s] 采集到 %d 条", name, len(got))
            except Exception:
                results[name] = []
                log.exception("[%s] 采集器异常，跳过", name)
            finally:
                log.info("[%s] 采集耗时 %.2fs", name, perf_counter() - started)

    return [item for name in selected for item in results.get(name, [])]


def deduplicate(items: list, enabled_sections: set[str]) -> list:
    """过滤禁用板块/危险 URL，并按 ID 与规范化 URL 去重。"""
    seen, deduped = set(), []
    for item in sorted(items, key=lambda value: 0 if value.section == "papers" else 1):
        if item.section not in enabled_sections:
            continue
        safe_url = safe_http_url(item.url)
        if safe_url is None:
            logging.getLogger("main").warning("跳过非 HTTP(S) 链接: %s", item.url)
            continue
        item.url = safe_url
        url_key = canonical_url(safe_url)
        if item.id in seen or url_key in seen:
            continue
        seen.add(item.id)
        seen.add(url_key)
        deduped.append(item)
    return deduped


def trim_items(cfg: dict, items: list) -> list:
    """按板块限制进入 LLM 的条目数，禁用板块不产生调用成本。"""
    trimmed = []
    for key, sec_cfg in cfg["sections"].items():
        if not sec_cfg.get("enabled", True):
            continue
        section_items = [item for item in items if item.section == key]
        cap = sec_cfg.get("limit", 8) * 2
        if any(item.score for item in section_items):
            section_items.sort(key=lambda item: item.score, reverse=True)
        max_per_source = sec_cfg.get("max_per_source")
        if max_per_source:
            section_items = take_with_source_limit(
                section_items, cap, max_per_source * 2,
            )
        trimmed.extend(section_items[:cap])
    return trimmed


def apply_no_llm_fallback(items: list) -> None:
    for item in items:
        text = " ".join(item.text.split())
        item.summary_zh = text if len(text) <= 360 else text[:359].rstrip() + "…"
        item.importance = 3


def run_checks(cfg: dict, require_api_key: bool) -> None:
    """验证配置、模板和可选的 LLM 凭据，不执行网络请求。"""
    check_template()
    if require_api_key:
        get_api_key()
    root = Path(cfg["_root"])
    if not root.is_dir():
        raise RuntimeError(f"项目目录不存在: {root}")


def main():
    parser = argparse.ArgumentParser(description="LLM 每日早报生成器")
    parser.add_argument("--no-llm", action="store_true",
                        help="跳过大模型摘要（测试抓取和渲染用）")
    parser.add_argument("--date", help="指定报告日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--check", action="store_true",
                        help="只检查配置、模板与凭据，不访问网络")
    args = parser.parse_args()

    cfg = load_config()
    root = Path(cfg["_root"])
    setup_logging(root)
    log = logging.getLogger("main")

    if args.check:
        run_checks(cfg, require_api_key=not args.no_llm)
        print("健康检查通过")
        return

    tz = ZoneInfo(cfg.get("timezone", "Asia/Shanghai"))
    if args.date:
        try:
            report_date = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=tz)
        except ValueError as exc:
            parser.error(f"--date 必须是有效的 YYYY-MM-DD: {exc}")
    else:
        report_date = datetime.now(tz)
    log.info("===== 开始生成 %s 早报 =====", report_date.strftime("%Y-%m-%d"))

    # 1. 抓取（单源失败不影响整体）
    pipeline_started = perf_counter()
    items = collect_all(cfg, report_date.date())

    if not items:
        log.error("所有来源均无数据，退出")
        write_status(
            cfg,
            {
                "status": "failed",
                "report_date": report_date.strftime("%Y-%m-%d"),
                "reason": "所有来源均无数据",
                "duration_seconds": round(perf_counter() - pipeline_started, 2),
            },
        )
        sys.exit(1)

    # 2. 跨板块去重（HF Papers 与 arXiv 共享 arxiv:<id>，优先保留 papers 板块）
    enabled_sections = {
        key for key, section in cfg["sections"].items()
        if section.get("enabled", True)
    }
    deduped = deduplicate(items, enabled_sections)
    log.info("去重后共 %d 条（原 %d 条）", len(deduped), len(items))

    # 3. 摘要前预裁剪：每板块最多保留 limit*2 条，控制 token 消耗
    #    （有热度分的按分数取头部；arXiv 等无分数的保持采集顺序=时间倒序）
    deduped = trim_items(cfg, deduped)
    log.info("预裁剪后送入摘要 %d 条", len(deduped))

    # 4. 大模型摘要 + 今日要点
    overview = []
    if args.no_llm:
        log.info("--no-llm：跳过摘要，条目以原文展示")
        apply_no_llm_fallback(deduped)
    else:
        summarizer = Summarizer(cfg)
        summarizer.summarize_items(deduped)
        overview = summarizer.make_overview(deduped)

    # 5. 渲染输出
    update_latest = report_date.date() == datetime.now(tz).date()
    out_path = render(
        cfg, deduped, overview, report_date, update_latest=update_latest,
    )
    duration = round(perf_counter() - pipeline_started, 2)
    write_status(
        cfg,
        {
            "status": "success",
            "report_date": report_date.strftime("%Y-%m-%d"),
            "output": str(out_path),
            "latest_updated": update_latest,
            "no_llm": args.no_llm,
            "collected_items": len(items),
            "render_candidates": len(deduped),
            "section_counts": {
                key: sum(item.section == key for item in deduped)
                for key in cfg["sections"]
            },
            "duration_seconds": duration,
        },
    )
    log.info("===== 完成: %s =====", out_path)
    log.info("流水线总耗时 %.2fs", duration)
    print(f"\n早报已生成: {out_path}")


if __name__ == "__main__":
    main()
