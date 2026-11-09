from __future__ import annotations

import json
import os
import platform
import secrets
import subprocess
import threading
import webbrowser
from collections import deque
from dataclasses import asdict
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Deque, Dict, Optional

from .config import AppConfig
from .engine import BackgroundSync, SyncEvent, SyncState
from .periodic_notes import NoteKind, create_periodic_note


class AppController:
    def __init__(
        self,
        config_path: Optional[Path] = None,
        open_created_files: bool = True,
    ) -> None:
        self.config_path = config_path
        self.open_created_files = open_created_files
        self.config = AppConfig.load(config_path)
        self.engine: Optional[BackgroundSync] = None
        self.state = SyncState.STOPPED
        self.status_message = "同步尚未启动"
        self.logs: Deque[Dict[str, Any]] = deque(maxlen=200)
        self.sequence = 0
        self._lock = threading.Lock()
        self._add_log("NoteSync 已就绪。你可以先创建笔记，也可以配置 GitHub 自动同步。")

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "state": self.state.value,
                "message": self.status_message,
                "sequence": self.sequence,
                "logs": list(self.logs),
                "running": bool(self.engine and self.engine.running),
            }

    def config_payload(self) -> Dict[str, Any]:
        return asdict(self.config)

    def start_sync(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        config = self._config_from_payload(payload)
        config.validate()
        config.save(self.config_path)
        self.stop_sync(quiet=True)
        self.config = config
        self.engine = BackgroundSync(config, self._on_sync_event)
        self.engine.start()
        self._add_log("配置已保存，后台同步已启动。")
        return self.config_payload()

    def request_sync(self) -> None:
        if not self.engine or not self.engine.running:
            raise ValueError("请先保存配置并启动后台同步")
        self.engine.request_sync()

    def stop_sync(self, quiet: bool = False) -> None:
        engine = self.engine
        self.engine = None
        if engine:
            engine.stop()
        elif not quiet:
            self._on_sync_event(SyncEvent(SyncState.STOPPED, "同步已停止"))

    def create_note(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        folder = str(payload.get("notes_dir", "")).strip()
        if not folder:
            raise ValueError("请先设置笔记目录")
        try:
            kind = NoteKind(str(payload.get("kind", "")))
        except ValueError as error:
            raise ValueError("请选择每日、周度或月度笔记") from error
        try:
            target = date.fromisoformat(str(payload.get("date", "")))
        except ValueError as error:
            raise ValueError("日期格式不正确，请使用 YYYY-MM-DD") from error

        vault = Path(folder).expanduser()
        vault.mkdir(parents=True, exist_ok=True)
        base_folder = str(payload.get("periodic_notes_dir", "周期笔记"))
        result = create_periodic_note(vault, kind, target, base_folder)

        self.config.notes_dir = str(vault.resolve())
        self.config.periodic_notes_dir = base_folder.strip()
        self.config.save(self.config_path)
        relative = result.path.relative_to(vault.resolve()).as_posix()
        if result.created:
            self._add_log(f"已创建{kind.label}：{relative}")
        else:
            self._add_log(f"笔记已存在，未覆盖：{relative}")
        if self.engine and self.engine.running:
            self.engine.request_sync()
        if self.open_created_files:
            self.open_path(result.path)
        return {
            "created": result.created,
            "path": str(result.path),
            "relative_path": relative,
            "label": kind.label,
        }

    def open_notes_folder(self, payload: Dict[str, Any]) -> None:
        folder = str(payload.get("notes_dir", self.config.notes_dir)).strip()
        if not folder:
            raise ValueError("请先设置笔记目录")
        path = Path(folder).expanduser()
        if not path.exists():
            raise ValueError("笔记目录不存在")
        self.open_path(path)

    @staticmethod
    def open_path(path: Path) -> None:
        system = platform.system()
        if system == "Darwin":
            subprocess.Popen(["open", str(path)])
        elif system == "Windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def _config_from_payload(self, payload: Dict[str, Any]) -> AppConfig:
        try:
            poll = int(payload.get("remote_poll_seconds", 30))
            debounce = int(payload.get("debounce_seconds", 4))
        except (TypeError, ValueError) as error:
            raise ValueError("同步间隔必须是整数") from error
        return AppConfig(
            notes_dir=str(payload.get("notes_dir", "")).strip(),
            remote_url=str(payload.get("remote_url", "")).strip(),
            branch=str(payload.get("branch", "main")).strip(),
            device_name=str(payload.get("device_name", "device")).strip(),
            remote_poll_seconds=poll,
            debounce_seconds=debounce,
            periodic_notes_dir=str(payload.get("periodic_notes_dir", "周期笔记")).strip(),
        )

    def _on_sync_event(self, event: SyncEvent) -> None:
        with self._lock:
            self.state = event.state
            self.status_message = event.message
        self._add_log(event.message)

    def _add_log(self, message: str) -> None:
        with self._lock:
            self.sequence += 1
            self.logs.append(
                {
                    "id": self.sequence,
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "message": message,
                }
            )


class NoteSyncServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple, controller: AppController, token: str) -> None:
        self.controller = controller
        self.token = token
        super().__init__(address, NoteSyncRequestHandler)


class NoteSyncRequestHandler(BaseHTTPRequestHandler):
    server: NoteSyncServer

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path.startswith("/api/"):
            if not self._authorized():
                self._json({"error": "unauthorized"}, HTTPStatus.FORBIDDEN)
                return
            if self.path.startswith("/api/config"):
                self._json(self.server.controller.config_payload())
                return
            if self.path.startswith("/api/status"):
                self._json(self.server.controller.snapshot())
                return
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return

        if self.path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        html_path = Path(__file__).with_name("web") / "index.html"
        html = html_path.read_text(encoding="utf-8").replace(
            "__NOTESYNC_TOKEN__", self.server.token
        )
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline'; connect-src 'self'")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if not self._authorized():
            self._json({"error": "unauthorized"}, HTTPStatus.FORBIDDEN)
            return
        try:
            payload = self._read_json()
            controller = self.server.controller
            if self.path == "/api/start":
                self._json({"ok": True, "config": controller.start_sync(payload)})
            elif self.path == "/api/sync":
                controller.request_sync()
                self._json({"ok": True})
            elif self.path == "/api/stop":
                controller.stop_sync()
                self._json({"ok": True})
            elif self.path == "/api/notes":
                self._json({"ok": True, **controller.create_note(payload)})
            elif self.path == "/api/open-folder":
                controller.open_notes_folder(payload)
                self._json({"ok": True})
            elif self.path == "/api/shutdown":
                controller.stop_sync(quiet=True)
                self._json({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except Exception as error:
            self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _authorized(self) -> bool:
        return secrets.compare_digest(
            self.headers.get("X-NoteSync-Token", ""), self.server.token
        )

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("请求内容过大")
        if not length:
            return {}
        decoded = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("请求格式不正确")
        return decoded

    def _json(self, payload: Dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def run_web_app() -> None:
    controller = AppController()
    token = secrets.token_urlsafe(32)
    server = NoteSyncServer(("127.0.0.1", 0), controller, token)
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"NoteSync 已启动：{url}")
    print("关闭此终端或在页面中点击“退出 NoteSync”即可停止。")
    if os.environ.get("NOTESYNC_NO_BROWSER") != "1":
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        controller.stop_sync(quiet=True)
        server.server_close()
