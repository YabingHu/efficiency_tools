from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Sequence

from .config import AppConfig
from .git_sync import GitRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NoteSync GitHub notes synchronizer")
    parser.add_argument("--once", action="store_true", help="同步一次后退出")
    parser.add_argument("--folder", help="本地笔记目录")
    parser.add_argument("--remote", help="GitHub 仓库 SSH/HTTPS 地址")
    parser.add_argument("--branch", default=None, help="Git 分支，默认 main")
    parser.add_argument("--device", default=None, help="当前设备名称")
    parser.add_argument("--native", action="store_true", help="使用备用原生 Tk 界面")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.once:
        if args.native:
            from .app import run_app

            run_app()
        else:
            from .web_app import run_web_app

            run_web_app()
        return 0

    config = AppConfig.load()
    if args.folder:
        config.notes_dir = args.folder
    if args.remote:
        config.remote_url = args.remote
    if args.branch:
        config.branch = args.branch
    if args.device:
        config.device_name = args.device
    config.validate()

    repository = GitRepository(
        Path(config.notes_dir),
        config.remote_url,
        config.branch,
        config.device_name,
        logger=print,
    )
    report = repository.sync()
    print(report.summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
