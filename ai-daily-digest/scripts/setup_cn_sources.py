"""安装隔离的中文作者采集环境，适用于 Windows 与 GitHub Actions。"""

import os
import shutil
import subprocess
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINS = {
    "mediacrawler-pilot": ("NanmiCoder/MediaCrawler", "8f583999006d5b692272c608440e193ca282e73b"),
    "newscrawler-pilot": ("NanmiCoder/NewsCrawler", "25fb3b4a20186905f5ce38f7a7f854050d402253"),
}


def run(*args):
    subprocess.run(args, cwd=ROOT, check=True)


def main():
    for folder, (repository, revision) in PINS.items():
        target = ROOT / ".external-skills" / folder
        if not target.exists():
            target.mkdir(parents=True)
            run("git", "-C", str(target), "init", "--quiet")
            run(
                "git",
                "-C",
                str(target),
                "remote",
                "add",
                "origin",
                f"https://github.com/{repository}.git",
            )
            run("git", "-C", str(target), "fetch", "--quiet", "--depth", "1", "origin", revision)
            run("git", "-C", str(target), "checkout", "--quiet", "--detach", "FETCH_HEAD")
        actual = subprocess.check_output(
            ["git", "-C", str(target), "rev-parse", "HEAD"], text=True
        ).strip()
        if actual != revision:
            raise RuntimeError("中文采集器版本不匹配")
    environment = ROOT / ".external-skills/cn-pilot-venv"
    if not environment.exists():
        venv.create(environment, with_pip=True)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    run(str(python), "-m", "pip", "install", "-r", "requirements-cn.txt")
    if os.name != "nt" and not shutil.which("google-chrome"):
        run(str(python), "-m", "playwright", "install", "--with-deps", "chrome")
    run(str(python), "-m", "src.cn_pilot", "doctor")


if __name__ == "__main__":
    main()
