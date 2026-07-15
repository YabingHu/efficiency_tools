"""大模型每日早报生成器 — 流水线入口。

用法:
    python -m src.main             # 完整流程（需要 .env 中的 LLM_API_KEY）
    python -m src.main --no-llm    # 跳过大模型摘要，仅测试抓取和渲染
    python -m src.main --date 2026-07-10
"""
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .collectors import arxiv_papers, github_trending, hackernews, hf_papers, rss_news
from .config import load_config
from .renderer import render
from .summarizer import Summarizer

COLLECTORS = {
    "papers": hf_papers.collect,
    "arxiv": arxiv_papers.collect,
    "github": github_trending.collect,
    "industry": rss_news.collect,
    "community": hackernews.collect,
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
            logging.FileHandler(log_dir / "run.log", encoding="utf-8"),
        ],
    )


def main():
    parser = argparse.ArgumentParser(description="LLM 每日早报生成器")
    parser.add_argument("--no-llm", action="store_true",
                        help="跳过大模型摘要（测试抓取和渲染用）")
    parser.add_argument("--date", help="指定报告日期 YYYY-MM-DD，默认今天")
    args = parser.parse_args()

    cfg = load_config()
    root = Path(cfg["_root"])
    setup_logging(root)
    log = logging.getLogger("main")

    tz = ZoneInfo(cfg.get("timezone", "Asia/Shanghai"))
    report_date = (datetime.strptime(args.date, "%Y-%m-%d")
                   if args.date else datetime.now(tz))
    log.info("===== 开始生成 %s 早报 =====", report_date.strftime("%Y-%m-%d"))

    # 1. 抓取（单源失败不影响整体）
    items = []
    for key, collect in COLLECTORS.items():
        if not cfg["sections"].get(key, {}).get("enabled", True):
            continue
        try:
            got = collect(cfg, report_date.date())
            items.extend(got)
            log.info("[%s] 采集到 %d 条", key, len(got))
        except Exception:
            log.exception("[%s] 采集器异常，跳过", key)

    if not items:
        log.error("所有来源均无数据，退出")
        sys.exit(1)

    # 2. 跨板块去重（HF Papers 与 arXiv 共享 arxiv:<id>，优先保留 papers 板块）
    seen, deduped = set(), []
    for it in sorted(items, key=lambda x: 0 if x.section == "papers" else 1):
        key = it.id
        if key in seen or it.url in seen:
            continue
        seen.add(key)
        seen.add(it.url)
        deduped.append(it)
    log.info("去重后共 %d 条（原 %d 条）", len(deduped), len(items))

    # 3. 摘要前预裁剪：每板块最多保留 limit*2 条，控制 token 消耗
    #    （有热度分的按分数取头部；arXiv 等无分数的保持采集顺序=时间倒序）
    trimmed = []
    for key, sec_cfg in cfg["sections"].items():
        sec_items = [it for it in deduped if it.section == key]
        cap = sec_cfg.get("limit", 8) * 2
        if any(it.score for it in sec_items):
            sec_items.sort(key=lambda x: x.score, reverse=True)
        trimmed.extend(sec_items[:cap])
    deduped = trimmed
    log.info("预裁剪后送入摘要 %d 条", len(deduped))

    # 4. 大模型摘要 + 今日要点
    overview = []
    if args.no_llm:
        log.info("--no-llm：跳过摘要，条目以原文展示")
        for it in deduped:
            it.importance = 3
    else:
        summarizer = Summarizer(cfg)
        summarizer.summarize_items(deduped)
        overview = summarizer.make_overview(deduped)

    # 5. 渲染输出
    out_path = render(cfg, deduped, overview, report_date)
    log.info("===== 完成: %s =====", out_path)
    print(f"\n早报已生成: {out_path}")


if __name__ == "__main__":
    main()
