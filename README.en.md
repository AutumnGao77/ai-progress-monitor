# AI Progress Monitor

English | [Chinese](README.md)

AI Progress Monitor is a local-first, low-interruption desktop companion for tracking AI coding sessions. It watches Claude Code, Codex, and other configured AI tools across terminal and desktop workflows, then shows a small Pet companion when a session is running, idle, or waiting for user action.

The current stable delivery focus is the local Web Companion plus the validated macOS floating companion app. A lightweight Windows floating entry is kept as a preview path, but it has not been accepted as a stable delivery target yet.

## Features

| Feature | Status |
|---|---|
| Local Web Companion | Supported |
| macOS floating companion | Supported, with a menu bar avatar icon for restore/quit |
| Windows lightweight floating companion | Preview entry, with a WinForms/PowerShell tray path kept in the package; not yet accepted as a stable delivery target |
| Three-state Pet UI | Idle, running, and needs-action images |
| Numeric badge | Shows the total number of visible session bubbles |
| Bubble list | Shows session/tool labels and status without exposing content |
| Click to focus | Opens the related terminal, IDE, or desktop window when possible |
| Direct CLI detection | Detects running `claude` / `codex` sessions conservatively |
| Codex Desktop session detection | Reads local Codex session events when available |
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

For a more desktop-pet-like experience, use the packaged floating companion entries:

| Platform | Entry | Behavior |
|---|---|---|
| macOS | `AI Progress Monitor Floating.app` | Validated desktop Pet entry; always-on-top floating Pet; closing hides it; restore/quit from the menu bar avatar icon |
| Windows | `scripts\start_floating_monitor.bat` | Lightweight preview entry; WinForms/PowerShell always-on-top Pet; closing hides it; restore/quit from the tray icon; requires a separate Windows acceptance pass |

During development on macOS, you can build and launch a local dev app without creating a release package:

```bash
scripts/run_macos_floating_dev.sh
```

Check the dev app state and manual acceptance evidence:

```bash
scripts/check_macos_floating_dev.sh
```

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

Custom image paths fall back to built-in assets if the file is missing, unsupported, or too large.

## Integrating Real Sessions

There are two recommended integration paths:

| Path | Best for |
|---|---|
| Terminal wrapper scripts | Claude Code / Codex terminal sessions where you want reliable status updates |
| JSON events | External tools or custom integrations |

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

JSON event example:

```bash
python3 scripts/emit_event.py \
  --session-id claude-demo-1 \
  --title "Claude Code - checkout-flow" \
  --tool claude_code \
  --surface terminal \
  --status needs_action \
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
| `dist/ai-progress-monitor.pyz` | Single-file Web Companion runtime package |
| `dist/ai-progress-monitor-release.zip` | Recommended distribution bundle with scripts, macOS app bundles, and Windows preview scripts |

For public GitHub releases, upload `dist/ai-progress-monitor-release.zip` as a Release artifact instead of committing it to the source repository.

The current macOS app bundles are locally built and ad-hoc signed. They are not Apple-notarized yet, so users may need to allow the app in macOS system settings.

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
| Direct `claude` / `codex` sessions are conservative | Wrapper scripts or JSON events are more reliable for fine-grained status |
| Windows floating entry is not yet a stable delivery target | The current path is a lightweight WinForms/PowerShell preview and still needs a dedicated Windows acceptance pass |
| Linux is not the first release target | The architecture leaves room for later support |

## License and Visual Assets

| Item | License |
|---|---|
| Code | MIT License, see `LICENSE` |
| Visual assets | See `ASSET_LICENSE.md` |

The visual assets were generated with Doubao AI from original prompts and then manually selected and processed for transparent backgrounds, sizing, state variants, and icon use. They are intended to be usable with this public project under the asset license notes.
