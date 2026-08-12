# AI Agent and MCP integration

AI Agent Personal Workbench is MCP-native. It does not require a proprietary Agent protocol and it does not bundle chat-channel connectors.

## Endpoint and authentication

The server exposes MCP Streamable HTTP at `/mcp/`:

```text
https://workbench.example.com/mcp/
Authorization: Bearer wba.<workspace-routing-id>.<prefix>.<secret>
```

Generate the token while signed in to the corresponding workspace. It is displayed once; the database stores only a peppered digest. Rotating the token immediately revokes the previous credential.

Store it as a secret environment value, for example `MCP_PERSONAL_WORKBENCH_API_KEY`, and reference that value from the Agent's configuration. Do not paste the token into prompts, screenshots, issue reports, shell history, or a checked-in JSON/YAML file.

## Generic configuration shape

Client configuration formats differ, but the required information is equivalent to:

```json
{
  "mcpServers": {
    "personal-workbench": {
      "url": "https://workbench.example.com/mcp/",
      "headers": {
        "Authorization": "Bearer ${MCP_PERSONAL_WORKBENCH_API_KEY}"
      }
    }
  }
}
```

Confirm whether your client expands environment variables in headers. If it does not, use its native secret-store mechanism rather than committing a literal token.

## Compatibility

| Client / SDK | Status | Notes |
| --- | --- | --- |
| Python MCP SDK 1.29.0 | Automated smoke test | Initializes Streamable HTTP, lists tools, and calls an authenticated overview tool |
| Hermes | Reference integration | First end-to-end Agent integration; configured separately and not bundled with the workbench |
| Other MCP Streamable HTTP clients | Protocol-compatible; client validation needed | Header and environment syntax varies by product |

See [Hermes](integrations/hermes.md) for the reference-specific configuration. A product name in this table is not an endorsement or a claim that chat connectors are built into AI Agent Personal Workbench.

## Tool and privacy model

- The credential determines the workspace; tool parameters cannot choose another tenant.
- Read and write scopes are attached to the credential.
- Agent writes use the same repositories, validation, audit events, and WebSocket refresh as user writes.
- One active Agent credential is supported per workspace in the alpha.
- User-visible structured records are durable. Raw Agent conversation history is not copied into the workbench.
- Attachments are loaded through authenticated tools or API routes, never through a public object URL.

Tools cover tasks, projects, calendar, health, learning, media, content, finance, daily suggestions, and the Agent job queue. Inspect the live server's `tools/list` result for the authoritative tool set and schemas.

## Smoke test

Set the token only in the process environment, then run:

```bash
export MCP_PERSONAL_WORKBENCH_API_KEY='replace-at-runtime'
python deploy/mcp-smoke-test.py --url https://workbench.example.com/mcp/
unset MCP_PERSONAL_WORKBENCH_API_KEY
```

The script reports only pass/fail facts and a tool count. It never prints the token or workspace contents.

## Chat channels

AI Agent Personal Workbench does not include WeChat, Feishu, QQ, Slack, email, or other channel connectors. An Agent that is already connected to a channel may choose to read or write the user's workbench through MCP, subject to that Agent's own permissions and privacy model.
