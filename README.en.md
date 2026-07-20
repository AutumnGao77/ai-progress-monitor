# AI Progress Monitor

English | [Chinese](README.md)

[![Validate](https://github.com/AutumnGao77/ai-progress-monitor/actions/workflows/validate.yml/badge.svg)](https://github.com/AutumnGao77/ai-progress-monitor/actions/workflows/validate.yml)

AI Progress Monitor is a local-first, low-interruption desktop companion for tracking AI coding sessions. It watches Claude Code, Codex, and other configured AI tools across terminal and desktop workflows, then shows a small Pet companion when a session is running, idle, or waiting for user action.

The current stable delivery focus is the local Web Companion plus the validated macOS floating companion app. A lightweight Windows floating entry is kept as a preview path, but it has not been accepted as a stable delivery target yet.

## Current Release

| Item | Details |
|---|---|
| Stable release | [v0.2.1](https://github.com/AutumnGao77/ai-progress-monitor/releases/tag/v0.2.1), published on 2026-07-20 |
| macOS package | [Download for macOS 13+ on Apple silicon](https://github.com/AutumnGao77/ai-progress-monitor/releases/download/v0.2.1/AI-Progress-Monitor-v0.2.1-macOS-arm64.zip); Python 3.9+ required |
| Portable package | [Download the portable package](https://github.com/AutumnGao77/ai-progress-monitor/releases/download/v0.2.1/ai-progress-monitor-v0.2.1-portable.zip) for Web/CLI integrations, diagnostics, and the Windows preview |
| Release acceptance | The v0.2.1 baseline passed 445 automated tests; GitHub re-download, first launch, Pet, menu, bubbles, and window focus were manually accepted on 2026-07-20 |

## Features

| Feature | Status |
|---|---|
| Local Web Companion | Supported |
| macOS floating companion | Supported, with a menu bar avatar icon for restore/quit |
| Windows lightweight floating companion | Preview entry, with a WinForms/PowerShell tray path kept in the package; not yet accepted as a stable delivery target |
| Three-state Pet UI | Idle, running, and needs-action images |
| Numeric badge | Shows the total number of visible session bubbles |
| Bubble list | Shows session/tool labels and status without exposing content |
| Click to focus | Clicking a bubble returns to the matching AI tool window when possible |
| Direct CLI detection | Detects configured AI CLI sessions conservatively, including Claude Code, Codex, Qoder, WorkBuddy, and `codebuddy` |
| ChatGPT Desktop session detection | Reads explicitly identified ChatGPT/Codex Desktop-originated events from the compatible local `~/.codex/sessions` store; Codex CLI remains separate |
| Qoder desktop status detection | Reads local Qoder/Qoder CN logs when available and falls back to a desktop idle entry when only the app is running |
| WorkBuddy desktop status detection | Reads explicit local WorkBuddy session database states when available and falls back to a desktop idle entry when only the app is running |
| JSON event source | Supported for reliable integrations |
| Local notifications | Optional needs-action notifications |
| Asset overrides | Configurable Pet and app avatar images |

## Requirements

- Python 3.9+
- No third-party runtime dependencies
- macOS for the validated native floating companion app
- Windows can run the Web Companion and the lightweight preview scripts, but it is not the current stable delivery focus

## Quick Start

Run the demo Web Companion:

```bash
PYTHONPATH=src python3 -m ai_progress_monitor --demo --no-windows
```

The app prints a local URL with a startup token. The page automatically uses the token for API requests.

```text
http://127.0.0.1:8765
```

You can also use the helper scripts:

```bash
sh scripts/run_web_demo.sh
```

Windows:

```bat
scripts\run_web_demo.bat
```

## Native Floating Companion

Use the platform-scoped packages so desktop users see one clear entry point:

| Platform | Entry | Behavior |
|---|---|---|
| macOS 13+ (Apple silicon) | Extract `AI-Progress-Monitor-v<version>-macOS-arm64.zip`, then double-click `AI Progress Monitor.app` | Validated native desktop Pet; always on top; closing hides it; restore/quit from the menu bar avatar; requires Python 3.9+ |
| Windows | Extract `ai-progress-monitor-v<version>-portable.zip`, then run `scripts\start_floating_monitor.bat` | Lightweight preview entry; WinForms/PowerShell always-on-top Pet; closing hides it; restore/quit from the tray icon; requires a separate Windows acceptance pass |

The macOS App is currently ad-hoc signed and not Apple-notarized. If macOS blocks it, Control-click the App and choose Open, or allow it in System Settings > Privacy & Security. Do not disable Gatekeeper globally.

During development on macOS, you can build and launch a local dev app without creating a release package:

```bash
scripts/run_macos_floating_dev.sh
```

ChatGPT Desktop sessions are read compatibly from `~/.codex/sessions`, but only records explicitly marked with the `Codex Desktop` or `ChatGPT Desktop` originator are accepted. Codex CLI and unidentified records remain separate and cannot appear as ChatGPT bubbles. When accessibility permission is unavailable, clicking a ChatGPT bubble still falls back to activating the ChatGPT app instead of reporting a false navigation failure.

Check the dev app state and manual acceptance evidence:

```bash
scripts/check_macos_floating_dev.sh
```

The checker reads the native dev log, shows recent appearance-switch events, and requests the running dev app's local shirt-sloth asset route to verify the approved image and no-store cache header. It does not control the GUI.

Strict mode reports any missing manual path:

```bash
scripts/check_macos_floating_dev.sh --strict
```

## Visual Assets

The Pet uses three local PNG assets for user-facing states, plus a separate app avatar used by the favicon, macOS menu bar icon, and macOS app bundle icon.

| Use | Runtime route | Built-in asset |
|---|---|---|
| Idle | `/assets/pet/idle.png` | `src/ai_progress_monitor/assets/sloth-pet-idle.png` |
| Running | `/assets/pet/running.png` | `src/ai_progress_monitor/assets/sloth-pet-running.png` |
| Needs action | `/assets/pet/needs-action.png` | `src/ai_progress_monitor/assets/sloth-pet-needs-action.png` |
| Shirt sloth appearance | `/assets/pet/shirt.png` | `src/ai_progress_monitor/assets/sloth-pet-shirt.png` |
| App avatar / favicon / macOS icon | `/assets/app-avatar.png` | `src/ai_progress_monitor/assets/app-avatar.png` |

The Pet images are currently 768 x 768 PNG files. The app avatar is a 1024 x 1024 PNG. Pet and avatar assets should keep transparent backgrounds. The app avatar should remain a clean transparent circular icon with no watermark or square background.

To override the built-in visual assets without changing code, create `~/.ai-progress-monitor/preferences.json`:

```json
{
  "pet_assets": {
    "idle": "/path/to/idle.png",
    "running": "/path/to/running.png",
    "needs_action": "/path/to/needs-action.png",
    "app_avatar": "/path/to/app-avatar.png"
  }
}
```

Right-click the Pet, open Appearance, and choose either the default overall sloth or the shirt sloth. The current choice is checked in the submenu. The default theme uses the three state images; the shirt theme currently uses `/assets/pet/shirt.png` for idle, running, and needs-action states. The selected theme is stored as `pet_appearance`; missing or invalid values fall back to the default theme.

The Pet appearance theme-switching PRD is `docs/prd/2026-07-11-pet-appearance-theme-switching-prd.md`.

Custom image paths fall back to built-in assets if the file is missing, unsupported, or too large. Existing `pet_assets.*` overrides still apply to the final Pet images. The app avatar, menu bar icon, and favicon do not change with the Pet appearance theme.

## Integrating Real Sessions

There are two recommended integration paths:

| Path | Best for |
|---|---|
| Terminal wrapper scripts | Claude Code, Codex, Qoder, WorkBuddy, or another AI CLI where you want reliable status updates |
| JSON events | External tools or custom integrations that can publish full session status |

macOS / Linux wrapper example:

```bash
AI_MONITOR_SESSION_ID=checkout-flow \
AI_MONITOR_TITLE="Claude Code - checkout-flow" \
sh scripts/monitor_claude.sh claude
```

Codex wrapper example:

```bash
AI_MONITOR_SESSION_ID=prd-polish \
AI_MONITOR_TITLE="Codex - PRD polish" \
sh scripts/monitor_codex.sh codex
```

Generic AI wrapper examples:

```bash
AI_MONITOR_SESSION_ID=workbuddy-product-ops \
AI_MONITOR_TITLE="WorkBuddy - product ops" \
sh scripts/monitor_workbuddy.sh workbuddy

AI_MONITOR_SESSION_ID=qoder-prd \
AI_MONITOR_TITLE="Qoder - PRD polish" \
sh scripts/monitor_qoder.sh qoder
```

JSON event example:

`scripts/emit_event.py` also follows `AI_PROGRESS_MONITOR_HOME`; by default it writes to `$AI_PROGRESS_MONITOR_HOME/sessions` and replaces a temporary file atomically so the monitor does not read a partial JSON file.

```bash
python3 scripts/emit_event.py \
  --session-id claude-demo-1 \
  --title "Claude Code - checkout-flow" \
  --tool claude_code \
  --surface terminal \
  --status needs_action \
  --summary "Needs user attention in the original window"
```

For a generic AI tool, use `--tool unknown` plus `--tool-display-name` and optional focus metadata:

```bash
python3 scripts/emit_event.py \
  --session-id workbuddy-demo-1 \
  --title "WorkBuddy - product ops" \
  --tool unknown \
  --tool-display-name WorkBuddy \
  --surface desktop \
  --status needs_action \
  --view-ack-required \
  --focus-app-name WorkBuddy \
  --summary "Needs user attention in the original window"
```

The Pet UI does not render command output, full prompts, or direct reply buttons. Users return to the original AI tool window for complex actions.

## Testing

Run the full test suite:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Run the release validation gate:

```bash
python3 scripts/validate_release.py
```

Run the release artifact smoke test:

```bash
python3 scripts/e2e_smoke.py --artifact dist/ai-progress-monitor.pyz
```

Run environment diagnostics:

```bash
python3 scripts/doctor.py
```

## Packaging

Build the local release artifacts:

```bash
python3 scripts/build_release.py
```

Generated artifacts:

| Artifact | Purpose |
|---|---|
| `dist/ai-progress-monitor.pyz` | Build intermediate and the single-file Web Companion runtime included in the portable package |
| `dist/AI-Progress-Monitor-v<version>-macOS-arm64.zip` | macOS 13+ Apple silicon user package containing one `AI Progress Monitor.app`, `README.txt`, and `LICENSE` |
| `dist/ai-progress-monitor-v<version>-portable.zip` | CLI integration, diagnostics, and Windows preview package containing `.pyz`, `scripts/`, `native/windows/`, `README.txt`, and `LICENSE`; no macOS App |

For public GitHub releases, upload both platform-scoped ZIPs instead of committing them to the source repository. Published version tags should remain immutable: keep an already published tag in place, and use a new patch version for later user-visible changes.

The current macOS App requires Python 3.9+, is locally built and ad-hoc signed, and is not Apple-notarized yet.

## Privacy and Security

| Principle | Behavior |
|---|---|
| Local first | Session content is not uploaded by this app |
| Minimal display | The Pet shows labels and status, not full conversation content |
| Original-window handling | Complex actions happen in the original AI tool window |
| Local API token | The page and API use a random startup token |
| Conservative cleanup | Running and needs-action sessions are preserved |

API example:

```text
GET /api/sessions?token=<startup-token>
POST /api/focus
Header: x-monitor-token: <startup-token>
```

## Current Limitations

| Limitation | Notes |
|---|---|
| Window detection depends on OS permissions | The app prefers window IDs and process metadata, then falls back to titles |
| Direct `claude` / `codex` sessions are conservative | Claude uses only the matching PID session state and real working directory; Codex remains CLI-only; wrapper scripts or JSON events are more reliable for fine-grained status |
| Windows floating entry is not yet a stable delivery target | The current path is a lightweight WinForms/PowerShell preview and still needs a dedicated Windows acceptance pass |
| Linux is not the first release target | The architecture leaves room for later support |

## License and Visual Assets

| Item | License |
|---|---|
| Code | MIT License, see `LICENSE` |
| Visual assets | See `ASSET_LICENSE.md` |

The published visual assets were generated with Doubao AI from original prompts and then manually selected and processed for transparent backgrounds, sizing, state variants, and icon use. Local candidate/source images are not committed or packaged by default. Published assets are intended to be usable with this public project under the asset license notes.
