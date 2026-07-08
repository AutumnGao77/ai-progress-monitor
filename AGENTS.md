# Repository Guidelines

## Project Structure & Module Organization

This repository contains a Python desktop app for monitoring Claude Code and Codex progress. Place application source code under `src/`, tests under `tests/`, helper scripts under `scripts/`, and product documents under `docs/`.

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
| App avatar / favicon / macOS icon | `/assets/app-avatar.png` | `app-avatar.png` |

Keep the Pet image background transparent. The WebView container must stay transparent and must not add a CSS `drop-shadow` on `.pet`; if a visual shadow is needed, bake it into the image intentionally and verify it still satisfies the transparent-window experience.

The app avatar source `src/ai_progress_monitor/assets/sloth-candidates/APP头像.png` and runtime `app-avatar.png` must stay clean transparent circular icons: no watermark, no outer square/yellow background, and transparent pixels should be `(0,0,0,0)` to avoid dirty edges in menu bar and bundle icons.

Visual replacements should preserve the current shape contract: three Pet state PNG files at 768 x 768, one app avatar PNG at 1024 x 1024, and the legacy `sloth-pet.png` fallback kept in sync with the idle state. User-configurable overrides are read from `~/.ai-progress-monitor/preferences.json` via `pet_assets.idle`, `pet_assets.running`, `pet_assets.needs_action`, and `pet_assets.app_avatar`.

macOS bundles must copy `app-avatar.png` into `Contents/Resources/`, generate `AppIcon.icns`, declare `CFBundleIconFile=AppIcon`, and use the avatar image for the menu bar status item instead of the literal `AI` text.

Candidate/source images can stay under `src/ai_progress_monitor/assets/sloth-candidates/` for local reference, but release packaging must exclude that directory and `.DS_Store` files. Shipping packages should contain only the final runtime assets.

## Build, Test, and Development Commands

Key commands:

```bash
PYTHONPATH=src python3 -m ai_progress_monitor --demo --no-windows
PYTHONPATH=src python3 -m unittest discover -s tests
python3 scripts/emit_event.py --help
python3 scripts/validate_release.py
python3 scripts/build_release.py
```

The first command launches the demo desktop pet. The second runs the full test suite. The third shows the JSON event helper used by integrations. Run `validate_release.py` before public release, then `build_release.py` to generate `dist/ai-progress-monitor.pyz` and `dist/ai-progress-monitor-release.zip`.

## Coding Style & Naming Conventions

Use Python 3.9-compatible syntax. Prefer dataclasses, enums, small modules, and descriptive names. Keep app logic separate from Tkinter UI so state rules remain testable.

## Testing Guidelines

Use `unittest`. Add tests before production logic for classifiers, stores, sources, and action boundaries. Name files `tests/test_<module>.py`.

## Commit & Pull Request Guidelines

This repository uses `main` as the primary branch. Use short, action-oriented commit messages, for example `Add session classifier` or `Fix action safety check`.

For public commits, use author name `AutumnGao` and the GitHub noreply email configured for this machine. Before `commit`, `amend`, or `push`, explain the operation and risk in plain Chinese, then verify `git config user.name`, `git config user.email`, `git var GIT_AUTHOR_IDENT`, and `git var GIT_COMMITTER_IDENT` so shell environment variables do not override the intended public identity.

Pull requests should include a brief summary, testing notes, linked issue or task reference when available, and screenshots for visible UI changes.

## Security & Configuration Tips

Do not commit secrets, private keys, local credentials, or personal data. Use example environment files such as `.env.example` and keep real `.env` files out of version control.

When documents need a person placeholder, use `Gao` instead of any real local name.

Keep `build/`, `dist/`, local agent folders, logs, and generated packages out of source control. For GitHub releases, upload `dist/ai-progress-monitor-release.zip` as a Release artifact instead of committing it. Current macOS app bundles are locally built and not Apple-notarized unless a future release process explicitly adds notarization.
