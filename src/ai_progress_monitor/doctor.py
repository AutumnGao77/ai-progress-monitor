from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional

from .notifier import build_notification_command
from .window_focus import build_focus_command


class CheckStatus(str, Enum):
    OK = "ok"
    WARN = "warn"
    ERROR = "error"


@dataclass(frozen=True)
class DiagnosticCheck:
    name: str
    status: CheckStatus
    detail: str


@dataclass(frozen=True)
class DiagnosticResult:
    checks: List[DiagnosticCheck]

    def exit_code(self) -> int:
        return 1 if any(check.status == CheckStatus.ERROR for check in self.checks) else 0

    def to_text(self) -> str:
        lines = ["AI Progress Monitor diagnostics"]
        for check in self.checks:
            lines.append(f"[{check.status.value.upper()}] {check.name}: {check.detail}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "ok": self.exit_code() == 0,
            "checks": [
                {
                    "name": check.name,
                    "status": check.status.value,
                    "detail": check.detail,
                }
                for check in self.checks
            ],
        }


def run_diagnostics(session_dir: Optional[Path] = None, response_dir: Optional[Path] = None) -> DiagnosticResult:
    session_dir = session_dir or Path.home() / ".ai-progress-monitor" / "sessions"
    response_dir = response_dir or Path.home() / ".ai-progress-monitor" / "responses"
    checks = [
        _python_version_check(),
        DiagnosticCheck("platform", CheckStatus.OK, f"{platform.system()} {platform.release()}"),
        _directory_writable_check("session_dir_writable", session_dir),
        _directory_writable_check("response_dir_writable", response_dir),
        _adapter_check("notification_adapter", build_notification_command("AI Monitor", "test")),
        _adapter_check("window_focus_adapter", build_focus_command("AI Monitor")),
    ]
    return DiagnosticResult(checks)


def _python_version_check() -> DiagnosticCheck:
    version = sys.version_info
    if version >= (3, 9):
        return DiagnosticCheck("python_version", CheckStatus.OK, f"{version.major}.{version.minor}.{version.micro}")
    return DiagnosticCheck("python_version", CheckStatus.ERROR, f"{version.major}.{version.minor}.{version.micro}; Python 3.9+ required")


def _directory_writable_check(name: str, directory: Path) -> DiagnosticCheck:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return DiagnosticCheck(name, CheckStatus.ERROR, str(exc))
    return DiagnosticCheck(name, CheckStatus.OK, str(directory))


def _adapter_check(name: str, command: Optional[List[str]]) -> DiagnosticCheck:
    if command is None:
        return DiagnosticCheck(name, CheckStatus.WARN, "No native adapter for this platform")
    return DiagnosticCheck(name, CheckStatus.OK, " ".join(command[:3]))
