# Deployment

AI Agent Personal Workbench supports a source build for contributors and a prebuilt GHCR image for operators. Both use the same PostgreSQL schema and private-object volume.

## Local source build

Follow [Quick start](quick-start.md): generate `.env`, then run `docker compose up -d --build`. The web service binds to `127.0.0.1` by default and does not expose PostgreSQL.

## Prebuilt GHCR image

After an official image is published, set these values in the private `.env` file:

```dotenv
WORKBENCH_IMAGE=ghcr.io/theonlymoon919/ai-agent-personal-workbench
WORKBENCH_IMAGE_TAG=0.3.0-alpha.4
```

Then start without a local build:

```bash
docker compose pull
docker compose up -d --no-build
```

Verify the image source, tag, digest, and release notes before upgrading. Never use an image tag as a backup mechanism.

## Ubuntu HTTPS deployment

The following model targets a fresh Ubuntu 24.04 host with a DNS name pointing to it. Run commands from a trusted administrator session.

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/theonlymoon919/ai-agent-personal-workbench.git ~/personal-workbench-bootstrap
cd ~/personal-workbench-bootstrap
sudo sh deploy/bootstrap-ubuntu.sh
sudo git clone https://github.com/theonlymoon919/ai-agent-personal-workbench.git /opt/personal-workbench
cd /opt/personal-workbench
sudo python3 scripts/generate_env.py \
  --output .env.cloud \
  --origin https://workbench.example.com \
  --domain workbench.example.com
sudo docker compose --env-file .env.cloud -f compose.yaml -f compose.cloud.yaml up -d --build
```

Caddy obtains and renews TLS certificates. Only ports 80 and 443 need public ingress; the application port remains bound to host loopback and PostgreSQL has no host port.

Initialize the administrator immediately after the first successful HTTPS response. Until setup is complete, restrict network access to trusted operators whenever possible. Do not expose an unattended uninitialized instance.

For a prebuilt image, edit `WORKBENCH_IMAGE` and `WORKBENCH_IMAGE_TAG` in `.env.cloud`, then use:

```bash
docker compose --env-file .env.cloud -f compose.yaml -f compose.cloud.yaml pull
docker compose --env-file .env.cloud -f compose.yaml -f compose.cloud.yaml up -d --no-build
```

## Upgrade

1. Create and verify a paired database/object backup.
2. Read the changelog and migration notes.
3. Pin the desired image tag or source commit.
4. Run the Compose command. The `migrate` one-shot service upgrades the schema before the app and worker start.
5. Check `/api/cloud/health`, login, an Agent tool call, recent attachments, and tenant isolation smoke tests.

Never run migrations against a different or production database merely to test an upgrade. Restore a backup into an isolated environment instead.

## Backup, export, and recovery

There are two separate capabilities:

- **User export** creates a portable package for the signed-in workspace.
- **Operator backup** protects the entire PostgreSQL database and private-object volume for disaster recovery.

Install the encrypted restic timer on Ubuntu:

```bash
sudo sh deploy/install-backup-timer.sh
```

`deploy/backup-cloud.sh` creates a PostgreSQL custom-format dump and backs it up together with the private-object volume. Configure an off-site restic repository or replicate the repository to separate storage; a backup on the same disk is not disaster recovery.

Recovery rules:

1. Stop application writes.
2. Restore PostgreSQL and private objects from the same recovery point.
3. Keep restored files private and preserve the runtime UID ownership.
4. Run migrations only after the restore is complete.
5. Validate login, attachments, exports, Agent authentication, and isolation before reopening access.

The initial alpha intentionally leaves destructive restore execution as an operator-reviewed process rather than an unauthenticated script. Test recovery regularly on an isolated host.

## Configuration reference

| Variable | Purpose |
| --- | --- |
| `WORKBENCH_PUBLIC_ORIGIN` | Exact browser origin; HTTPS in public deployments |
| `WORKBENCH_DOMAIN` | Caddy hostname for the HTTPS overlay |
| `POSTGRES_PASSWORD` | Database owner password used by migrations |
| `WORKBENCH_DB_RUNTIME_PASSWORD` | Lower-privilege application role password |
| `WORKBENCH_TOKEN_PEPPER` | Server-only pepper for session, invitation, and Agent credential digests |
| `WORKBENCH_IMAGE` / `WORKBENCH_IMAGE_TAG` | Local image name or GHCR package and pinned version |
| `WORKBENCH_SECURE_COOKIES` | Must be `true` behind public HTTPS |

All private configuration files are ignored by Git and Docker build context. Rotate a leaked value and invalidate related credentials; removing it from the latest file is not enough once it has entered Git history.
