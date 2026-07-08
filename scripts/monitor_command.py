#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
import fcntl
import os
import queue
import select
import subprocess
import sys
import termios
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_progress_monitor.terminal_bridge import TerminalBridge


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Claude Code or Codex terminal command with monitor integration")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--tool", choices=("claude_code", "codex", "unknown"), required=True)
    monitor_home = default_monitor_home()
    parser.add_argument("--session-dir", default=str(default_session_dir(monitor_home)))
    parser.add_argument("--response-dir", default=str(default_response_dir(monitor_home)))
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run after --")
    args = parser.parse_args()

    command = normalize_command(args.command)
    if not command:
        parser.error("missing command after --")

    bridge = TerminalBridge(
        session_id=args.session_id,
        title=args.title,
        tool=args.tool,
        session_dir=Path(args.session_dir),
        response_dir=Path(args.response_dir),
    )
    bridge.mark_running("Starting command")
    exit_code = run_monitored_command(command, bridge)
    bridge.mark_finished(exit_code)
    return exit_code


def normalize_command(command: List[str]) -> List[str]:
    if command and command[0] == "--":
        return command[1:]
    return command


def default_monitor_home() -> Path:
    return Path(os.environ.get("AI_PROGRESS_MONITOR_HOME") or Path.home() / ".ai-progress-monitor")


def default_session_dir(monitor_home: Path) -> Path:
    return monitor_home / "sessions"


def default_response_dir(monitor_home: Path) -> Path:
    return monitor_home / "responses"


def run_monitored_command(
    command: List[str],
    bridge: TerminalBridge,
    use_pty: Optional[bool] = None,
    terminal_input_fd: Optional[int] = None,
) -> int:
    if use_pty is None:
        use_pty = os.name == "posix"
    if use_pty:
        return _run_pty_command(command, bridge, terminal_input_fd)
    return _run_piped_command(command, bridge)


def _run_piped_command(command: List[str], bridge: TerminalBridge) -> int:
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )
    focus_process_id, focus_app_name = detect_focus_app_for_process(process.pid)
    bridge.set_process_metadata(
        process.pid,
        Path(command[0]).name if command else None,
        focus_process_id=focus_process_id,
        focus_app_name=focus_app_name,
    )
    bridge.mark_running("Starting command")
    output_queue: queue.Queue[str] = queue.Queue()
    reader = threading.Thread(target=_read_output, args=(process, output_queue), daemon=True)
    reader.start()

    def drain_output() -> None:
        while not output_queue.empty():
            line = output_queue.get()
            print(line, end="", flush=True)
            bridge.process_output(line)

    while process.poll() is None or not output_queue.empty():
        drain_output()
        response = bridge.consume_response()
        if response and process.stdin:
            process.stdin.write(response + os.linesep)
            process.stdin.flush()
        time.sleep(0.1)

    reader.join(timeout=2)
    drain_output()
    if process.stdin:
        process.stdin.close()
    if process.stdout:
        process.stdout.close()
    return process.returncode if process.returncode is not None else 1


def _run_pty_command(command: List[str], bridge: TerminalBridge, terminal_input_fd: Optional[int] = None) -> int:
    import pty

    master_fd, slave_fd = pty.openpty()
    input_fd = terminal_input_fd if terminal_input_fd is not None else _default_terminal_input_fd()
    restore_fd = input_fd
    old_terminal_attrs = _enter_raw_mode(input_fd)
    process = subprocess.Popen(
        command,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        text=False,
        close_fds=True,
        preexec_fn=_make_controlling_terminal(slave_fd),
    )
    focus_process_id, focus_app_name = detect_focus_app_for_process(process.pid)
    bridge.set_process_metadata(
        process.pid,
        Path(command[0]).name if command else None,
        focus_process_id=focus_process_id,
        focus_app_name=focus_app_name,
    )
    bridge.mark_running("Starting command")
    os.close(slave_fd)

    pending = ""
    try:
        while process.poll() is None:
            read_fds = [master_fd]
            if input_fd is not None:
                read_fds.append(input_fd)
            ready, _, _ = select.select(read_fds, [], [], 0.1)
            if master_fd in ready:
                pending, closed = _read_pty_output(master_fd, bridge, pending)
                if closed:
                    break
            if input_fd is not None and input_fd in ready:
                input_fd = _forward_terminal_input(input_fd, master_fd)
            response = bridge.consume_response()
            if response:
                os.write(master_fd, (response + os.linesep).encode("utf-8"))

        while True:
            ready, _, _ = select.select([master_fd], [], [], 0)
            if not ready:
                break
            pending, closed = _read_pty_output(master_fd, bridge, pending)
            if closed:
                break
    finally:
        _restore_terminal(restore_fd, old_terminal_attrs)
        os.close(master_fd)

    process.wait()
    if pending:
        bridge.process_output(pending)
    return process.returncode if process.returncode is not None else 1


def _make_controlling_terminal(slave_fd: int):
    def configure_child() -> None:
        os.setsid()
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

    return configure_child


def _default_terminal_input_fd() -> Optional[int]:
    try:
        fd = sys.stdin.fileno()
    except (AttributeError, OSError):
        return None
    return fd if os.isatty(fd) else None


def _enter_raw_mode(input_fd: Optional[int]) -> Optional[list]:
    if input_fd is None or not os.isatty(input_fd):
        return None
    import termios
    import tty

    old_attrs = termios.tcgetattr(input_fd)
    tty.setraw(input_fd)
    return old_attrs


def _restore_terminal(input_fd: Optional[int], old_attrs: Optional[list]) -> None:
    if input_fd is None or old_attrs is None:
        return
    import termios

    termios.tcsetattr(input_fd, termios.TCSADRAIN, old_attrs)


def _forward_terminal_input(input_fd: int, master_fd: int) -> Optional[int]:
    data = os.read(input_fd, 4096)
    if not data:
        return None
    os.write(master_fd, data)
    return input_fd


def _read_pty_output(master_fd: int, bridge: TerminalBridge, pending: str) -> tuple[str, bool]:
    try:
        chunk = os.read(master_fd, 4096)
    except OSError as exc:
        if exc.errno == errno.EIO:
            return pending, True
        raise
    if not chunk:
        return pending, True

    text = chunk.decode("utf-8", errors="replace")
    print(text, end="", flush=True)
    pending += text
    lines = pending.splitlines(keepends=True)
    if lines and not lines[-1].endswith(("\n", "\r")):
        pending = lines.pop()
    else:
        pending = ""
    for line in lines:
        bridge.process_output(line)
    return pending, False


def _read_output(process: subprocess.Popen, output_queue: queue.Queue[str]) -> None:
    if process.stdout is None:
        return
    for line in process.stdout:
        output_queue.put(line)


def detect_focus_app_for_process(process_id: int) -> Tuple[Optional[int], Optional[str]]:
    if os.name != "posix":
        return None, None
    try:
        completed = subprocess.run(
            ["ps", "axo", "pid=,ppid=,args="],
            check=False,
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    if completed.returncode != 0:
        return None, None
    return detect_focus_app_from_process_rows(process_id, completed.stdout.splitlines())


def detect_focus_app_from_process_rows(process_id: int, rows: List[str]) -> Tuple[Optional[int], Optional[str]]:
    process_table = {}
    for row in rows:
        parts = row.strip().split(None, 2)
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        process_table[pid] = (ppid, parts[2])

    current = process_id
    for _ in range(8):
        entry = process_table.get(current)
        if entry is None:
            return None, None
        parent_id, args = entry
        app_name = focus_app_name_from_args(args)
        if app_name is not None:
            return current, app_name
        if parent_id <= 1 or parent_id == current:
            return None, None
        current = parent_id
    return None, None


def focus_app_name_from_args(args: str) -> Optional[str]:
    markers = [
        ("/Terminal.app/", "Terminal"),
        ("/iTerm.app/", "iTerm"),
        ("/iTerm2.app/", "iTerm"),
        ("/Warp.app/", "Warp"),
        ("/WezTerm.app/", "WezTerm"),
        ("/kitty.app/", "kitty"),
        ("/Alacritty.app/", "Alacritty"),
        ("/Zed.app/", "Zed"),
        ("/Cursor.app/", "Cursor"),
        ("/Visual Studio Code.app/", "Visual Studio Code"),
        ("/Codex.app/", "Codex"),
    ]
    for marker, app_name in markers:
        if marker in args:
            return app_name
    return None


if __name__ == "__main__":
    raise SystemExit(main())
