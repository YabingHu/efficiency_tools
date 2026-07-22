"""跨天去重台账：记录已在早报中展示过的条目，抑制窗口期内的重复。

单次运行内的去重由 main.deduplicate 负责；本模块解决跨天重复——同一条资讯
连续几天被采集到时，只在第一次展示，之后一周内不再重复出现。台账保存在
history/seen-items.json，随 digest-history artifact 在云端逐日累积。

只记录“真正渲染进早报”的条目，而非全部采集结果：被限流截断的新条目不会因此
被永久压制，改天仍有机会展示。读取/写入失败均降级为不去重，绝不阻断早报生成。
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

from .models import NewsItem
from .utils import canonical_url, safe_http_url

log = logging.getLogger(__name__)


def _entry_keys(item: NewsItem) -> set[str]:
    """一条资讯的去重键：ID 和规范化 URL 各算一个，命中任一即视为重复。"""
    keys = {f"id:{item.id}"}
    safe_url = safe_http_url(item.url)
    if safe_url is not None:
        keys.add(f"url:{canonical_url(safe_url)}")
    return keys


class SeenLedger:
    def __init__(self, path: str | Path, window_days: int):
        self.path = Path(path)
        self.window_days = window_days
        self._entries: dict[str, str] = self._load()
        self._dirty = False

    def _load(self) -> dict[str, str]:
        if not self.path.is_file():
            return {}
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
            raw_entries = document.get("entries", {})
            if not isinstance(raw_entries, dict):
                raise ValueError("entries 不是对象")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            log.warning("跨天去重台账无法读取，本次不去重: %s", exc)
            return {}

        entries = {}
        for key, value in raw_entries.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            try:
                date.fromisoformat(value)
            except ValueError:
                continue
            entries[key] = value
        return entries

    def filter_unseen(self, items: list[NewsItem], report_date: date) -> list[NewsItem]:
        """滤掉近 window_days 天内已展示过的条目（不含当天本身）。"""
        window_start = report_date - timedelta(days=self.window_days)
        fresh, dropped = [], 0
        for item in items:
            if self._is_recent_duplicate(item, window_start, report_date):
                dropped += 1
                log.debug("跨天去重命中，跳过：%s", item.title[:80])
                continue
            fresh.append(item)
        if dropped:
            log.info("跨天去重：过滤掉 %d 条近 %d 天已展示的重复", dropped, self.window_days)
        return fresh

    def _is_recent_duplicate(
        self, item: NewsItem, window_start: date, report_date: date
    ) -> bool:
        for key in _entry_keys(item):
            seen = self._entries.get(key)
            if seen is None:
                continue
            seen_date = date.fromisoformat(seen)
            if window_start <= seen_date < report_date:
                return True
        return False

    def record(self, items: list[NewsItem], report_date: date) -> None:
        """把本期真正展示的条目登记为“已见”，日期用报告日。"""
        iso = report_date.isoformat()
        for item in items:
            for key in _entry_keys(item):
                if self._entries.get(key) != iso:
                    self._entries[key] = iso
                    self._dirty = True

    def prune(self, report_date: date) -> None:
        """丢弃早于窗口的记录——它们再也压制不了任何东西。"""
        cutoff = report_date - timedelta(days=self.window_days)
        stale = [
            key for key, value in self._entries.items()
            if date.fromisoformat(value) < cutoff
        ]
        for key in stale:
            del self._entries[key]
            self._dirty = True

    def save(self) -> None:
        if not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        document = {"version": 1, "entries": self._entries}
        fd, temp_name = tempfile.mkstemp(
            dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp",
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                json.dump(document, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temp_path.replace(self.path)
            self._dirty = False
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    def save_safely(self) -> None:
        try:
            self.save()
        except OSError as exc:
            log.warning("跨天去重台账写入失败，本次早报仍继续生成: %s", exc)
