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
APP_AVATAR = ROOT / "src" / "ai_progress_monitor" / "assets" / "app-avatar.png"
VERSION_FILE = ROOT / "src" / "ai_progress_monitor" / "__init__.py"
LICENSE_FILE = ROOT / "LICENSE"
PORTABLE_FILES = (
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
MACOS_MINIMUM_VERSION = "13.0"
MACOS_RELEASE_DIR = DIST / f"AI Progress Monitor v{RELEASE_VERSION} macOS arm64"
MACOS_RELEASE_ZIP = DIST / f"AI-Progress-Monitor-v{RELEASE_VERSION}-macOS-arm64.zip"
PORTABLE_RELEASE_DIR = DIST / f"ai-progress-monitor-v{RELEASE_VERSION}-portable"
PORTABLE_RELEASE_ZIP = DIST / f"ai-progress-monitor-v{RELEASE_VERSION}-portable.zip"


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
    build_release_bundles()
    verify_release_bundles()
    print(f"release-artifact-ok {ARTIFACT}")
    print(f"macos-release-ok {MACOS_RELEASE_ZIP}")
    print(f"portable-release-ok {PORTABLE_RELEASE_ZIP}")
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
        raise SystemExit("codesign is required to build the signed macOS release app")
    run([codesign, "--force", "--deep", "--sign", "-", str(app_path)])


def build_release_bundles() -> None:
    build_macos_release_bundle()
    build_portable_release_bundle()


def build_macos_release_bundle() -> None:
    MACOS_RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    create_macos_app_bundle(MACOS_RELEASE_DIR / "AI Progress Monitor.app")
    shutil.copy2(LICENSE_FILE, MACOS_RELEASE_DIR / "LICENSE")
    (MACOS_RELEASE_DIR / "README.txt").write_text(
        "\n".join(
            [
                "AI Progress Monitor for macOS (Apple silicon)",
                f"Version: {RELEASE_VERSION}",
                "",
                "Start here:",
                "  1. Python 3.9+ is required. Check with: python3 --version",
                "  2. Double-click AI Progress Monitor.app.",
                "  3. The Pet stays on top; closing hides it. Restore or quit from the menu bar avatar.",
                "",
                "Compatibility:",
                f"  This package requires macOS {MACOS_MINIMUM_VERSION} or later.",
                "  It contains an arm64 native app for Apple silicon Macs.",
                "  Intel Macs are not supported by this package.",
                "",
                "macOS security:",
                "  This app is ad-hoc signed and is not notarized by Apple.",
                "  If macOS blocks it, Control-click the app and choose Open, or allow it in System Settings > Privacy & Security.",
                "  Do not disable Gatekeeper globally.",
                "",
                "Privacy:",
                "  The app runs locally and does not upload session content.",
                "",
                "Logs:",
                "  ~/Library/Logs/AI Progress Monitor/native-monitor.log",
                "",
                "Advanced CLI, integration scripts, and the Windows preview are distributed separately in the portable package.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    archive_release_directory(MACOS_RELEASE_DIR, MACOS_RELEASE_ZIP)


def build_portable_release_bundle() -> None:
    PORTABLE_RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ARTIFACT, PORTABLE_RELEASE_DIR / ARTIFACT.name)
    shutil.copy2(LICENSE_FILE, PORTABLE_RELEASE_DIR / "LICENSE")
    scripts_dir = PORTABLE_RELEASE_DIR / "scripts"
    scripts_dir.mkdir()
    for relative in PORTABLE_FILES:
        source = ROOT / relative
        target = PORTABLE_RELEASE_DIR / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    (PORTABLE_RELEASE_DIR / "README.txt").write_text(
        "\n".join(
            [
                "AI Progress Monitor",
                f"Version: {RELEASE_VERSION}",
                "",
                "Requirements:",
                "  Python 3.9+ is required for this release package.",
                "  This portable package is intended for CLI integrations, diagnostics, and the Windows preview.",
                "  macOS desktop users should download the separate macOS arm64 package.",
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
                "  The separate macOS package includes app-avatar.png and AppIcon.icns; the menu bar item uses the avatar icon instead of AI text.",
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
                "  The separate macOS package is ad-hoc signed and is not notarized by Apple.",
                "  The app runs locally and does not upload session content.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    archive_release_directory(PORTABLE_RELEASE_DIR, PORTABLE_RELEASE_ZIP)


def archive_release_directory(release_dir: Path, release_zip: Path) -> None:
    with zipfile.ZipFile(release_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(release_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(DIST))


def verify_release_bundles() -> None:
    verify_macos_release_bundle()
    verify_portable_release_bundle()


def verify_macos_release_bundle() -> None:
    root = MACOS_RELEASE_DIR.name
    app_prefix = f"{root}/AI Progress Monitor.app/"
    required = {
        f"{root}/README.txt",
        f"{root}/LICENSE",
        f"{app_prefix}Contents/Info.plist",
        f"{app_prefix}Contents/MacOS/AI Progress Monitor",
        f"{app_prefix}Contents/Resources/ai-progress-monitor.pyz",
        f"{app_prefix}Contents/Resources/app-avatar.png",
        f"{app_prefix}Contents/Resources/AppIcon.icns",
    }
    names = archive_names(MACOS_RELEASE_ZIP)
    assert_archive_contains(MACOS_RELEASE_ZIP, names, required)
    unexpected = sorted(
        name
        for name in names
        if name not in {f"{root}/README.txt", f"{root}/LICENSE"}
        and not name.startswith(app_prefix)
    )
    if unexpected:
        raise SystemExit(f"macOS release contains unexpected files: {unexpected}")
    forbidden = sorted(
        name
        for name in names
        if name.endswith(("FloatingMonitor.swift", "FloatingMonitorGeometry.swift", "BUILD_FLOATING_APP.txt"))
    )
    if forbidden:
        raise SystemExit(f"macOS release contains build-only files: {forbidden}")
    assert_archive_hygiene(MACOS_RELEASE_ZIP, names)


def verify_portable_release_bundle() -> None:
    root = PORTABLE_RELEASE_DIR.name
    required = {
        f"{root}/ai-progress-monitor.pyz",
        f"{root}/README.txt",
        f"{root}/LICENSE",
        f"{root}/native/windows/FloatingMonitor.ps1",
        f"{root}/scripts/monitor_command.py",
        f"{root}/scripts/doctor.py",
        f"{root}/scripts/e2e_smoke.py",
        f"{root}/scripts/monitor_claude.sh",
        f"{root}/scripts/monitor_codex.sh",
        f"{root}/scripts/monitor_qoder.sh",
        f"{root}/scripts/monitor_workbuddy.sh",
        f"{root}/scripts/monitor_claude.bat",
        f"{root}/scripts/monitor_codex.bat",
        f"{root}/scripts/monitor_qoder.bat",
        f"{root}/scripts/monitor_workbuddy.bat",
        f"{root}/scripts/start_monitor.sh",
        f"{root}/scripts/start_monitor.bat",
        f"{root}/scripts/start_floating_monitor.bat",
    }
    names = archive_names(PORTABLE_RELEASE_ZIP)
    assert_archive_contains(PORTABLE_RELEASE_ZIP, names, required)
    app_files = sorted(name for name in names if ".app/" in name)
    if app_files:
        raise SystemExit(f"portable release must not contain macOS app bundles: {app_files}")
    assert_archive_hygiene(PORTABLE_RELEASE_ZIP, names)


def archive_names(release_zip: Path) -> set[str]:
    with zipfile.ZipFile(release_zip) as archive:
        return set(archive.namelist())


def assert_archive_contains(release_zip: Path, names: set[str], required: set[str]) -> None:
    missing = sorted(required - names)
    if missing:
        raise SystemExit(f"release bundle missing files in {release_zip.name}: {missing}")


def assert_archive_hygiene(release_zip: Path, names: set[str]) -> None:
    forbidden = sorted(
        name for name in names if name.endswith(".DS_Store") or "sloth-candidates" in name
    )
    if forbidden:
        raise SystemExit(f"release bundle contains forbidden files in {release_zip.name}: {forbidden}")


def create_macos_app_bundle(app_path: Path) -> None:
    contents = app_path / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ARTIFACT, resources / ARTIFACT.name)
    copy_app_icon_resources(resources)
    executable = macos / "AI Progress Monitor"
    compile_macos_app_executable(executable)
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
  <key>LSMinimumSystemVersion</key>
  <string>{MACOS_MINIMUM_VERSION}</string>
  <key>LSUIElement</key>
  <true/>
</dict>
</plist>
""",
        encoding="utf-8",
    )
    sign_macos_app_bundle(app_path)


def compile_macos_app_executable(executable: Path) -> None:
    source = ROOT / "native" / "macos" / "FloatingMonitor.swift"
    geometry_source = ROOT / "native" / "macos" / "FloatingMonitorGeometry.swift"
    swiftc = shutil.which("swiftc")
    if swiftc is None:
        raise SystemExit("swiftc is required to build the macOS release app")
    env = os.environ.copy()
    env.setdefault("CLANG_MODULE_CACHE_PATH", "/private/tmp/ai-progress-monitor-clang-cache")
    env.setdefault("SWIFT_MODULE_CACHE_PATH", "/private/tmp/ai-progress-monitor-swift-cache")
    completed = subprocess.run(
        [
            swiftc,
            str(source),
            str(geometry_source),
            "-target",
            f"arm64-apple-macos{MACOS_MINIMUM_VERSION}",
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
    if completed.returncode != 0:
        print(completed.stdout, file=sys.stderr)
        print(completed.stderr, file=sys.stderr)
        raise SystemExit("Swift compilation failed for the macOS release app")
    if not executable.exists():
        raise SystemExit("Swift compilation reported success without creating the macOS executable")
    executable.chmod(0o755)


if __name__ == "__main__":
    raise SystemExit(main())
