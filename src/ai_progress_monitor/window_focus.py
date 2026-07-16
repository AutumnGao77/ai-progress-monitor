from __future__ import annotations

import platform
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional


@dataclass(frozen=True)
class FocusResult:
    ok: bool
    detail: str


@dataclass(frozen=True)
class FocusTarget:
    title: str
    window_id: Optional[str] = None
    process_id: Optional[int] = None
    app_name: Optional[str] = None
    cwd: Optional[str] = None


FocusSender = Callable[[FocusTarget], FocusResult]
FOCUS_COMMAND_TIMEOUT_SECONDS = 5
FOCUS_FALLBACK_TIMEOUT_SECONDS = 15
PROJECT_EDITOR_APP_NAMES = {
    "android studio",
    "clion",
    "code",
    "cursor",
    "nova",
    "sublime text",
    "windsurf",
    "xcode",
    "zed",
}
PROJECT_EDITOR_APP_PREFIXES = (
    "goland",
    "intellij idea",
    "phpstorm",
    "pycharm",
    "rider",
    "rubymine",
    "visual studio code",
    "webstorm",
)
AI_DESKTOP_APP_NAMES = {
    "chatgpt",
    "claude",
    "codex",
    "gemini",
    "kiro",
    "perplexity",
    "poe",
    "qoder",
    "qoder cn",
    "workbuddy",
}
SAFE_FOCUS_METHODS = {
    "activated-app",
    "focused-process",
    "focused-project-window",
    "focused-title-window",
    "focused-window",
    "focused-window-id",
}


class WindowFocusManager:
    def __init__(self, sender: Optional[FocusSender] = None):
        self.sender = sender or focus_native_window

    def focus(
        self,
        title: str,
        window_id: Optional[str] = None,
        process_id: Optional[int] = None,
        app_name: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> FocusResult:
        if not title.strip():
            return FocusResult(False, "Window title is empty")
        return self.sender(FocusTarget(title=title, window_id=window_id, process_id=process_id, app_name=app_name, cwd=cwd))


def focus_native_window(target: FocusTarget) -> FocusResult:
    command = build_focus_command(target)
    if command is None:
        return FocusResult(False, "Window focusing is not supported on this platform")
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=FOCUS_COMMAND_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return FocusResult(False, str(exc))
    if completed.returncode == 0 and _focus_output_indicates_success(completed.stdout):
        return FocusResult(True, _focus_success_detail(completed.stdout))
    detail = completed.stderr.strip() or completed.stdout.strip() or f"Focus command exited with {completed.returncode}"
    fallback = focus_fallback_command(target)
    if fallback is not None:
        try:
            fallback_result = subprocess.run(fallback, check=False, capture_output=True, text=True, timeout=FOCUS_FALLBACK_TIMEOUT_SECONDS)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return FocusResult(False, f"{detail}; fallback failed: {exc}")
        if fallback_result.returncode == 0:
            return FocusResult(True, "activated-app")
        fallback_detail = fallback_result.stderr.strip() or fallback_result.stdout.strip() or f"fallback exited with {fallback_result.returncode}"
        detail = f"{detail}; fallback failed: {fallback_detail}"
    return FocusResult(False, detail)


def build_focus_command(target: FocusTarget) -> Optional[List[str]]:
    system = platform.system().lower()
    if system == "darwin":
        return build_macos_focus_command(target)
    if system == "windows":
        return build_windows_focus_command(target)
    return None


def build_macos_focus_command(target) -> List[str]:
    if isinstance(target, str):
        target = FocusTarget(title=target)
    escaped = _escape_applescript(target.title)
    escaped_app_name = _escape_applescript(target.app_name) if target.app_name else ""
    process_condition = ""
    if target.process_id is not None and not target.cwd:
        escaped_process_id = _escape_applescript(str(target.process_id))
        process_condition = f'if unix id of proc as string is "{escaped_process_id}" then\n'
        process_condition += "set frontmost of proc to true\n"
        process_condition += "try\n"
        process_condition += "if (count of windows of proc) > 0 then\n"
        process_condition += 'perform action "AXRaise" of window 1 of proc\n'
        process_condition += "end if\n"
        process_condition += "end try\n"
        process_condition += 'return "focused-process"\n'
        process_condition += "end if\n"
    id_condition = ""
    if target.window_id:
        escaped_id = _escape_applescript(str(target.window_id))
        id_condition = f'if id of win as string is "{escaped_id}" then\n'
        id_condition += 'perform action "AXRaise" of win\n'
        id_condition += 'return "focused-window-id"\n'
        id_condition += "end if\n"
    cwd_name_condition = ""
    if target.cwd:
        folder_name = Path(target.cwd).name
        if folder_name:
            escaped_folder_name = _escape_applescript(folder_name)
            cwd_name_condition = f'if name of win is "{escaped_folder_name}" or name of win contains "{escaped_folder_name}" then\n'
            cwd_name_condition += 'perform action "AXRaise" of win\n'
            cwd_name_condition += 'return "focused-project-window"\n'
            cwd_name_condition += "end if\n"
    if escaped_app_name:
        direct_process_condition = ""
        if target.process_id is not None and not target.cwd:
            escaped_process_id = _escape_applescript(str(target.process_id))
            direct_process_condition = f'if unix id as string is "{escaped_process_id}" then\n'
            direct_process_condition += "set frontmost to true\n"
            direct_process_condition += "try\n"
            direct_process_condition += "if (count of windows) > 0 then\n"
            direct_process_condition += 'perform action "AXRaise" of window 1\n'
            direct_process_condition += "end if\n"
            direct_process_condition += "end try\n"
            direct_process_condition += 'return "focused-process"\n'
            direct_process_condition += "end if\n"
        script = (
            'tell application "System Events"\n'
            f'tell application process "{escaped_app_name}"\n'
            f"{direct_process_condition}"
            "repeat with win in windows\n"
            "try\n"
            f"{id_condition}"
            f"{cwd_name_condition}"
            f'if name of win contains "{escaped}" then\n'
            "perform action \"AXRaise\" of win\n"
            "return \"focused-title-window\"\n"
            "end if\n"
            "end try\n"
            "end repeat\n"
            "end tell\n"
            'error "not found" number 1\n'
            "end tell"
        )
        return ["osascript", "-e", script]
    script = (
        'tell application "System Events"\n'
        "repeat with proc in application processes\n"
        f"{process_condition}"
        "repeat with win in windows of proc\n"
        "try\n"
        f"{id_condition}"
        f"{cwd_name_condition}"
        f'if name of win contains "{escaped}" then\n'
        "perform action \"AXRaise\" of win\n"
        "return \"focused-title-window\"\n"
        "end if\n"
        "end try\n"
        "end repeat\n"
        "end repeat\n"
        'error "not found" number 1\n'
        "end tell"
    )
    return ["osascript", "-e", script]


def focus_fallback_command(target: FocusTarget) -> Optional[List[str]]:
    system = platform.system().lower()
    if system == "darwin" and target.app_name:
        if target.cwd:
            if _is_project_editor_app(target.app_name):
                return None
            if _is_ai_desktop_app(target.app_name):
                return build_macos_activate_app_command(target.app_name)
            return build_macos_open_path_in_app_command(target.app_name, target.cwd)
        return build_macos_activate_app_command(target.app_name)
    return None


def build_macos_activate_app_command(app_name: str) -> List[str]:
    return ["open", "-a", app_name]


def build_macos_open_path_in_app_command(app_name: str, path: str) -> List[str]:
    return ["open", "-a", app_name, path]


def build_windows_focus_command(target) -> List[str]:
    if isinstance(target, str):
        target = FocusTarget(title=target)
    escaped = _escape_powershell(target.title)
    process_lookup = (
        f"$p = Get-Process -Id {target.process_id} -ErrorAction SilentlyContinue;\n"
        if target.process_id is not None
        else f"$p = Get-Process | Where-Object {{ $_.MainWindowTitle -like '*{escaped}*' }} | Select-Object -First 1;\n"
    )
    script = (
        "Add-Type @\"\n"
        "using System;\n"
        "using System.Runtime.InteropServices;\n"
        "public class Win32 { [DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr hWnd); }\n"
        "\"@;\n"
        f"{process_lookup}"
        "if ($p) { [Win32]::SetForegroundWindow($p.MainWindowHandle) | Out-Null; 'focused-process' } else { 'not found'; exit 1 }"
    )
    return ["powershell", "-NoProfile", "-Command", script]


def _escape_applescript(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _escape_powershell(value: str) -> str:
    return value.replace("'", "''")


def _is_project_editor_app(app_name: str) -> bool:
    normalized = app_name.strip().lower()
    return normalized in PROJECT_EDITOR_APP_NAMES or any(normalized.startswith(prefix) for prefix in PROJECT_EDITOR_APP_PREFIXES)


def _is_ai_desktop_app(app_name: str) -> bool:
    return app_name.strip().lower() in AI_DESKTOP_APP_NAMES


def _focus_success_detail(output: str) -> str:
    for match in re.findall(r"focused[-a-z]*|activated-app", output.lower()):
        if match in SAFE_FOCUS_METHODS:
            return match
    return "focused-window"


def _focus_output_indicates_success(output: str) -> bool:
    return "focused" in output.lower()
