from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from .config import AppConfig
from .git_sync import GitRepository, SyncReport


class SyncState(str, Enum):
    STOPPED = "stopped"
    WATCHING = "watching"
    SYNCING = "syncing"
    ERROR = "error"


@dataclass
class SyncEvent:
    state: SyncState
    message: str
    report: Optional[SyncReport] = None


class BackgroundSync:
    def __init__(
        self,
        config: AppConfig,
        callback: Optional[Callable[[SyncEvent], None]] = None,
    ) -> None:
        self.config = config
        self.callback = callback or (lambda _event: None)
        self._stop = threading.Event()
        self._sync_requested = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_event: Optional[tuple] = None
        self.repository = GitRepository(
            Path(config.notes_dir),
            config.remote_url,
            config.branch,
            config.device_name,
            logger=self._log,
        )

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self.config.validate()
        self._stop.clear()
        self._sync_requested.set()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="NoteSyncBackground",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._sync_requested.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)
        self._emit(SyncState.STOPPED, "同步已停止")

    def request_sync(self) -> None:
        self._sync_requested.set()

    def _run_loop(self) -> None:
        last_signature: Optional[str] = None
        changed_at: Optional[float] = None
        next_remote_check = 0.0

        while not self._stop.is_set():
            now = time.monotonic()
            manual = self._sync_requested.is_set()
            if manual:
                self._sync_requested.clear()

            try:
                self.repository.initialize()
                signature = self.repository.status_signature()
                if signature != last_signature:
                    last_signature = signature
                    changed_at = now if signature else None

                local_ready = bool(
                    signature
                    and changed_at is not None
                    and now - changed_at >= self.config.debounce_seconds
                )
                remote_ready = now >= next_remote_check

                if manual or local_ready or remote_ready:
                    self._emit(SyncState.SYNCING, "正在同步…")
                    report = self.repository.sync()
                    self._emit(SyncState.WATCHING, report.summary, report)
                    last_signature = self.repository.status_signature()
                    changed_at = None
                    next_remote_check = time.monotonic() + self.config.remote_poll_seconds
                else:
                    self._emit(SyncState.WATCHING, "正在监听文件变化")
            except Exception as error:  # keep the daemon alive and retry safely
                self._emit(SyncState.ERROR, str(error))
                next_remote_check = time.monotonic() + 15

            self._stop.wait(1.0)

    def _log(self, message: str) -> None:
        self._emit(SyncState.SYNCING, message)

    def _emit(
        self,
        state: SyncState,
        message: str,
        report: Optional[SyncReport] = None,
    ) -> None:
        event_key = (state, message)
        if report is None and event_key == self._last_event:
            return
        self._last_event = event_key
        self.callback(SyncEvent(state, message, report))
