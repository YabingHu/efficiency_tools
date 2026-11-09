from __future__ import annotations

import json
import os
import platform
import socket
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional


def default_config_path() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "NoteSync" / "config.json"


@dataclass
class AppConfig:
    notes_dir: str = ""
    remote_url: str = ""
    branch: str = "main"
    device_name: str = socket.gethostname().split(".")[0] or "device"
    remote_poll_seconds: int = 30
    debounce_seconds: int = 4
    periodic_notes_dir: str = "周期笔记"

    def validate(self) -> None:
        if not self.notes_dir.strip():
            raise ValueError("请选择本地笔记目录")
        if not self.remote_url.strip():
            raise ValueError("请填写 GitHub 仓库地址")
        if not self.branch.strip():
            raise ValueError("分支名不能为空")
        if self.remote_poll_seconds < 5:
            raise ValueError("远端检查间隔不能少于 5 秒")
        if self.debounce_seconds < 1:
            raise ValueError("自动提交延迟不能少于 1 秒")
        from .periodic_notes import validate_relative_folder

        validate_relative_folder(self.periodic_notes_dir)

    def save(self, path: Optional[Path] = None) -> Path:
        destination = path or default_config_path()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(destination)
        return destination

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AppConfig":
        source = path or default_config_path()
        if not source.exists():
            return cls()
        raw: Dict[str, Any] = json.loads(source.read_text(encoding="utf-8"))
        known = {key: raw[key] for key in cls.__dataclass_fields__ if key in raw}
        return cls(**known)
