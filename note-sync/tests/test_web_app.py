import tempfile
import unittest
from pathlib import Path

from notesync.web_app import AppController


class WebAppControllerTests(unittest.TestCase):
    def test_create_monthly_note_from_frontend_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = AppController(
                config_path=root / "config.json",
                open_created_files=False,
            )
            payload = {
                "notes_dir": str(root / "vault"),
                "periodic_notes_dir": "我的周期笔记",
                "kind": "monthly",
                "date": "2026-11-07",
            }
            result = controller.create_note(payload)
            self.assertTrue(result["created"])
            note = root / "vault" / result["relative_path"]
            self.assertTrue(note.exists())
            headings = [
                line
                for line in note.read_text(encoding="utf-8").splitlines()
                if line.startswith("## ")
            ]
            self.assertEqual(30, len(headings))

            repeated = controller.create_note(payload)
            self.assertFalse(repeated["created"])


if __name__ == "__main__":
    unittest.main()
