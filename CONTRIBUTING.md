# Contributing

Thank you for helping improve AI Agent Personal Workbench.

## Before opening a change

1. Search existing issues and explain the user problem before proposing a large implementation.
2. Keep tenant isolation, user ownership, export/delete behavior, and MCP compatibility intact.
3. Never use real user records, attachments, credentials, domains, or signing material in fixtures, screenshots, logs, commits, or issues.
4. Use synthetic names and data in every test and demo.

## Development checks

```bash
python -m venv .venv
./.venv/bin/pip install -r backend/requirements.txt
./.venv/bin/python -m unittest discover -s backend/tests -v
cd frontend && npm ci && npm test && npm run build
```

On Windows, activate `.venv\Scripts\Activate.ps1` and use `npm.cmd` if PowerShell script execution is restricted. Android debug builds require JDK 17 and the Android SDK; see [docs/android.md](docs/android.md).

Before submitting, run `python scripts/privacy_scan.py` and review `git diff --check`. Add tests for behavioral changes and update documentation when an API, deployment step, or privacy guarantee changes.

## Pull requests

Keep each pull request focused. Describe what changed, why it changed, user impact, migration considerations, and the exact checks run. By submitting a contribution, you agree that it is licensed under Apache License 2.0.

Security reports must follow [SECURITY.md](SECURITY.md), not the public issue tracker.
