from __future__ import annotations

import os
import platform
import queue
import subprocess
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from .config import AppConfig
from .engine import BackgroundSync, SyncEvent, SyncState
from .periodic_notes import NoteKind, create_periodic_note, note_relative_path


class NoteSyncApp:
    BG = "#F3F6FB"
    SURFACE = "#FFFFFF"
    SURFACE_SOFT = "#F8FAFC"
    TEXT = "#172033"
    MUTED = "#64748B"
    BORDER = "#DDE4EE"
    PRIMARY = "#4F46E5"
    PRIMARY_HOVER = "#4338CA"
    PRIMARY_SOFT = "#EEF2FF"
    GREEN = "#16A34A"
    RED = "#DC2626"
    AMBER = "#D97706"

    STATE_COLORS = {
        SyncState.STOPPED: MUTED,
        SyncState.WATCHING: GREEN,
        SyncState.SYNCING: PRIMARY,
        SyncState.ERROR: RED,
    }

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("NoteSync · 你的周期笔记")
        self.root.geometry("940x720")
        self.root.minsize(820, 640)
        self.font_family = self._font_family()
        self._apply_system_palette()
        self.root.configure(background=self.BG)

        self.config = AppConfig.load()
        self.engine: Optional[BackgroundSync] = None
        self.events: "queue.Queue[SyncEvent]" = queue.Queue()

        self.folder_var = tk.StringVar(value=self.config.notes_dir)
        self.remote_var = tk.StringVar(value=self.config.remote_url)
        self.branch_var = tk.StringVar(value=self.config.branch)
        self.device_var = tk.StringVar(value=self.config.device_name)
        self.poll_var = tk.StringVar(value=str(self.config.remote_poll_seconds))
        self.debounce_var = tk.StringVar(value=str(self.config.debounce_seconds))
        self.periodic_dir_var = tk.StringVar(value=self.config.periodic_notes_dir)
        self.note_date_var = tk.StringVar(value=date.today().isoformat())
        self.date_hint_var = tk.StringVar()
        self.status_var = tk.StringVar(value="同步尚未启动")

        self._configure_styles()
        self._build_ui()
        self._update_date_hint()
        self.note_date_var.trace_add("write", lambda *_args: self._update_date_hint())
        self.periodic_dir_var.trace_add("write", lambda *_args: self._update_date_hint())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(150, self._drain_events)

    @staticmethod
    def _font_family() -> str:
        system = platform.system()
        if system == "Darwin":
            return "SF Pro Text"
        if system == "Windows":
            return "Segoe UI"
        return "DejaVu Sans"

    def _apply_system_palette(self) -> None:
        dark_mode = False
        if platform.system() == "Darwin":
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
            )
            dark_mode = result.returncode == 0 and "dark" in result.stdout.lower()
        if dark_mode:
            self.BG = "#17191F"
            self.SURFACE = "#1E222A"
            self.SURFACE_SOFT = "#252A34"
            self.TEXT = "#F8FAFC"
            self.MUTED = "#AAB4C3"
            self.BORDER = "#3A4251"
            self.PRIMARY = "#7C83FF"
            self.PRIMARY_HOVER = "#696FE5"
            self.PRIMARY_SOFT = "#292D4A"
            self.GREEN = "#4ADE80"
            self.RED = "#FB7185"
            self.AMBER = "#FBBF24"
        self.STATE_COLORS = {
            SyncState.STOPPED: self.MUTED,
            SyncState.WATCHING: self.GREEN,
            SyncState.SYNCING: self.PRIMARY,
            SyncState.ERROR: self.RED,
        }
        self.root.tk_setPalette(
            background=self.BG,
            foreground=self.TEXT,
            activeBackground=self.PRIMARY_HOVER,
            activeForeground="white",
            selectBackground=self.PRIMARY,
            selectForeground="white",
        )

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TNotebook", background=self.BG, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=self.BG,
            foreground=self.MUTED,
            borderwidth=0,
            padding=(20, 11),
            font=(self.font_family, 11, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.SURFACE)],
            foreground=[("selected", self.PRIMARY)],
        )
        style.configure(
            "Modern.TEntry",
            fieldbackground=self.SURFACE_SOFT,
            foreground=self.TEXT,
            bordercolor=self.BORDER,
            lightcolor=self.BORDER,
            darkcolor=self.BORDER,
            padding=9,
            font=(self.font_family, 11),
        )
        style.configure(
            "Modern.TButton",
            background=self.PRIMARY,
            foreground="white",
            borderwidth=0,
            padding=(16, 10),
            font=(self.font_family, 11, "bold"),
        )
        style.map(
            "Modern.TButton",
            background=[("active", self.PRIMARY_HOVER), ("pressed", self.PRIMARY_HOVER)],
        )
        style.configure(
            "Quiet.TButton",
            background=self.SURFACE_SOFT,
            foreground=self.TEXT,
            borderwidth=0,
            padding=(14, 9),
            font=(self.font_family, 10, "bold"),
        )
        style.map("Quiet.TButton", background=[("active", self.PRIMARY_SOFT)])

    def _build_ui(self) -> None:
        shell = tk.Frame(self.root, bg=self.BG)
        shell.pack(fill="both", expand=True, padx=30, pady=(24, 28))

        header = tk.Frame(shell, bg=self.BG)
        header.pack(fill="x", pady=(0, 18))
        brand = tk.Frame(header, bg=self.BG)
        brand.pack(side="left")
        tk.Label(
            brand,
            text="N",
            bg=self.PRIMARY,
            fg="white",
            width=2,
            height=1,
            font=(self.font_family, 18, "bold"),
        ).pack(side="left", padx=(0, 12))
        title_box = tk.Frame(brand, bg=self.BG)
        title_box.pack(side="left")
        tk.Label(
            title_box,
            text="NoteSync",
            bg=self.BG,
            fg=self.TEXT,
            font=(self.font_family, 21, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title_box,
            text="周期记录与 GitHub 自动同步",
            bg=self.BG,
            fg=self.MUTED,
            font=(self.font_family, 10),
        ).pack(anchor="w")

        status_box = tk.Frame(
            header,
            bg=self.SURFACE,
            highlightbackground=self.BORDER,
            highlightthickness=1,
            padx=12,
            pady=8,
        )
        status_box.pack(side="right")
        self.status_dot = tk.Canvas(
            status_box,
            width=12,
            height=12,
            bg=self.SURFACE,
            highlightthickness=0,
        )
        self.status_dot.pack(side="left", padx=(0, 8))
        self.status_dot_id = self.status_dot.create_oval(
            2, 2, 10, 10, fill=self.MUTED, outline=""
        )
        tk.Label(
            status_box,
            textvariable=self.status_var,
            bg=self.SURFACE,
            fg=self.TEXT,
            font=(self.font_family, 10, "bold"),
        ).pack(side="left")

        self.notebook = ttk.Notebook(shell)
        self.notebook.pack(fill="both", expand=True)
        self.notes_page = tk.Frame(self.notebook, bg=self.SURFACE)
        self.settings_page = tk.Frame(self.notebook, bg=self.SURFACE)
        self.activity_page = tk.Frame(self.notebook, bg=self.SURFACE)
        self.notebook.add(self.notes_page, text="新增笔记")
        self.notebook.add(self.settings_page, text="同步设置")
        self.notebook.add(self.activity_page, text="活动记录")

        self._build_notes_page()
        self._build_settings_page()
        self._build_activity_page()

    def _page_header(self, parent: tk.Frame, title: str, subtitle: str) -> None:
        tk.Label(
            parent,
            text=title,
            bg=self.SURFACE,
            fg=self.TEXT,
            font=(self.font_family, 22, "bold"),
        ).pack(anchor="w")
        tk.Label(
            parent,
            text=subtitle,
            bg=self.SURFACE,
            fg=self.MUTED,
            font=(self.font_family, 11),
        ).pack(anchor="w", pady=(5, 0))

    def _build_notes_page(self) -> None:
        page = tk.Frame(self.notes_page, bg=self.SURFACE, padx=28, pady=25)
        page.pack(fill="both", expand=True)
        self._page_header(page, "今天想记录什么？", "选择一种周期，模板会按所选日期自动生成。")

        date_bar = tk.Frame(
            page,
            bg=self.SURFACE_SOFT,
            highlightbackground=self.BORDER,
            highlightthickness=1,
            padx=16,
            pady=13,
        )
        date_bar.pack(fill="x", pady=(22, 18))
        tk.Label(
            date_bar,
            text="基准日期",
            bg=self.SURFACE_SOFT,
            fg=self.TEXT,
            font=(self.font_family, 10, "bold"),
        ).pack(side="left")
        ttk.Button(
            date_bar, text="‹", width=3, style="Quiet.TButton", command=lambda: self._shift_date(-1)
        ).pack(side="left", padx=(18, 6))
        ttk.Entry(
            date_bar,
            textvariable=self.note_date_var,
            width=14,
            justify="center",
            style="Modern.TEntry",
        ).pack(side="left")
        ttk.Button(
            date_bar, text="›", width=3, style="Quiet.TButton", command=lambda: self._shift_date(1)
        ).pack(side="left", padx=(6, 10))
        ttk.Button(date_bar, text="今天", style="Quiet.TButton", command=self._use_today).pack(
            side="left"
        )
        tk.Label(
            date_bar,
            text="格式：YYYY-MM-DD",
            bg=self.SURFACE_SOFT,
            fg=self.MUTED,
            font=(self.font_family, 9),
        ).pack(side="right")

        cards = tk.Frame(page, bg=self.SURFACE)
        cards.pack(fill="both", expand=True)
        for column in range(3):
            cards.grid_columnconfigure(column, weight=1, uniform="note-card")
        self._note_card(
            cards,
            0,
            "日",
            "每日笔记",
            "快速记录当天的想法、进展和待办。",
            "#DBEAFE",
            "#2563EB",
            NoteKind.DAILY,
        )
        self._note_card(
            cards,
            1,
            "周",
            "周度笔记",
            "按 ISO 周创建，并预先列出周一到周日。",
            "#DCFCE7",
            "#15803D",
            NoteKind.WEEKLY,
        )
        self._note_card(
            cards,
            2,
            "月",
            "月度笔记",
            "自动生成当月每天的二级日期标题。",
            "#F3E8FF",
            "#7E22CE",
            NoteKind.MONTHLY,
        )

        destination = tk.Frame(page, bg=self.SURFACE)
        destination.pack(fill="x", pady=(18, 0))
        tk.Label(
            destination,
            text="保存目录",
            bg=self.SURFACE,
            fg=self.TEXT,
            font=(self.font_family, 10, "bold"),
        ).pack(side="left")
        ttk.Entry(
            destination,
            textvariable=self.periodic_dir_var,
            width=20,
            style="Modern.TEntry",
        ).pack(side="left", padx=(12, 16))
        tk.Label(
            destination,
            textvariable=self.date_hint_var,
            bg=self.SURFACE,
            fg=self.MUTED,
            font=(self.font_family, 9),
        ).pack(side="left", fill="x", expand=True)

    def _note_card(
        self,
        parent: tk.Frame,
        column: int,
        icon: str,
        title: str,
        description: str,
        icon_bg: str,
        icon_fg: str,
        kind: NoteKind,
    ) -> None:
        card = tk.Frame(
            parent,
            bg=self.SURFACE,
            highlightbackground=self.BORDER,
            highlightthickness=1,
            padx=18,
            pady=18,
        )
        card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 7, 0 if column == 2 else 7))
        tk.Label(
            card,
            text=icon,
            bg=icon_bg,
            fg=icon_fg,
            width=3,
            height=1,
            font=(self.font_family, 18, "bold"),
        ).pack(anchor="w")
        tk.Label(
            card,
            text=title,
            bg=self.SURFACE,
            fg=self.TEXT,
            font=(self.font_family, 15, "bold"),
        ).pack(anchor="w", pady=(18, 8))
        tk.Label(
            card,
            text=description,
            bg=self.SURFACE,
            fg=self.MUTED,
            justify="left",
            wraplength=200,
            font=(self.font_family, 10),
        ).pack(anchor="w", fill="x")
        tk.Button(
            card,
            text="创建并打开",
            command=lambda selected=kind: self._create_note(selected),
            bg=self.PRIMARY,
            fg="white",
            activebackground=self.PRIMARY_HOVER,
            activeforeground="white",
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            padx=14,
            pady=9,
            font=(self.font_family, 10, "bold"),
        ).pack(anchor="w", fill="x", side="bottom", pady=(22, 0))

    def _build_settings_page(self) -> None:
        page = tk.Frame(self.settings_page, bg=self.SURFACE, padx=28, pady=25)
        page.pack(fill="both", expand=True)
        self._page_header(page, "同步设置", "连接 GitHub 后，新增和修改的笔记会在后台自动同步。")

        form = tk.Frame(
            page,
            bg=self.SURFACE_SOFT,
            highlightbackground=self.BORDER,
            highlightthickness=1,
            padx=20,
            pady=16,
        )
        form.pack(fill="x", pady=(22, 16))
        form.grid_columnconfigure(1, weight=1)
        self._settings_row(form, 0, "笔记目录", self.folder_var, browse=True)
        self._settings_row(form, 1, "GitHub 仓库", self.remote_var)
        self._settings_row(form, 2, "分支", self.branch_var, compact=True)
        self._settings_row(form, 3, "设备名称", self.device_var, compact=True)

        timing = tk.Frame(page, bg=self.SURFACE)
        timing.pack(fill="x", pady=(2, 20))
        tk.Label(
            timing,
            text="远端检查间隔",
            bg=self.SURFACE,
            fg=self.TEXT,
            font=(self.font_family, 10, "bold"),
        ).pack(side="left")
        ttk.Entry(timing, textvariable=self.poll_var, width=7, style="Modern.TEntry").pack(
            side="left", padx=(10, 6)
        )
        tk.Label(timing, text="秒", bg=self.SURFACE, fg=self.MUTED).pack(side="left")
        tk.Label(
            timing,
            text="文件停止变化",
            bg=self.SURFACE,
            fg=self.TEXT,
            font=(self.font_family, 10, "bold"),
        ).pack(side="left", padx=(30, 0))
        ttk.Entry(
            timing, textvariable=self.debounce_var, width=7, style="Modern.TEntry"
        ).pack(side="left", padx=(10, 6))
        tk.Label(timing, text="秒后同步", bg=self.SURFACE, fg=self.MUTED).pack(side="left")

        controls = tk.Frame(page, bg=self.SURFACE)
        controls.pack(fill="x")
        ttk.Button(controls, text="保存并启动", style="Modern.TButton", command=self._start).pack(
            side="left"
        )
        ttk.Button(controls, text="立即同步", style="Quiet.TButton", command=self._sync_now).pack(
            side="left", padx=9
        )
        ttk.Button(controls, text="停止同步", style="Quiet.TButton", command=self._stop).pack(
            side="left"
        )
        ttk.Button(controls, text="打开笔记目录", style="Quiet.TButton", command=self._open_folder).pack(
            side="right"
        )

        tip = tk.Frame(page, bg=self.PRIMARY_SOFT, padx=15, pady=13)
        tip.pack(fill="x", pady=(22, 0))
        tk.Label(
            tip,
            text="提示",
            bg=self.PRIMARY_SOFT,
            fg=self.PRIMARY,
            font=(self.font_family, 10, "bold"),
        ).pack(side="left", padx=(0, 10))
        tk.Label(
            tip,
            text="推荐使用 GitHub SSH 地址。后台同步不会弹出密码输入框。",
            bg=self.PRIMARY_SOFT,
            fg=self.TEXT,
            font=(self.font_family, 10),
        ).pack(side="left")

    def _settings_row(
        self,
        parent: tk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        browse: bool = False,
        compact: bool = False,
    ) -> None:
        tk.Label(
            parent,
            text=label,
            bg=self.SURFACE_SOFT,
            fg=self.TEXT,
            font=(self.font_family, 10, "bold"),
        ).grid(row=row, column=0, sticky="w", pady=7)
        entry = ttk.Entry(
            parent,
            textvariable=variable,
            width=20 if compact else 50,
            style="Modern.TEntry",
        )
        entry.grid(row=row, column=1, sticky="w" if compact else "ew", padx=(16, 8), pady=7)
        if browse:
            ttk.Button(parent, text="选择…", style="Quiet.TButton", command=self._choose_folder).grid(
                row=row, column=2, pady=7
            )

    def _build_activity_page(self) -> None:
        page = tk.Frame(self.activity_page, bg=self.SURFACE, padx=28, pady=25)
        page.pack(fill="both", expand=True)
        self._page_header(page, "活动记录", "查看笔记创建、上传、下载和冲突处理状态。")
        log_shell = tk.Frame(
            page,
            bg=self.SURFACE_SOFT,
            highlightbackground=self.BORDER,
            highlightthickness=1,
            padx=14,
            pady=14,
        )
        log_shell.pack(fill="both", expand=True, pady=(22, 0))
        self.log = tk.Text(
            log_shell,
            wrap="word",
            state="disabled",
            borderwidth=0,
            highlightthickness=0,
            background=self.SURFACE_SOFT,
            foreground=self.TEXT,
            insertbackground=self.TEXT,
            font=("Menlo" if platform.system() == "Darwin" else "Consolas", 10),
            padx=8,
            pady=8,
        )
        scrollbar = ttk.Scrollbar(log_shell, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._append_log("NoteSync 已就绪。你可以先创建笔记，也可以配置 GitHub 自动同步。")

    def _choose_folder(self) -> None:
        selected = filedialog.askdirectory(
            initialdir=self.folder_var.get() or str(Path.home()),
            mustexist=False,
        )
        if selected:
            self.folder_var.set(selected)

    def _selected_date(self) -> date:
        try:
            return date.fromisoformat(self.note_date_var.get().strip())
        except ValueError as error:
            raise ValueError("日期格式不正确，请使用 YYYY-MM-DD") from error

    def _shift_date(self, days: int) -> None:
        try:
            selected = self._selected_date()
        except ValueError:
            selected = date.today()
        self.note_date_var.set((selected + timedelta(days=days)).isoformat())

    def _use_today(self) -> None:
        self.note_date_var.set(date.today().isoformat())

    def _update_date_hint(self) -> None:
        try:
            selected = self._selected_date()
            path = note_relative_path(
                NoteKind.MONTHLY,
                selected,
                self.periodic_dir_var.get(),
            )
            self.date_hint_var.set(f"月度示例：{path.as_posix()}")
        except ValueError as error:
            self.date_hint_var.set(str(error))

    def _create_note(self, kind: NoteKind) -> None:
        try:
            folder = self.folder_var.get().strip()
            if not folder:
                raise ValueError("请先到“同步设置”选择笔记目录")
            vault = Path(folder).expanduser()
            vault.mkdir(parents=True, exist_ok=True)
            selected = self._selected_date()
            result = create_periodic_note(
                vault,
                kind,
                selected,
                self.periodic_dir_var.get(),
            )
            self.config.notes_dir = str(vault.resolve())
            self.config.periodic_notes_dir = self.periodic_dir_var.get().strip()
            self.config.save()
        except Exception as error:
            messagebox.showerror("无法创建笔记", str(error))
            return

        relative = result.path.relative_to(vault.resolve()).as_posix()
        if result.created:
            message = f"已创建{kind.label}：{relative}"
            self._set_status(SyncState.WATCHING, f"{kind.label}已创建")
            self._append_log(message)
            if self.engine and self.engine.running:
                self.engine.request_sync()
            self._open_path(result.path)
            return

        self._append_log(f"笔记已存在，未覆盖：{relative}")
        if messagebox.askyesno("笔记已经存在", f"{relative}\n\n是否打开现有笔记？"):
            self._open_path(result.path)

    def _read_config(self) -> AppConfig:
        try:
            poll = int(self.poll_var.get())
            debounce = int(self.debounce_var.get())
        except ValueError as error:
            raise ValueError("同步间隔必须是整数") from error
        config = AppConfig(
            notes_dir=self.folder_var.get().strip(),
            remote_url=self.remote_var.get().strip(),
            branch=self.branch_var.get().strip(),
            device_name=self.device_var.get().strip(),
            remote_poll_seconds=poll,
            debounce_seconds=debounce,
            periodic_notes_dir=self.periodic_dir_var.get().strip(),
        )
        config.validate()
        return config

    def _start(self) -> None:
        try:
            config = self._read_config()
            config.save()
        except Exception as error:
            messagebox.showerror("无法启动", str(error))
            return
        self._stop(quiet=True)
        self.config = config
        self.engine = BackgroundSync(config, self.events.put)
        self.engine.start()
        self._append_log("配置已保存，后台同步已启动。")

    def _sync_now(self) -> None:
        if not self.engine or not self.engine.running:
            self._start()
            return
        self.engine.request_sync()

    def _stop(self, quiet: bool = False) -> None:
        if self.engine:
            self.engine.stop()
            self.engine = None
        if not quiet:
            self._set_status(SyncState.STOPPED, "同步已停止")

    def _drain_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                self._set_status(event.state, event.message)
                self._append_log(event.message)
        except queue.Empty:
            pass
        self.root.after(150, self._drain_events)

    def _set_status(self, state: SyncState, message: str) -> None:
        self.status_var.set(message)
        self.status_dot.itemconfigure(self.status_dot_id, fill=self.STATE_COLORS[state])

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert("end", f"{timestamp}  {message}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _open_folder(self) -> None:
        path = Path(self.folder_var.get()).expanduser()
        if not path.exists():
            messagebox.showwarning("目录不存在", "请先选择或创建笔记目录。")
            return
        self._open_path(path)

    @staticmethod
    def _open_path(path: Path) -> None:
        system = platform.system()
        if system == "Darwin":
            subprocess.Popen(["open", str(path)])
        elif system == "Windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def _on_close(self) -> None:
        self._stop(quiet=True)
        self.root.destroy()


def run_app() -> None:
    root = tk.Tk()
    NoteSyncApp(root)
    root.mainloop()
