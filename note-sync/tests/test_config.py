import json
import tempfile
import unittest
from pathlib import Path

from notesync.config import AppConfig


class AppConfigTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            original = AppConfig(
                notes_dir="/tmp/notes",
                remote_url="git@example.test:me/notes.git",
                branch="main",
                device_name="laptop",
                remote_poll_seconds=45,
                debounce_seconds=3,
            )
            original.save(path)
            loaded = AppConfig.load(path)
            self.assertEqual(original, loaded)
            self.assertEqual("/tmp/notes", json.loads(path.read_text())["notes_dir"])

    def test_rejects_too_fast_polling(self) -> None:
        config = AppConfig(notes_dir="x", remote_url="y", remote_poll_seconds=1)
        with self.assertRaises(ValueError):
            config.validate()


if __name__ == "__main__":
    unittest.main()
