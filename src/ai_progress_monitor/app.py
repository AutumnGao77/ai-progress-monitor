from __future__ import annotations

import argparse
import os
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import ttk
from typing import Iterable, List, Optional

from .actions import ActionExecutor, is_low_risk_action
from .demo import DemoSource
from .models import SessionStatus, SessionUpdate
from .sources import CodexSessionSource, JsonSessionSource, OsWindowSource
from .store import SessionStore


STATUS_LABELS = {
    SessionStatus.NEEDS_ACTION: "需要处理",
    SessionStatus.RUNNING: "执行中",
    SessionStatus.IDLE: "空闲/完成",
    SessionStatus.STUCK: "疑似卡住",
    SessionStatus.UNKNOWN: "无法识别",
}

STATUS_COLORS = {
    SessionStatus.NEEDS_ACTION: "#d84a2b",
    SessionStatus.RUNNING: "#2563eb",
    SessionStatus.IDLE: "#2f7d32",
    SessionStatus.STUCK: "#b7791f",
    SessionStatus.UNKNOWN: "#6b7280",
}


class ProgressPetApp:
    def __init__(self, sources: Iterable, store: SessionStore, executor: ActionExecutor, poll_ms: int = 3000):
        self.sources = list(sources)
        self.store = store
        self.executor = executor
        self.poll_ms = poll_ms
        self.paused = False
        self.expanded = False
        self.drag_offset = (0, 0)

        self.root = tk.Tk()
        self.root.title("AI Progress Monitor")
        self.root.geometry("184x64+40+120")
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.92)
        self.root.resizable(False, False)
        self.root.configure(bg="#111827")
        try:
            self.root.overrideredirect(True)
        except tk.TclError:
            pass

        self.status_dot = tk.Label(self.root, text="●", fg="#6b7280", bg="#111827", font=("Arial", 16))
        self.status_dot.place(x=10, y=10)
        self.title_label = tk.Label(
            self.root,
            text="AI Monitor",
            fg="#f9fafb",
            bg="#111827",
            font=("Arial", 12, "bold"),
        )
        self.title_label.place(x=36, y=10)
        self.summary_label = tk.Label(
            self.root,
            text="启动中",
            fg="#d1d5db",
            bg="#111827",
            font=("Arial", 10),
            anchor="w",
        )
        self.summary_label.place(x=36, y=34, width=136)

        self.panel = None
        self.root.bind("<Button-1>", self._start_drag)
        self.root.bind("<B1-Motion>", self._drag)
        self.root.bind("<Double-Button-1>", lambda _event: self.toggle_panel())
        self.root.bind("<Button-3>", lambda _event: self.toggle_panel())
        self.root.after(200, self.refresh)

    def run(self) -> None:
        self.root.mainloop()

    def refresh(self) -> None:
        if not self.paused:
            for source in self.sources:
                self.store.apply_updates(source.poll())
        sessions = self.store.sessions()
        self._render_pet(sessions)
        if self.panel is not None and self.panel.winfo_exists():
            self._render_panel(sessions)
        self.root.after(self.poll_ms, self.refresh)

    def toggle_panel(self) -> None:
        if self.panel is not None and self.panel.winfo_exists():
            self.panel.destroy()
            self.panel = None
            return
        self.panel = tk.Toplevel(self.root)
        self.panel.title("AI Progress Sessions")
        self.panel.geometry("460x360+40+190")
        self.panel.attributes("-topmost", True)
        self.panel.configure(bg="#f8fafc")
        self._render_panel(self.store.sessions())

    def _render_pet(self, sessions: List[SessionUpdate]) -> None:
        if not sessions:
            self.status_dot.configure(fg=STATUS_COLORS[SessionStatus.UNKNOWN])
            self.summary_label.configure(text="未发现会话")
            return
        top = sessions[0]
        count = sum(1 for session in sessions if session.status == SessionStatus.NEEDS_ACTION)
        if count:
            text = f"{count} 个待处理"
        else:
            text = f"{STATUS_LABELS[top.status]} · {len(sessions)} 个会话"
        self.status_dot.configure(fg=STATUS_COLORS[top.status])
        self.summary_label.configure(text=text)

    def _render_panel(self, sessions: List[SessionUpdate]) -> None:
        for child in self.panel.winfo_children():
            child.destroy()
        header = tk.Frame(self.panel, bg="#f8fafc")
        header.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(header, text="AI 工作进度", bg="#f8fafc", fg="#111827", font=("Arial", 14, "bold")).pack(side="left")
        ttk.Button(header, text="暂停" if not self.paused else "继续", command=self._toggle_pause).pack(side="right")
        ttk.Button(header, text="隐藏", command=self.panel.destroy).pack(side="right", padx=6)

        if not sessions:
            tk.Label(self.panel, text="暂无 Claude Code / Codex 会话", bg="#f8fafc", fg="#6b7280").pack(pady=40)
            return

        for session in sessions:
            self._render_session_row(session)

    def _render_session_row(self, session: SessionUpdate) -> None:
        row = tk.Frame(self.panel, bg="white", highlightbackground="#e5e7eb", highlightthickness=1)
        row.pack(fill="x", padx=12, pady=5)
        color = STATUS_COLORS[session.status]
        title = f"{session.title} · {session.tool.value} · {session.surface.value}"
        tk.Label(row, text=title, bg="white", fg="#111827", anchor="w", font=("Arial", 11, "bold")).pack(fill="x", padx=10, pady=(8, 2))
        status_text = f"{STATUS_LABELS[session.status]} · {session.summary} · {human_time(session.updated_at)}"
        tk.Label(row, text=status_text, bg="white", fg=color, anchor="w", wraplength=420).pack(fill="x", padx=10, pady=(0, 8))
        if session.safe_action and is_low_risk_action(session.safe_action):
            actions = tk.Frame(row, bg="white")
            actions.pack(fill="x", padx=10, pady=(0, 8))
            for option in session.safe_action.options:
                ttk.Button(actions, text=option, command=lambda opt=option, s=session: self._execute_action(s, opt)).pack(side="left", padx=(0, 6))
        elif session.status == SessionStatus.NEEDS_ACTION:
            ttk.Button(row, text="需要进入原窗口处理", command=lambda s=session: self._record_open_request(s)).pack(anchor="w", padx=10, pady=(0, 8))

    def _execute_action(self, session: SessionUpdate, option: str) -> None:
        result = self.executor.execute(session.session_id, session.safe_action, option)
        self.store.audit_action(session.session_id, option, "sent" if result.ok else result.detail)
        self.refresh()

    def _record_open_request(self, session: SessionUpdate) -> None:
        self.store.audit_action(session.session_id, "open-window", "manual-attention-required")

    def _toggle_pause(self) -> None:
        self.paused = not self.paused
        self.refresh()

    def _start_drag(self, event) -> None:
        self.drag_offset = (event.x, event.y)

    def _drag(self, event) -> None:
        x = self.root.winfo_pointerx() - self.drag_offset[0]
        y = self.root.winfo_pointery() - self.drag_offset[1]
        self.root.geometry(f"+{x}+{y}")


def human_time(value: datetime) -> str:
    seconds = max(0, int((datetime.now(timezone.utc) - value).total_seconds()))
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    return f"{minutes // 60}h ago"


def build_sources(args) -> List:
    sources: List = []
    source_started_at = datetime.now(timezone.utc)
    if args.demo:
        sources.append(DemoSource())
    session_dir = Path(args.session_dir or os.environ.get("AI_PROGRESS_MONITOR_HOME", Path.home() / ".ai-progress-monitor" / "sessions"))
    sources.append(JsonSessionSource(session_dir, source_started_at=source_started_at))
    sources.append(CodexSessionSource(source_started_at=source_started_at))
    if not args.no_windows:
        sources.append(OsWindowSource())
    return sources


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Low-intrusion Claude Code and Codex progress monitor")
    parser.add_argument("--demo", action="store_true", help="Show sample Claude Code and Codex sessions")
    parser.add_argument("--session-dir", help="Directory containing JSON session files")
    parser.add_argument("--no-windows", action="store_true", help="Disable OS window scanning")
    parser.add_argument("--poll-ms", type=int, default=3000, help="Refresh interval in milliseconds")
    args = parser.parse_args(argv)

    store = SessionStore()
    app = ProgressPetApp(build_sources(args), store, ActionExecutor(), poll_ms=args.poll_ms)
    app.run()
    return 0
