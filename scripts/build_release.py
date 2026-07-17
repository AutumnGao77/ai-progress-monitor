#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import sys
import zipapp
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
ARTIFACT = DIST / "ai-progress-monitor.pyz"
RELEASE_DIR = DIST / "ai-progress-monitor"
RELEASE_ZIP = DIST / "ai-progress-monitor-release.zip"
APP_AVATAR = ROOT / "src" / "ai_progress_monitor" / "assets" / "app-avatar.png"
VERSION_FILE = ROOT / "src" / "ai_progress_monitor" / "__init__.py"
RELEASE_FILES = (
    "scripts/emit_event.py",
    "scripts/e2e_smoke.py",
    "scripts/doctor.py",
    "scripts/monitor_command.py",
    "scripts/monitor_claude.sh",
    "scripts/monitor_codex.sh",
    "scripts/monitor_qoder.sh",
    "scripts/monitor_workbuddy.sh",
    "scripts/monitor_claude.bat",
    "scripts/monitor_codex.bat",
    "scripts/monitor_qoder.bat",
    "scripts/monitor_workbuddy.bat",
    "scripts/run_web_demo.sh",
    "scripts/run_web_demo.bat",
    "scripts/start_monitor.sh",
    "scripts/start_monitor.bat",
    "scripts/start_floating_monitor.bat",
    "native/windows/FloatingMonitor.ps1",
)


def load_release_version(version_file: Path = VERSION_FILE) -> str:
    match = re.search(
        r'^__version__\s*=\s*["\']([^"\']+)["\']\s*$',
        version_file.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if match is None:
        raise RuntimeError(f"release version not found in {version_file}")
    return match.group(1)


RELEASE_VERSION = load_release_version()


def include_pyz_path(path: Path) -> bool:
    if path.name == ".DS_Store" or "__pycache__" in path.parts:
        return False
    if "sloth-candidates" in path.parts:
        return False
    try:
        relative = path.relative_to(ROOT / "src")
    except ValueError:
        return True
    parts = relative.parts
    if len(parts) >= 3 and parts[:3] == ("ai_progress_monitor", "assets", "sloth-candidates"):
        return False
    return True


def write_png_icns(source_png: Path, target_icns: Path) -> None:
    png = source_png.read_bytes()
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"app icon source is not a PNG: {source_png}")
    chunk = b"ic10" + struct.pack(">I", len(png) + 8) + png
    target_icns.write_bytes(b"icns" + struct.pack(">I", len(chunk) + 8) + chunk)


def copy_app_icon_resources(resources: Path) -> None:
    if not APP_AVATAR.exists():
        return
    shutil.copy2(APP_AVATAR, resources / "app-avatar.png")
    write_png_icns(APP_AVATAR, resources / "AppIcon.icns")


def main() -> int:
    run([sys.executable, "scripts/validate_release.py"])
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)
    zipapp.create_archive(
        ROOT / "src",
        target=ARTIFACT,
        main="ai_progress_monitor.web:main",
        interpreter="/usr/bin/env python3",
        filter=include_pyz_path,
        compressed=True,
    )
    run([sys.executable, str(ARTIFACT), "--help"])
    run([sys.executable, "scripts/e2e_smoke.py", "--artifact", str(ARTIFACT)])
    build_release_bundle()
    verify_release_bundle()
    print(f"release-artifact-ok {ARTIFACT}")
    print(f"release-bundle-ok {RELEASE_ZIP}")
    return 0


def run(command: list[str]) -> None:
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if completed.returncode != 0:
        print(completed.stdout, file=sys.stderr)
        print(completed.stderr, file=sys.stderr)
        raise SystemExit(completed.returncode)


def sign_macos_app_bundle(app_path: Path) -> None:
    codesign = shutil.which("codesign")
    if not codesign:
        return
    run([codesign, "--force", "--deep", "--sign", "-", str(app_path)])


def build_release_bundle() -> None:
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ARTIFACT, RELEASE_DIR / ARTIFACT.name)
    create_macos_app_bundle(RELEASE_DIR / "AI Progress Monitor.app")
    create_macos_floating_app_bundle(RELEASE_DIR / "AI Progress Monitor Floating.app")
    scripts_dir = RELEASE_DIR / "scripts"
    scripts_dir.mkdir()
    for relative in RELEASE_FILES:
        source = ROOT / relative
        target = RELEASE_DIR / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    (RELEASE_DIR / "README.txt").write_text(
        "\n".join(
            [
                "AI Progress Monitor",
                f"Version: {RELEASE_VERSION}",
                "",
                "Requirements:",
                "  Python 3.9+ is required for this release package.",
                "  On macOS, double-clicking the bundled apps uses /usr/bin/env python3.",
                "",
                "Run demo:",
                "  python3 ai-progress-monitor.pyz --demo --no-windows",
                "",
                "Run release smoke test:",
                "  python3 scripts/e2e_smoke.py --artifact ai-progress-monitor.pyz",
                "",
                "Run and open browser automatically:",
                "  sh scripts/start_monitor.sh --demo --no-windows",
                "  scripts\\start_monitor.bat --demo --no-windows",
                "  Double-click AI Progress Monitor.app on macOS",
                "  Double-click AI Progress Monitor Floating.app on macOS for an always-on-top companion window",
                "  Double-click scripts\\start_floating_monitor.bat on Windows for an always-on-top companion window",
                "",
                "Startup logs:",
                "  macOS: ~/Library/Logs/AI Progress Monitor/monitor.log",
                "  Windows: %LOCALAPPDATA%\\AI Progress Monitor\\monitor.log",
                "",
                "Pet visual assets:",
                "  Built-in state images are served at /assets/pet/idle.png, /assets/pet/running.png, and /assets/pet/needs-action.png.",
                "  Right-click Pet -> Appearance to switch between the default three-state sloth and the shirt sloth.",
                "  The shirt sloth theme uses /assets/pet/shirt.png for idle, running, and needs-action states.",
                "  The app avatar is served at /assets/app-avatar.png.",
                "  macOS app bundles include app-avatar.png and AppIcon.icns; the menu bar item uses the avatar icon instead of AI text.",
                "  To replace only the visual appearance, set local paths in ~/.ai-progress-monitor/preferences.json.",
                "  Supported keys are pet_assets.idle, pet_assets.running, pet_assets.needs_action, and pet_assets.app_avatar.",
                "  Invalid, unsupported, or oversized image files fall back to the bundled assets.",
                "  Keep Pet image backgrounds transparent for the native floating window.",
                "",
                "Then open:",
                "  Use the URL printed by the launcher. If 8765 is busy, the app uses the next available port.",
                "",
                "Direct configured AI CLI detection:",
                "  If you run a configured AI CLI directly, the monitor shows a process-only bubble while the CLI is still interactive.",
                "  Claude Code prefers its local session state: running stays running, quiet idle stays idle, and a freshly completed reply becomes needs-action until you click its bubble.",
                "  Codex, Qoder, WorkBuddy, codebuddy, and other generic CLI tools are currently classified conservatively by process activity unless they use a wrapper or JSON event source.",
                "  ChatGPT Desktop sessions are read from the compatible ~/.codex/sessions event directory when available.",
                "  Qoder Desktop sessions are read from local Qoder/Qoder CN logs when available.",
                "  WorkBuddy Desktop sessions are read from explicit local WorkBuddy session database states when available; ambiguous blank Pending sessions stay as the desktop idle entry.",
                "  A viewed desktop conversation stays idle for 15 minutes, then leaves the bubble list; if the desktop app is still alive, the app idle entry remains.",
                "  Clicking the bubble and successfully returning to the terminal marks that reply as viewed.",
                "  Process-only detection does not display terminal content.",
                "  For detailed prompt text and scripted integrations, use the wrapper scripts below.",
                "  Run wrapper commands from the project folder you want the AI tool to work in.",
                "  If AI_MONITOR_SESSION_ID is omitted, wrappers generate a unique session ID per run.",
                "",
                "Wrap Claude Code on macOS/Linux:",
                "  AI_MONITOR_SESSION_ID=demo-1 AI_MONITOR_TITLE='Claude Code - demo-1' sh scripts/monitor_claude.sh claude",
                "",
                "Wrap Codex on macOS/Linux:",
                "  AI_MONITOR_SESSION_ID=demo-1 AI_MONITOR_TITLE='Codex - demo-1' sh scripts/monitor_codex.sh codex",
                "",
                "Wrap Qoder on macOS/Linux:",
                "  AI_MONITOR_SESSION_ID=demo-1 AI_MONITOR_TITLE='Qoder - demo-1' sh scripts/monitor_qoder.sh qoder",
                "",
                "Wrap WorkBuddy on macOS/Linux:",
                "  AI_MONITOR_SESSION_ID=demo-1 AI_MONITOR_TITLE='WorkBuddy - demo-1' sh scripts/monitor_workbuddy.sh workbuddy",
                "",
                "Useful paths and options:",
                "  AI_PROGRESS_MONITOR_HOME controls the sessions/ and responses/ folders.",
                "  --session-dir reads JSON session files from a custom folder.",
                "  --response-dir writes wrapper response files for integration tests and future adapters.",
                "",
                "The local API is protected by a startup token embedded in the page.",
                "",
                "Public release note:",
                "  This package is built locally and is not notarized by Apple.",
                "  GitHub users may need to allow the macOS app in System Settings after download.",
                "  The app runs locally and does not upload session content.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    with zipfile.ZipFile(RELEASE_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(RELEASE_DIR.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(DIST))


def verify_release_bundle() -> None:
    required = {
        "ai-progress-monitor/ai-progress-monitor.pyz",
        "ai-progress-monitor/README.txt",
        "ai-progress-monitor/AI Progress Monitor.app/Contents/Info.plist",
        "ai-progress-monitor/AI Progress Monitor.app/Contents/MacOS/AI Progress Monitor",
        "ai-progress-monitor/AI Progress Monitor.app/Contents/Resources/ai-progress-monitor.pyz",
        "ai-progress-monitor/AI Progress Monitor.app/Contents/Resources/app-avatar.png",
        "ai-progress-monitor/AI Progress Monitor.app/Contents/Resources/AppIcon.icns",
        "ai-progress-monitor/AI Progress Monitor Floating.app/Contents/Info.plist",
        "ai-progress-monitor/AI Progress Monitor Floating.app/Contents/MacOS/AI Progress Monitor Floating",
        "ai-progress-monitor/AI Progress Monitor Floating.app/Contents/Resources/ai-progress-monitor.pyz",
        "ai-progress-monitor/AI Progress Monitor Floating.app/Contents/Resources/app-avatar.png",
        "ai-progress-monitor/AI Progress Monitor Floating.app/Contents/Resources/AppIcon.icns",
        "ai-progress-monitor/AI Progress Monitor Floating.app/Contents/Resources/FloatingMonitor.swift",
        "ai-progress-monitor/AI Progress Monitor Floating.app/Contents/Resources/FloatingMonitorGeometry.swift",
        "ai-progress-monitor/native/windows/FloatingMonitor.ps1",
        "ai-progress-monitor/scripts/monitor_command.py",
        "ai-progress-monitor/scripts/doctor.py",
        "ai-progress-monitor/scripts/e2e_smoke.py",
        "ai-progress-monitor/scripts/monitor_claude.sh",
        "ai-progress-monitor/scripts/monitor_codex.sh",
        "ai-progress-monitor/scripts/monitor_qoder.sh",
        "ai-progress-monitor/scripts/monitor_workbuddy.sh",
        "ai-progress-monitor/scripts/monitor_claude.bat",
        "ai-progress-monitor/scripts/monitor_codex.bat",
        "ai-progress-monitor/scripts/monitor_qoder.bat",
        "ai-progress-monitor/scripts/monitor_workbuddy.bat",
        "ai-progress-monitor/scripts/start_monitor.sh",
        "ai-progress-monitor/scripts/start_monitor.bat",
        "ai-progress-monitor/scripts/start_floating_monitor.bat",
    }
    with zipfile.ZipFile(RELEASE_ZIP) as archive:
        names = set(archive.namelist())
    missing = sorted(required - names)
    if missing:
        raise SystemExit(f"release bundle missing files: {missing}")


def create_macos_app_bundle(app_path: Path) -> None:
    contents = app_path / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ARTIFACT, resources / ARTIFACT.name)
    copy_app_icon_resources(resources)
    launcher = macos / "AI Progress Monitor"
    launcher.write_text(
        "\n".join(
            [
                "#!/usr/bin/env sh",
                "set -eu",
                'APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"',
                'PYZ="$APP_DIR/Resources/ai-progress-monitor.pyz"',
                'LOG_DIR="${HOME}/Library/Logs/AI Progress Monitor"',
                'LOG_FILE="$LOG_DIR/monitor.log"',
                'mkdir -p "$LOG_DIR"',
                'printf "\\n[%s] Starting AI Progress Monitor\\n" "$(date -u \'+%Y-%m-%dT%H:%M:%SZ\')" >>"$LOG_FILE"',
                'exec /usr/bin/env python3 "$PYZ" --open "$@" >>"$LOG_FILE" 2>&1',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    (contents / "Info.plist").write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>AI Progress Monitor</string>
  <key>CFBundleDisplayName</key>
  <string>AI Progress Monitor</string>
  <key>CFBundleIdentifier</key>
  <string>local.ai-progress-monitor</string>
  <key>CFBundleVersion</key>
  <string>{RELEASE_VERSION}</string>
  <key>CFBundleShortVersionString</key>
  <string>{RELEASE_VERSION}</string>
  <key>CFBundleExecutable</key>
  <string>AI Progress Monitor</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>LSUIElement</key>
  <true/>
</dict>
</plist>
""",
        encoding="utf-8",
    )
    sign_macos_app_bundle(app_path)


def create_macos_floating_app_bundle(app_path: Path) -> None:
    contents = app_path / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ARTIFACT, resources / ARTIFACT.name)
    copy_app_icon_resources(resources)
    source = ROOT / "native" / "macos" / "FloatingMonitor.swift"
    geometry_source = ROOT / "native" / "macos" / "FloatingMonitorGeometry.swift"
    shutil.copy2(source, resources / "FloatingMonitor.swift")
    shutil.copy2(geometry_source, resources / "FloatingMonitorGeometry.swift")
    executable = macos / "AI Progress Monitor Floating"
    swiftc = shutil.which("swiftc")
    if swiftc:
        env = os.environ.copy()
        env.setdefault("CLANG_MODULE_CACHE_PATH", "/private/tmp/ai-progress-monitor-clang-cache")
        env.setdefault("SWIFT_MODULE_CACHE_PATH", "/private/tmp/ai-progress-monitor-swift-cache")
        completed = subprocess.run(
            [
                swiftc,
                str(source),
                str(geometry_source),
                "-o",
                str(executable),
                "-framework",
                "Cocoa",
                "-framework",
                "WebKit",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0:
            executable.chmod(0o755)
        else:
            executable.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env sh",
                        "set -eu",
                        'APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"',
                        'NOTE="$APP_DIR/Resources/BUILD_FLOATING_APP.txt"',
                        'open -a TextEdit "$NOTE" 2>/dev/null || cat "$NOTE"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
            (resources / "BUILD_FLOATING_APP.txt").write_text(
                "Swift compilation did not succeed on this machine. Build with a matching Xcode/Swift toolchain:\n"
                "swiftc FloatingMonitor.swift FloatingMonitorGeometry.swift -o '../MacOS/AI Progress Monitor Floating' -framework Cocoa -framework WebKit\n",
                encoding="utf-8",
            )
    (contents / "Info.plist").write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>AI Progress Monitor Floating</string>
  <key>CFBundleDisplayName</key>
  <string>AI Progress Monitor Floating</string>
  <key>CFBundleIdentifier</key>
  <string>local.ai-progress-monitor.floating</string>
  <key>CFBundleVersion</key>
  <string>{RELEASE_VERSION}</string>
  <key>CFBundleShortVersionString</key>
  <string>{RELEASE_VERSION}</string>
  <key>CFBundleExecutable</key>
  <string>AI Progress Monitor Floating</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>LSUIElement</key>
  <true/>
</dict>
</plist>
""",
        encoding="utf-8",
    )
    sign_macos_app_bundle(app_path)


if __name__ == "__main__":
    raise SystemExit(main())
