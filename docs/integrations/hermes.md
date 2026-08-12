# Hermes reference integration

Hermes was the first AI Agent used end to end with AI Agent Personal Workbench. It remains a reference integration, not a required runtime dependency and not a private workbench protocol.

## What the Windows installer adds

The optional installer configures four separate pieces for the current Windows user:

- the standard `personal_workbench` Streamable HTTP MCP connection;
- a persistent `personal-workbench` Hermes skill for ordinary chat sessions;
- attachment-path handoff plus an authenticated health-image upload bridge;
- a scheduled connector that listens for workbench Agent jobs from a stable `%LOCALAPPDATA%\PersonalWorkbench` runtime directory.

It writes a bounded, repeatable block into the existing Hermes `SOUL.md`, preserves all text outside that block, changes `agent.image_input_mode` to `text`, and removes only the obsolete `personal-workbench-app` skill under Hermes' skill directory. Configuration backups stay in the private Hermes home and must never be copied into this repository.

## Prerequisites

- A running HTTPS AI Agent Personal Workbench deployment
- A signed-in user who generated their own Agent Token
- Hermes installed for the current Windows account, including its CLI configuration package
- A separate Windows account for each person when a computer is shared

Run from the repository's `scripts` directory and pass your own deployment origin explicitly:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_hermes_workbench.ps1 `
  -WorkbenchUrl "https://workbench.example.com"
```

The installer derives `https://workbench.example.com/mcp/`, securely prompts for the token, and never prints it. The origin has no production default and must use HTTPS. To specify the MCP URL separately, pass `-McpUrl`; it must use the same HTTPS origin and end in `/mcp/`.

If the current Hermes home already has a valid `personal_workbench` MCP entry and private token, preserve them with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_hermes_workbench.ps1 `
  -WorkbenchUrl "https://workbench.example.com" `
  -ReuseExistingConnection
```

Restart Hermes after installation so normal chat sessions reload the skill and attachment handoff. The full operating prompt is [HERMES_WORKBENCH_PROMPT.md](../HERMES_WORKBENCH_PROMPT.md); the installed skill receives it as `references/operating-rules.md`.

## Health images from chat channels

When a user explicitly asks Hermes to save a meal, weight, or exercise image received through WeChat, Feishu, QQ, or another channel, the skill requires Hermes to:

1. obtain the real local attachment-cache path supplied to the tool context;
2. confirm the file exists with `Test-Path -LiteralPath`;
3. call `%LOCALAPPDATA%\PersonalWorkbench\upload_health_image.ps1` with the correct kind, date, and optional meal slot;
4. accept success only when the bridge returns `ok=true` and a `record_id`;
5. read the resulting record and original image through MCP before saving any analysis.

The bridge reads the Agent Token from the private Hermes environment, sends an idempotency key, and returns only non-secret record metadata. It does not upload an image when the user only asks to view or analyze it. Missing or expired attachment paths are reported accurately instead of being misrepresented as an unsupported workbench feature.

## Verification

1. Restart Hermes and ask it to use `personal_workbench` to read the workspace overview.
2. Confirm it loads the persistent skill and calls `get_workspace_overview` for the token owner's workspace.
3. Create a synthetic task in the UI and confirm Hermes can read it.
4. Send a non-sensitive exercise image and explicitly ask Hermes to upload it. Confirm a record ID is returned and the same record is readable over MCP.
5. Inspect `%LOCALAPPDATA%\PersonalWorkbench\logs\hermes-cloud-connector.log` for the connected-channel message. Logs must not contain the Agent Token or attachment contents.

## Operating and security rules

- One Hermes instance should use only the token owned by that workspace.
- Do not copy raw Hermes conversation history, `SOUL.md`, `config.yaml`, `.env`, backups, logs, task exports, or chat attachment caches into Git.
- Do not copy the `%LOCALAPPDATA%\hermes` or `%LOCALAPPDATA%\PersonalWorkbench` runtime directories into a source checkout.
- Rotate the token from the user page if the Hermes environment is lost or exposed.
- A channel used by Hermes is outside AI Agent Personal Workbench; the workbench does not claim to bundle WeChat, Feishu, QQ, Telegram, or other connectors.

Internal `hermes` source/status field values remain for data compatibility. MCP clients do not depend on those internal names.
