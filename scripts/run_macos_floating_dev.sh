#!/usr/bin/env bash
set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_ROOT="$ROOT_DIR/build/macos-dev"
APP_NAME="AI Progress Monitor Floating Dev.app"
APP_DIR="$BUILD_ROOT/$APP_NAME"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
PYZ="$RESOURCES_DIR/ai-progress-monitor.pyz"
EXECUTABLE="$MACOS_DIR/AI Progress Monitor Floating Dev"
BUILD_ONLY=0
LAUNCH_ONLY=0

for arg in "$@"; do
  case "$arg" in
    --build-only) BUILD_ONLY=1 ;;
    --launch-only) LAUNCH_ONLY=1 ;;
    *)
      printf 'Unknown option: %s\n' "$arg" >&2
      printf 'Usage: %s [--build-only] [--launch-only]\n' "$0" >&2
      exit 2
      ;;
  esac
done

launch_app() {
  pkill -x "AI Progress Monitor Floating" >/dev/null 2>&1 || true
  pkill -x "AI Progress Monitor Floating Dev" >/dev/null 2>&1 || true
  pkill -f "AI Progress Monitor Floating.app/Contents/Resources/ai-progress-monitor.pyz" >/dev/null 2>&1 || true
  pkill -f "AI Progress Monitor Floating Dev.app/Contents/Resources/ai-progress-monitor.pyz" >/dev/null 2>&1 || true
  pkill -f "build/macos-dev/AI Progress Monitor Floating Dev.app/Contents/Resources/ai-progress-monitor.pyz" >/dev/null 2>&1 || true
  /usr/bin/open -n "$APP_DIR"
  printf 'Launched development app. Use the menu bar icon -> Show Monitor to restore after hiding.\n'
}

if [ "$LAUNCH_ONLY" = "1" ]; then
  if [ ! -x "$EXECUTABLE" ]; then
    printf 'Existing development app not found: %s\n' "$APP_DIR" >&2
    printf 'Build it first with: %s --build-only\n' "$0" >&2
    exit 1
  fi
  launch_app
  exit 0
fi

command -v python3 >/dev/null 2>&1 || {
  echo "python3 is required" >&2
  exit 1
}
command -v swiftc >/dev/null 2>&1 || {
  echo "swiftc is required" >&2
  exit 1
}
command -v codesign >/dev/null 2>&1 || {
  echo "codesign is required" >&2
  exit 1
}

rm -rf "$APP_DIR"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"

python3 -m zipapp "$ROOT_DIR/src" \
  --main ai_progress_monitor.web:main \
  --python "/usr/bin/env python3" \
  --compress \
  --output "$PYZ"

cp "$ROOT_DIR/native/macos/FloatingMonitor.swift" "$RESOURCES_DIR/FloatingMonitor.swift"
cp "$ROOT_DIR/native/macos/FloatingMonitorGeometry.swift" "$RESOURCES_DIR/FloatingMonitorGeometry.swift"

APP_AVATAR="$ROOT_DIR/src/ai_progress_monitor/assets/app-avatar.png"
if [ -f "$APP_AVATAR" ]; then
  cp "$APP_AVATAR" "$RESOURCES_DIR/app-avatar.png"
  APP_AVATAR="$APP_AVATAR" APP_ICON="$RESOURCES_DIR/AppIcon.icns" python3 - <<'PY'
import os
import struct
from pathlib import Path

source = Path(os.environ["APP_AVATAR"])
target = Path(os.environ["APP_ICON"])
png = source.read_bytes()
if not png.startswith(b"\x89PNG\r\n\x1a\n"):
    raise SystemExit(f"app icon source is not a PNG: {source}")
chunk = b"ic10" + struct.pack(">I", len(png) + 8) + png
target.write_bytes(b"icns" + struct.pack(">I", len(chunk) + 8) + chunk)
PY
fi

CLANG_MODULE_CACHE_PATH="${CLANG_MODULE_CACHE_PATH:-/private/tmp/ai-progress-monitor-clang-cache}"
SWIFT_MODULE_CACHE_PATH="${SWIFT_MODULE_CACHE_PATH:-/private/tmp/ai-progress-monitor-swift-cache}"
export CLANG_MODULE_CACHE_PATH
export SWIFT_MODULE_CACHE_PATH
mkdir -p "$CLANG_MODULE_CACHE_PATH" "$SWIFT_MODULE_CACHE_PATH"

swiftc "$ROOT_DIR/native/macos/FloatingMonitor.swift" \
  "$ROOT_DIR/native/macos/FloatingMonitorGeometry.swift" \
  -o "$EXECUTABLE" \
  -framework Cocoa \
  -framework WebKit
chmod 755 "$EXECUTABLE"

cat > "$CONTENTS_DIR/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>AI Progress Monitor Floating Dev</string>
  <key>CFBundleDisplayName</key>
  <string>AI Progress Monitor Floating Dev</string>
  <key>CFBundleIdentifier</key>
  <string>local.ai-progress-monitor.floating.dev</string>
  <key>CFBundleVersion</key>
  <string>0.1.0-dev</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0-dev</string>
  <key>CFBundleExecutable</key>
  <string>AI Progress Monitor Floating Dev</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>LSUIElement</key>
  <true/>
</dict>
</plist>
PLIST

codesign --force --deep --sign - "$APP_DIR" >/dev/null

printf 'Built development app: %s\n' "$APP_DIR"

if [ "$BUILD_ONLY" = "1" ]; then
  exit 0
fi

launch_app
