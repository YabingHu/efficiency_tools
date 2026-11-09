from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from pathlib import Path, PurePath
from typing import List


WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


class NoteKind(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"

    @property
    def label(self) -> str:
        return {
            NoteKind.DAILY: "每日笔记",
            NoteKind.WEEKLY: "周度笔记",
            NoteKind.MONTHLY: "月度笔记",
        }[self]


@dataclass(frozen=True)
class CreatedNote:
    path: Path
    created: bool
    kind: NoteKind
    target_date: date


def validate_relative_folder(value: str) -> str:
    cleaned = value.strip().strip("/\\")
    if not cleaned:
        raise ValueError("周期笔记目录不能为空")
    path = PurePath(cleaned)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("周期笔记目录必须是笔记库内的相对路径")
    return cleaned


def note_relative_path(kind: NoteKind, target: date, base_folder: str) -> Path:
    base = Path(validate_relative_folder(base_folder))
    if kind is NoteKind.DAILY:
        return base / "每日" / f"{target.year:04d}" / f"{target.month:02d}" / f"{target:%Y-%m-%d}.md"
    if kind is NoteKind.WEEKLY:
        iso_year, iso_week, _ = target.isocalendar()
        return base / "周度" / f"{iso_year:04d}" / f"{iso_year:04d}-W{iso_week:02d}.md"
    return base / "月度" / f"{target.year:04d}" / f"{target:%Y-%m}.md"


def render_note(kind: NoteKind, target: date) -> str:
    if kind is NoteKind.DAILY:
        return _render_daily(target)
    if kind is NoteKind.WEEKLY:
        return _render_weekly(target)
    return _render_monthly(target)


def create_periodic_note(
    vault: Path,
    kind: NoteKind,
    target: date,
    base_folder: str = "周期笔记",
) -> CreatedNote:
    root = vault.expanduser().resolve()
    relative = note_relative_path(kind, target, base_folder)
    path = (root / relative).resolve()
    if root != path and root not in path.parents:
        raise ValueError("生成的笔记路径超出了笔记库")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(render_note(kind, target))
        created = True
    except FileExistsError:
        created = False
    return CreatedNote(path=path, created=created, kind=kind, target_date=target)


def _date_heading(value: date) -> str:
    return f"## {value:%Y-%m-%d} {WEEKDAYS[value.weekday()]}"


def _render_daily(target: date) -> str:
    return "\n".join(
        [
            "---",
            "type: daily",
            f"date: {target:%Y-%m-%d}",
            "---",
            "",
            f"# {target:%Y-%m-%d} {WEEKDAYS[target.weekday()]}",
            "",
            "## 今日记录",
            "",
            "",
        ]
    )


def _render_weekly(target: date) -> str:
    iso_year, iso_week, iso_weekday = target.isocalendar()
    monday = target - timedelta(days=iso_weekday - 1)
    sunday = monday + timedelta(days=6)
    lines: List[str] = [
        "---",
        "type: weekly",
        f"week: {iso_year:04d}-W{iso_week:02d}",
        f"start: {monday:%Y-%m-%d}",
        f"end: {sunday:%Y-%m-%d}",
        "---",
        "",
        f"# {iso_year:04d} 年第 {iso_week:02d} 周",
        "",
    ]
    for offset in range(7):
        lines.extend([_date_heading(monday + timedelta(days=offset)), ""])
    lines.append("")
    return "\n".join(lines)

def _render_monthly(target: date) -> str:
    day_count = calendar.monthrange(target.year, target.month)[1]
    lines: List[str] = [
        "---",
        "type: monthly",
        f"month: {target:%Y-%m}",
        "---",
        "",
        f"# {target.year:04d} 年 {target.month:02d} 月",
        "",
    ]
    for day in range(1, day_count + 1):
        lines.extend([_date_heading(date(target.year, target.month, day)), ""])
    lines.append("")
    return "\n".join(lines)
