# Repository Guidelines

## Project Structure & Module Organization

This repository contains a Python desktop app for monitoring Claude Code, Codex, Qoder, WorkBuddy, and other configured AI tool progress. Place application source code under `src/`, tests under `tests/`, helper scripts under `scripts/`, and product documents under `docs/`.

Recommended structure:

```text
src/        Python application code
tests/      Unit and behavior tests
scripts/    Local helper scripts and launchers
native/     macOS and Windows native companion shells
docs/       PRDs, plans, and product notes
```

Keep feature-specific files close together when practical. For example, a future module named `billing` can use `src/billing/` and matching tests in `tests/billing/`.

## Pet Visual Assets

The desktop Pet uses local raster assets under `src/ai_progress_monitor/assets/` and serves them through stable runtime routes:

| State or use | Route | Default asset |
|---|---|---|
| Idle | `/assets/pet/idle.png` | `sloth-pet-idle.png` |
| Running | `/assets/pet/running.png` | `sloth-pet-running.png` |
| Needs action | `/assets/pet/needs-action.png` | `sloth-pet-needs-action.png` |
| Shirt appearance | `/assets/pet/shirt.png` | `sloth-pet-shirt.png` |
| App avatar / favicon / macOS icon | `/assets/app-avatar.png` | `app-avatar.png` |

Keep the Pet image background transparent. The WebView container must stay transparent and must not add a CSS `drop-shadow` on `.pet`; if a visual shadow is needed, bake it into the image intentionally and verify it still satisfies the transparent-window experience.

Runtime `app-avatar.png` must stay a clean transparent circular icon: no watermark, no outer square/yellow background, and transparent pixels should be `(0,0,0,0)` to avoid dirty edges in menu bar and bundle icons. If local candidate/source files exist, apply the same visual standard to them before deriving runtime assets.

Visual replacements should preserve the current shape contract: three Pet state PNG files at 768 x 768, one app avatar PNG at 1024 x 1024, and the legacy `sloth-pet.png` fallback kept in sync with the idle state. User-configurable overrides are read from `~/.ai-progress-monitor/preferences.json` via `pet_assets.idle`, `pet_assets.running`, `pet_assets.needs_action`, and `pet_assets.app_avatar`.

Pet appearance switching is documented in `docs/prd/2026-07-11-pet-appearance-theme-switching-prd.md`. The right-click Pet menu is `外观`, `隐藏 Pet`, and `退出程序`; the `外观` submenu contains `背带裤树懒` and `衬衫树懒`, with a checkmark on the active choice. `pet_appearance` accepts `default` or `shirt`; missing or invalid values fall back to `default`. The token-protected local preference API is `GET /api/preferences` and `POST /api/preferences/pet-appearance`. `pet_assets.*` overrides still apply to the final Pet image after the selected theme is resolved.

The public macOS package contains one user-facing `AI Progress Monitor.app`, built from the validated native floating companion. It must target Apple silicon arm64 and macOS 13+, copy `app-avatar.png` into `Contents/Resources/`, generate `AppIcon.icns`, declare `CFBundleIconFile=AppIcon`, and use the avatar image for the menu bar status item instead of the literal `AI` text. Release builds must fail when Swift compilation fails; never ship a placeholder launcher or embed Swift build sources in the App bundle.

Keep advanced CLI integrations and the Windows preview in the separate portable package. Both public ZIPs must include `README.txt` and `LICENSE`; the macOS package must not contain `.pyz` at its root, `scripts/`, or `native/`, while the portable package must not contain a macOS `.app`.

Candidate/source images can stay under `src/ai_progress_monitor/assets/sloth-candidates/` for local reference, but they are gitignored by default and release packaging must exclude that directory and `.DS_Store` files. CI and public tests must validate the final runtime assets instead of requiring local candidate files.

## AI Tool Monitoring

AI tool detection is configured through `AI_TOOL_DEFINITIONS` in `src/ai_progress_monitor/sources.py`. Each tool definition can declare `key`, `display_name`, CLI executable names, desktop main binaries, ignored helper/daemon command tokens, and generated conversation path patterns. Keep new tool support in that registry and its source-specific parsers instead of hard-coding naming rules in the front end.

The current full desktop monitoring scope includes ChatGPT Desktop session events (read compatibly from `~/.codex/sessions` only when the originator is explicitly `Codex Desktop` or `ChatGPT Desktop`), Qoder / Qoder CN logs and local cache metadata, and WorkBuddy local session database plus runtime logs. Codex remains supported as a CLI tool; the retired `Codex.app` must not generate a desktop product entry. Generic process-only entries are still allowed for configured AI CLI tools and desktop app idle fallbacks, but they must not be treated as proof that AI is running.

For direct Claude Code CLI processes on macOS, reset per-process scan fields such as `cwd` before every loop iteration. Claude may skip the normal `lsof` lookup and then use only its matching `~/.claude/sessions/<pid>.json` record to fill the working directory and status. Never inherit another process's cwd or use a different directory's Claude state, because that creates a fictitious session and breaks window focus.

On POSIX process scans, discard zombie (`Z`) and exiting (`E`) rows before any `lsof`, child-activity, or ancestor lookup. Filtering only after those expensive lookups can exhaust the four-second source budget and freeze discovery for every healthy App and CLI, even though stale bubbles remain temporarily visible through the failure grace window.

User-visible state stays normalized to three states: `needs_action`, `running`, and `idle`. Completed results that only need user review can use `view_ack_required=true` and become idle after a successful focus/view. True user-attention states such as approval, suspended, pending with activity, or waiting for input must use `view_ack_required=false` and remain needs-action until the source state changes.

Desktop full sessions take priority over generic desktop app idle entries. After a viewed desktop session becomes idle, keep the specific conversation visible for 15 minutes; after that, remove it and show the desktop app idle entry if the app is still running. WorkBuddy conversation titles should include project/folder context when available. Qoder and Qoder CN must prefer real conversation titles from cache/project metadata and must not expose generated `chat-1`, `chat-3`, task IDs, UUIDs, or internal session fragments as primary bubble labels.

The AI tool monitoring expansion PRD is `docs/prd/2026-07-14-ai-tool-monitoring-expansion-prd.md`. User-configurable tool discovery / automatic process scanning is not part of this iteration.

## Build, Test, and Development Commands

Key commands:

```bash
PYTHONPATH=src python3 -m ai_progress_monitor --demo --no-windows
PYTHONPATH=src python3 -m unittest discover -s tests
python3 scripts/emit_event.py --help
python3 scripts/validate_release.py
python3 scripts/build_release.py
```

The first command launches the demo desktop pet. The second runs the full test suite. The third shows the JSON event helper used by integrations. Run `validate_release.py` before public release, then `build_release.py` to generate `dist/ai-progress-monitor.pyz`, `dist/AI-Progress-Monitor-v<version>-macOS-arm64.zip`, and `dist/ai-progress-monitor-v<version>-portable.zip`.

The current public release baseline is `v0.2.1`, published and manually accepted on 2026-07-20. Its annotated tag resolves to commit `0deab62144d4c16e780b8aaa7cafe6fbbe9c5175`, and its two public assets are `AI-Progress-Monitor-v0.2.1-macOS-arm64.zip` and `ai-progress-monitor-v0.2.1-portable.zip`. The authoritative package hashes and post-download acceptance evidence are recorded in `docs/qa/2026-07-17-v0.2.1-release-packaging-validation.md`. For later releases, rebuild and recompute hashes; never reuse this release's checksums or move the published tag.

## Development Principles

Feature development and iteration must start from first principles: clarify the real user problem, success criteria, system boundaries, failure modes, and long-term maintenance cost before choosing an implementation. Design and review changes for stable long-running software, including predictable behavior, testability, observability, backward compatibility, safe defaults, and graceful degradation when dependencies or local environments fail.

## Coding Style & Naming Conventions

Use Python 3.9-compatible syntax. Prefer dataclasses, enums, small modules, and descriptive names. Keep app logic separate from Tkinter UI so state rules remain testable.

## Testing Guidelines

Use `unittest`. Add tests before production logic for classifiers, stores, sources, and action boundaries. Name files `tests/test_<module>.py`.

## Commit & Pull Request Guidelines

This repository uses `main` as the primary branch. Use short, action-oriented commit messages, for example `Add session classifier` or `Fix action safety check`.

For public commits, use author name `AutumnGao` and the GitHub noreply email configured for this machine. Before `commit`, `amend`, or `push`, explain the operation and risk in plain Chinese, then verify `git config user.name`, `git config user.email`, `git var GIT_AUTHOR_IDENT`, and `git var GIT_COMMITTER_IDENT` so shell environment variables do not override the intended public identity.

Pull requests should include a brief summary, testing notes, linked issue or task reference when available, and screenshots for visible UI changes.

## Security & Configuration Tips

Do not commit secrets, private keys, local credentials, company-related identifiers, or personal data. Use example environment files such as `.env.example` and keep real `.env` files out of version control.

When documents need a person placeholder, use `Gao` instead of any real local name.

Treat the local login username, machine names, real local paths, old personal/company email fragments, and any company workspace identifiers as sensitive. Public code, docs, tests, release notes, GitHub issues, and release artifacts must not expose them; use `Gao`, placeholder paths, or GitHub noreply identity where needed.

Keep `build/`, `dist/`, local agent folders, logs, and generated packages out of source control. For GitHub releases, upload both platform-scoped ZIPs from `dist/` instead of committing them. The current macOS App is locally built and ad-hoc signed, requires Python 3.9+, and is not Apple-notarized unless a future release process explicitly adds Developer ID signing and notarization.
