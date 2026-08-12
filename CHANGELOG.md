# Changelog

All notable changes are documented here. This project follows [Semantic Versioning](https://semver.org/) while APIs remain pre-1.0.

## [Unreleased]

## [0.3.0-alpha.3] - 2026-08-12

### Changed

- Renamed the public product to AI Agent Personal Workbench / AI Agent 个人工作台.
- Renamed the public GitHub repository and GHCR image to `ai-agent-personal-workbench` while retaining stable MCP, package, data-path, and Hermes skill identifiers for compatibility.
- Updated the web app, Android shell, documentation, demo, and installation assets to use the new brand.

## [0.3.0-alpha.2] - 2026-08-12

### Added

- Independent, privacy-cleaned open-source distribution.
- One-time web initialization for the first administrator, with a transaction lock that permanently closes setup after success.
- Generic MCP-compatible AI Agent wording and a separate Hermes reference integration.
- Source and prebuilt-image Docker deployment paths, Android debug build guidance, CI, dependency audits, and secret scanning.
- Unified Chinese installation and user guide covering local use, phones, generic Agents, Hermes, operations, and troubleshooting.
- Apache License 2.0 and community health files.

### Changed

- Invitation authority is assigned generically to the first administrator instead of a fixed username.
- Deployment configuration uses generated local secrets and example domains only.
- Ubuntu bootstrap instructions now include the initial source checkout required on a fresh server.
- Authenticated API transactions now commit before successful responses are sent, preventing immediate follow-up reads from seeing stale data.
- User-facing news labels and prompts now use the interest-neutral “今日资讯” instead of assuming every user follows AI news.
- Desktop and mobile navigation now expose “今日资讯” directly instead of hiding news and short-video trends under “个人 IP”.

## [0.3.0-alpha.1] - 2026-08-11

- Initial open-source alpha candidate.
