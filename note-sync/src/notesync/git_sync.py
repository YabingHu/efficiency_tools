from __future__ import annotations

import os
import re
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable, List, Optional, Sequence, Union


Output = Union[str, bytes]


@dataclass
class CommandResult:
    returncode: int
    stdout: Output
    stderr: Output


class GitCommandError(RuntimeError):
    def __init__(self, args: Sequence[str], result: CommandResult):
        details = result.stderr or result.stdout
        if isinstance(details, bytes):
            details = details.decode("utf-8", errors="replace")
        message = str(details).strip() or f"Git 命令退出码 {result.returncode}"
        super().__init__(message)
        self.args_list = list(args)
        self.result = result


@dataclass
class SyncReport:
    committed: bool = False
    pulled: bool = False
    pushed: bool = False
    conflicts: List[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        actions: List[str] = []
        if self.committed:
            actions.append("已保存本地修改")
        if self.pulled:
            actions.append("已接收远端更新")
        if self.pushed:
            actions.append("已上传到 GitHub")
        if self.conflicts:
            actions.append(f"保留了 {len(self.conflicts)} 个冲突副本")
        return "，".join(actions) if actions else "已是最新状态"


class GitRepository:
    def __init__(
        self,
        root: Path,
        remote_url: str,
        branch: str = "main",
        device_name: str = "device",
        logger: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.root = root.expanduser().resolve()
        self.remote_url = remote_url.strip()
        self.branch = branch.strip()
        self.device_name = self._sanitize_device_name(device_name)
        self.logger = logger or (lambda _message: None)
        self._lock = threading.Lock()
        self._validate_branch()

    @staticmethod
    def _sanitize_device_name(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip())
        return cleaned.strip("-")[:40] or "device"

    def _validate_branch(self) -> None:
        invalid = (
            not re.fullmatch(r"[A-Za-z0-9._/-]+", self.branch)
            or self.branch.startswith(("-", "/", "."))
            or self.branch.endswith(("/", "."))
            or ".." in self.branch
            or "//" in self.branch
            or "@{" in self.branch
        )
        if invalid:
            raise ValueError(f"无效的分支名：{self.branch}")

    def _run(
        self,
        args: Sequence[str],
        *,
        check: bool = True,
        binary: bool = False,
    ) -> CommandResult:
        environment = os.environ.copy()
        environment["GIT_TERMINAL_PROMPT"] = "0"
        completed = subprocess.run(
            ["git", *args],
            cwd=str(self.root),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=not binary,
            check=False,
        )
        result = CommandResult(completed.returncode, completed.stdout, completed.stderr)
        if check and completed.returncode != 0:
            raise GitCommandError(args, result)
        return result

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        git_marker = self.root / ".git"
        if not git_marker.exists():
            self.logger("正在初始化本地 Git 仓库")
            self._run(["init", "-b", self.branch])

        inside = self._run(["rev-parse", "--is-inside-work-tree"]).stdout
        if str(inside).strip() != "true":
            raise RuntimeError("选择的目录不是有效的 Git 仓库")

        current_remote = self._run(["remote", "get-url", "origin"], check=False)
        if current_remote.returncode == 0:
            existing = str(current_remote.stdout).strip()
            if existing != self.remote_url:
                raise RuntimeError(
                    "该目录已经连接到另一个 origin。为避免误传数据，NoteSync 没有修改它。"
                )
        else:
            self._run(["remote", "add", "origin", self.remote_url])

        if self.has_commits():
            current_branch = str(self._run(["branch", "--show-current"]).stdout).strip()
            if current_branch and current_branch != self.branch:
                raise RuntimeError(
                    f"本地当前分支是 {current_branch}，配置中却是 {self.branch}。"
                )
        else:
            self._run(["symbolic-ref", "HEAD", f"refs/heads/{self.branch}"])

        self._ensure_local_excludes()

    def _ensure_local_excludes(self) -> None:
        exclude_file = self.root / ".git" / "info" / "exclude"
        if not exclude_file.parent.exists():
            return
        existing = exclude_file.read_text(encoding="utf-8") if exclude_file.exists() else ""
        patterns = [".DS_Store", "Thumbs.db", "Desktop.ini", ".notesync/"]
        missing = [pattern for pattern in patterns if pattern not in existing.splitlines()]
        if missing:
            with exclude_file.open("a", encoding="utf-8") as handle:
                if existing and not existing.endswith("\n"):
                    handle.write("\n")
                handle.write("# NoteSync local excludes\n")
                handle.write("\n".join(missing) + "\n")

    def has_commits(self) -> bool:
        return self._run(["rev-parse", "--verify", "HEAD"], check=False).returncode == 0

    def status_signature(self) -> str:
        result = self._run(["status", "--porcelain=v1", "-z"])
        return str(result.stdout)

    def _commit_all(self, message: str) -> bool:
        self._run(["add", "-A"])
        staged = self._run(["diff", "--cached", "--quiet"], check=False)
        if staged.returncode == 0:
            return False
        if staged.returncode != 1:
            raise GitCommandError(["diff", "--cached", "--quiet"], staged)
        self._run(
            [
                "-c",
                "user.name=NoteSync",
                "-c",
                "user.email=notesync@local",
                "commit",
                "-m",
                message,
            ]
        )
        return True

    def _create_initial_commit(self) -> None:
        self._run(
            [
                "-c",
                "user.name=NoteSync",
                "-c",
                "user.email=notesync@local",
                "commit",
                "--allow-empty",
                "-m",
                "NoteSync: initialize notes repository",
            ]
        )

    def _remote_branch_exists(self) -> bool:
        result = self._run(
            ["show-ref", "--verify", "--quiet", f"refs/remotes/origin/{self.branch}"],
            check=False,
        )
        return result.returncode == 0

    def sync(self) -> SyncReport:
        with self._lock:
            self.initialize()
            report = SyncReport()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            report.committed = self._commit_all(
                f"NoteSync: {self.device_name} {timestamp}"
            )

            self.logger("正在检查 GitHub 更新")
            self._run(["fetch", "--prune", "origin"])

            if self._remote_branch_exists():
                if not self.has_commits():
                    self._run(
                        ["checkout", "-B", self.branch, f"origin/{self.branch}"]
                    )
                    report.pulled = True
                else:
                    before = str(self._run(["rev-parse", "HEAD"]).stdout).strip()
                    merge = self._run(
                        [
                            "-c",
                            "user.name=NoteSync",
                            "-c",
                            "user.email=notesync@local",
                            "merge",
                            "--no-edit",
                            "--allow-unrelated-histories",
                            f"origin/{self.branch}",
                        ],
                        check=False,
                    )
                    if merge.returncode != 0:
                        unmerged = self._unmerged_paths()
                        if not unmerged:
                            self._abort_merge_if_needed()
                            raise GitCommandError(["merge", f"origin/{self.branch}"], merge)
                        report.conflicts = self._resolve_conflicts(unmerged)
                        self._commit_all(
                            f"NoteSync: preserve conflicts on {self.device_name} {timestamp}"
                        )
                    after = str(self._run(["rev-parse", "HEAD"]).stdout).strip()
                    report.pulled = before != after

            if not self.has_commits():
                self._create_initial_commit()
                report.committed = True

            self.logger("正在上传本地更新")
            self._run(["push", "-u", "origin", self.branch])
            report.pushed = report.committed or report.pulled or bool(report.conflicts)
            return report

    def _abort_merge_if_needed(self) -> None:
        if (self.root / ".git" / "MERGE_HEAD").exists():
            self._run(["merge", "--abort"], check=False)

    def _unmerged_paths(self) -> List[str]:
        result = self._run(
            ["diff", "--name-only", "--diff-filter=U", "-z"], binary=True
        )
        output = result.stdout if isinstance(result.stdout, bytes) else result.stdout.encode()
        return [part.decode("utf-8", errors="surrogateescape") for part in output.split(b"\0") if part]

    def _resolve_conflicts(self, paths: Sequence[str]) -> List[str]:
        saved: List[str] = []
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for relative in paths:
            target = self._safe_target(relative)
            ours = self._run(["show", f":2:{relative}"], check=False, binary=True)
            theirs = self._run(["show", f":3:{relative}"], check=False, binary=True)

            if ours.returncode == 0:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(self._as_bytes(ours.stdout))
            elif target.exists():
                target.unlink()

            conflict_relative: Optional[str] = None
            if theirs.returncode == 0:
                conflict_path = self._conflict_path(target, stamp)
                conflict_path.parent.mkdir(parents=True, exist_ok=True)
                conflict_path.write_bytes(self._as_bytes(theirs.stdout))
                conflict_relative = conflict_path.relative_to(self.root).as_posix()
                saved.append(conflict_relative)
                self.logger(f"检测到同时修改，已保留副本：{conflict_relative}")

            add_paths = [relative]
            if conflict_relative:
                add_paths.append(conflict_relative)
            self._run(["add", "-A", "--", *add_paths])
        return saved

    @staticmethod
    def _as_bytes(output: Output) -> bytes:
        return output if isinstance(output, bytes) else output.encode("utf-8")

    def _safe_target(self, relative: str) -> Path:
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts:
            raise RuntimeError(f"Git 返回了不安全的文件路径：{relative}")
        target = (self.root / Path(*pure.parts)).resolve()
        if self.root != target and self.root not in target.parents:
            raise RuntimeError(f"文件路径超出笔记目录：{relative}")
        return target

    def _conflict_path(self, original: Path, stamp: str) -> Path:
        suffix = original.suffix
        stem = original.name[: -len(suffix)] if suffix else original.name
        candidate = original.with_name(
            f"{stem}.conflict-remote-on-{self.device_name}-{stamp}{suffix}"
        )
        counter = 2
        while candidate.exists():
            candidate = original.with_name(
                f"{stem}.conflict-remote-on-{self.device_name}-{stamp}-{counter}{suffix}"
            )
            counter += 1
        return candidate
