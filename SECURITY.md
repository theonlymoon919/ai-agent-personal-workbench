# Security Policy

## Supported versions

Security fixes are applied to the latest published release. Pre-release builds are provided for evaluation and may change without backward-compatibility guarantees.

## Reporting a vulnerability

Please use the repository's **Security → Report a vulnerability** flow to open a private GitHub Security Advisory. Do not disclose suspected vulnerabilities, credentials, private data, or exploit details in a public issue.

Include the affected version, deployment model, reproduction steps, impact, and any suggested mitigation. Maintainers will acknowledge a complete report as soon as practical and coordinate disclosure after a fix is available.

Never attach a real database, `.env` file, Agent Token, session cookie, private attachment, signing key, or production log to a report. Replace sensitive values with clearly marked examples.

## Deployment responsibilities

Operators are responsible for TLS, host patching, off-site backups, access controls, secret rotation, and limiting who can reach an uninitialized instance. See [Privacy and security](docs/privacy-and-security.md).
