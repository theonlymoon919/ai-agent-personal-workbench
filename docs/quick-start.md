# Quick start

For a complete Chinese walkthrough covering local use, phones, Agents, Hermes, HTTPS, and backup, read [中文安装与使用说明书](USER_GUIDE.zh-CN.md).

This guide creates a new local installation with empty Docker volumes and synthetic or user-entered data only.

## Requirements

- Docker Engine with Docker Compose v2
- Python 3.10 or newer
- 2 GB RAM recommended for the first image build

## Start from source

```bash
git clone https://github.com/theonlymoon919/ai-agent-personal-workbench.git
cd ai-agent-personal-workbench
python scripts/generate_env.py
docker compose up -d --build
docker compose ps
```

Open `http://localhost:8787`. Do not copy an `.env`, database, attachment directory, or Docker volume from another deployment.

On Windows, `py scripts\generate_env.py` is equivalent. If PowerShell blocks `npm.ps1` during development, invoke `npm.cmd` directly.

## Create the first administrator

When the users table is empty, the sign-in screen becomes a one-time setup form:

1. Choose a unique username with 3–80 non-space characters.
2. Choose the display name the workbench should show.
3. Use a unique password of at least 12 characters.
4. Submit the form. The setup endpoint is permanently closed as soon as the transaction succeeds.

If the web form cannot be reached, use the generic interactive fallback from a trusted terminal:

```bash
docker compose exec workbench python -m backend.cloud_manage create-initial-admin \
  --username admin --display-name "Workbench Admin"
```

The CLI refuses to create an administrator if any user already exists and never accepts a password on the command line.

## Invite another user

The first administrator has invitation permission. In **Me → Account & AI Agent**, choose an expiry and create an invitation. Send the URL through a private channel. It is valid once and stores only a server-side digest.

The invited person chooses their own username, display name, and password. The inviter never sees their password or Agent Token.

## Connect an Agent

Each signed-in user can create or rotate one Agent Token in **Me → Account & AI Agent**. The token is displayed once. Save it directly into the Agent's secret store and use the MCP URL shown by the page. See [Agent integration](agent-integration.md).

## Stop, restart, and upgrade

```bash
docker compose stop
docker compose start
docker compose pull
docker compose up -d --build
```

Do not run `docker compose down -v` unless you deliberately intend to delete the database and private-object volumes. Back up both together before upgrading; see [Deployment](deployment.md#backup-export-and-recovery).

## Troubleshooting

```bash
docker compose ps
docker compose logs --tail=100 workbench worker postgres
curl http://localhost:8787/api/cloud/health
```

Redact environment values, tokens, usernames, health/finance details, and object paths before sharing logs.
