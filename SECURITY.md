# Security Policy

AI Progress Monitor is a local-first desktop companion. It should not upload session content, prompts, command output, credentials, or private local files.

## Supported Versions

| Version | Supported |
|---|---|
| `main` | Active development |
| Tagged releases | Best-effort support |

## Reporting a Vulnerability

Please do not post sensitive exploit details, private tokens, or personal data in a public issue.

Preferred reporting path:

1. Use GitHub private vulnerability reporting if it is enabled for this repository.
2. If private reporting is unavailable, open a minimal public issue that describes the affected area without including secrets or exploit details.

Useful information to include:

- Affected version, commit, or release tag.
- Operating system and launch path.
- Whether the issue involves local API tokens, window focusing, logs, release packages, or visual assets.
- A safe reproduction outline that does not expose private user content.

## Security Expectations

- Local API routes require a startup token.
- Logs and UI should avoid exposing prompt text, command output, credentials, or raw session identifiers.
- Release artifacts should be generated from source and attached to GitHub Releases, not committed to the repository.
