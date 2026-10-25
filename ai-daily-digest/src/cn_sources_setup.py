"""中文作者采集健康检查，以及本机会话的定向导出。"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
from pathlib import Path


async def export_state():
    from .cn_pilot import PRIVATE, browser

    states = {}
    for platform, domains in {
        "weibo": {"weibo.cn", "weibo.com"},
        "zhihu": {"zhihu.com"},
    }.items():
        manager, context = await browser(platform, headless=True)
        try:
            state = await context.storage_state()
            states[platform] = {
                "cookies": [
                    c
                    for c in state["cookies"]
                    if any(
                        c["domain"].lstrip(".") == d or c["domain"].lstrip(".").endswith("." + d)
                        for d in domains
                    )
                ],
                "origins": [],
            }
        finally:
            await context.close()
            await manager.stop()
    target = PRIVATE / "cloud-state.b64"
    target.write_text(base64.b64encode(json.dumps(states).encode()).decode(), encoding="ascii")
    print(json.dumps({"status": "exported", "platforms": list(states)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-state", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.export_state:
        asyncio.run(export_state())
        return
    if not args.check:
        parser.error("请选择 --check 或 --export-state")
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from .collectors.cn_authors import collect
    from .config import load_config

    cfg = load_config()
    items = collect(cfg, datetime.now(ZoneInfo(cfg.get("timezone", "Asia/Shanghai"))).date())
    diagnostic = cfg.get("_collector_status", {}).get("cn_authors", {})
    print(json.dumps({"items": len(items), **diagnostic}, ensure_ascii=False))
    target = Path(cfg["_root"], ".private/cn-pilot/integration-status.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
    if diagnostic.get("status") in {"failed", "partial"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
