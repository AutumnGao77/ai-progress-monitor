# Contributing

Thanks for taking an interest in AI Progress Monitor.

## Current Project Status

The current stable delivery focus is:

| Area | Status |
|---|---|
| Local Web Companion | Stable project path |
| macOS floating companion | Validated primary native path |
| Windows floating companion | Lightweight preview path, not yet accepted as stable |

Please keep this status accurate in docs and issues.

## Development Setup

Use Python 3.9+ and the standard library. The project intentionally avoids third-party runtime dependencies.

```bash
PYTHONPATH=src python3 -m ai_progress_monitor --demo --no-windows
PYTHONPATH=src python3 -m unittest discover -s tests
python3 scripts/validate_release.py
```

## Pull Request Checklist

- Keep changes focused and avoid unrelated refactors.
- Run `python3 scripts/validate_release.py` before opening a PR.
- Include screenshots or short notes for visible UI changes.
- Do not commit secrets, local credentials, build artifacts, or generated release packages.
- Keep Windows wording clear: the current Windows floating entry is a preview path until a dedicated Windows acceptance pass is completed.

## Visual Assets

Pet and app-avatar changes should preserve transparent backgrounds and the documented asset sizes. Candidate/source images should stay out of source control unless there is a clear product reason to publish them.
