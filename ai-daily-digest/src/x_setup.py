"""安全保存 X 会话，或单独验证 X 采集（不调用 LLM）。"""
import argparse
import getpass
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .collectors.x_twscrape import COOKIE_FILE, collect, validate_cookies
from .config import load_config


def save_cookies(root: Path, cookies: dict) -> None:
    cookies = validate_cookies(cookies)
    private = root / ".private"
    private.mkdir(mode=0o700, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=private, prefix=".x-session-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(cookies, handle)
        Path(name).replace(private / COOKIE_FILE)
    finally:
        Path(name).unlink(missing_ok=True)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="配置免费的 X 采集登录会话")
    parser.add_argument("--check", action="store_true", help="只采集 X，不生成日报或调用 LLM")
    args = parser.parse_args()
    cfg = load_config()
    if args.check:
        today = datetime.now(ZoneInfo(cfg.get("timezone", "Asia/Shanghai"))).date()
        items = collect(cfg, today)
        print(json.dumps(cfg["_collector_status"]["x_twscrape"], ensure_ascii=False, indent=2))
        for item in items:
            print(f"{item.title}\n{item.url}")
        return 0 if cfg["_collector_status"]["x_twscrape"]["status"] in {"ok", "empty"} else 1
    if not sys.stdin.isatty():
        print("请在本地交互式终端运行；不要将登录信息放进命令参数。")
        return 1
    print("登录 x.com 后，打开 F12 → Application/应用 → Cookies → https://x.com。")
    print("分别复制 auth_token 和 ct0 的值。输入时不会显示；不需要账号密码。")
    try:
        cookies = {key: getpass.getpass(f"{key}: ").strip() for key in ("auth_token", "ct0")}
        save_cookies(Path(cfg["_root"]), cookies)
    except (ValueError, OSError):
        print("未能保存：请检查两个 Cookie 值及目录权限。")
        return 1
    print("已保存到被 Git 忽略的 .private/x-cookies.json。")
    print("运行 python -m src.x_setup --check 验证采集。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
