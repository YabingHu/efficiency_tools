import tempfile
import unittest
from datetime import date
from pathlib import Path

from notesync.periodic_notes import (
    NoteKind,
    create_periodic_note,
    note_relative_path,
    render_note,
)


class PeriodicNoteTests(unittest.TestCase):
    def test_daily_note_has_expected_path_and_template(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = create_periodic_note(
                Path(directory), NoteKind.DAILY, date(2026, 11, 7)
            )
            self.assertTrue(result.created)
            self.assertEqual(
                Path("周期笔记/每日/2026/11/2026-11-07.md"),
                result.path.relative_to(Path(directory).resolve()),
            )
            content = result.path.read_text(encoding="utf-8")
            self.assertIn("# 2026-11-07 星期六", content)
            self.assertIn("## 今日记录", content)

    def test_monthly_note_has_a_heading_for_every_day(self) -> None:
        content = render_note(NoteKind.MONTHLY, date(2024, 2, 10))
        headings = [line for line in content.splitlines() if line.startswith("## ")]
        self.assertEqual(29, len(headings))
        self.assertEqual("## 2024-02-01 星期四", headings[0])
        self.assertEqual("## 2024-02-29 星期四", headings[-1])

    def test_weekly_note_uses_iso_week_across_year_boundary(self) -> None:
        target = date(2023, 1, 1)
        path = note_relative_path(NoteKind.WEEKLY, target, "周期笔记")
        self.assertEqual(Path("周期笔记/周度/2022/2022-W52.md"), path)
        content = render_note(NoteKind.WEEKLY, target)
        self.assertIn("## 2022-12-26 星期一", content)
        self.assertIn("## 2023-01-01 星期日", content)

    def test_existing_note_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = create_periodic_note(root, NoteKind.MONTHLY, date(2026, 11, 7))
            first.path.write_text("my existing note", encoding="utf-8")
            second = create_periodic_note(root, NoteKind.MONTHLY, date(2026, 11, 7))
            self.assertFalse(second.created)
            self.assertEqual("my existing note", second.path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
