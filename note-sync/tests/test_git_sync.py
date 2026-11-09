import subprocess
import tempfile
import unittest
from pathlib import Path

from notesync.git_sync import GitRepository


def run_git(directory: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(directory),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )


class GitSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.remote = self.base / "remote.git"
        self.remote.mkdir()
        run_git(self.remote, "init", "--bare", "--initial-branch=main")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def repository(self, name: str) -> GitRepository:
        return GitRepository(
            self.base / name,
            str(self.remote),
            branch="main",
            device_name=name,
        )

    def test_two_devices_exchange_files(self) -> None:
        first = self.repository("first")
        first.root.mkdir()
        (first.root / "hello.md").write_text("hello", encoding="utf-8")
        first_report = first.sync()
        self.assertTrue(first_report.committed)

        second = self.repository("second")
        second.sync()
        self.assertEqual("hello", (second.root / "hello.md").read_text())

        (second.root / "image.bin").write_bytes(b"\x00\x01image")
        second.sync()
        first.sync()
        self.assertEqual(b"\x00\x01image", (first.root / "image.bin").read_bytes())

    def test_empty_folder_can_initialize_empty_remote(self) -> None:
        repository = self.repository("empty")
        report = repository.sync()
        self.assertTrue(report.committed)
        remote_head = run_git(self.remote, "rev-parse", "refs/heads/main")
        self.assertTrue(remote_head.stdout.strip())

    def test_same_file_conflict_preserves_both_versions(self) -> None:
        first = self.repository("first")
        first.root.mkdir()
        note = first.root / "shared.md"
        note.write_text("base\n", encoding="utf-8")
        first.sync()

        second = self.repository("second")
        second.sync()

        note.write_text("edited on first\n", encoding="utf-8")
        first.sync()
        second_note = second.root / "shared.md"
        second_note.write_text("edited on second\n", encoding="utf-8")
        report = second.sync()

        self.assertEqual("edited on second\n", second_note.read_text())
        self.assertEqual(1, len(report.conflicts))
        conflict = second.root / report.conflicts[0]
        self.assertEqual("edited on first\n", conflict.read_text())

        first.sync()
        self.assertEqual("edited on second\n", note.read_text())
        matching = list(first.root.glob("shared.conflict-remote-on-second-*.md"))
        self.assertEqual(1, len(matching))
        self.assertEqual("edited on first\n", matching[0].read_text())

    def test_rejects_existing_different_origin(self) -> None:
        root = self.base / "existing"
        root.mkdir()
        run_git(root, "init", "-b", "main")
        run_git(root, "remote", "add", "origin", "example:other/repo.git")
        repository = GitRepository(root, str(self.remote))
        with self.assertRaisesRegex(RuntimeError, "另一个 origin"):
            repository.initialize()


if __name__ == "__main__":
    unittest.main()
