# Privacy and security

AI Agent Personal Workbench is designed so a user can see and control the durable records an AI Agent uses. Self-hosting still requires active operator security.

## Protected assets

- User identity, password hash, session, and invitation state
- Tasks, health, finance, learning, media, projects, preferences, and audit events
- Private images and generated export packages
- Agent Tokens, database credentials, token pepper, TLS state, backups, and Android signing material

## Isolation controls

Every tenant-owned row carries `workspace_id`. PostgreSQL row-level security is both enabled and forced, and repository transactions set `app.current_workspace_id`. Users and Agent credentials are resolved to one workspace before tenant queries execute. Attachments use generated, workspace-scoped object keys rather than user filenames.

Isolation depends on PostgreSQL grants and migrations as well as application checks. Do not replace PostgreSQL with a database that ignores the RLS policies, and do not grant the runtime role table-owner or superuser privileges.

## First-run setup

The setup status is public so a fresh UI can discover whether initialization is required. The setup write path obtains a PostgreSQL advisory transaction lock, checks that no user exists, creates the administrator, grants invitation authority, and creates the session in one transaction. Once any user exists, setup returns a conflict and cannot be reopened through configuration.

An attacker who reaches an unattended uninitialized public instance could attempt to become the first administrator. Restrict network access until the owner completes setup, then verify the chosen username before inviting anyone else.

## Authentication and credentials

- Passwords are hashed with Argon2 and never recoverable.
- Browser login uses an HttpOnly session cookie plus a separate CSRF token; public deployments require HTTPS secure cookies.
- Invitations and Agent Tokens are high-entropy one-time-displayed credentials. Only peppered digests are stored.
- Agent Tokens route to one public workspace ID and do not contain database IDs or personal data.
- Token rotation revokes the old Agent credential.
- Login, registration, and initial setup are rate-limited in each application process. Deploy an edge rate limit for hostile public traffic.

## Attachments and external content

Uploads have size limits, are image-normalized, and are stored outside the application image. Browsers receive private objects through authenticated routes. The UI may open external source/media links supplied by an Agent; those sites have independent privacy policies and may observe the user's request.

## Data control

Supported records can be corrected, soft-deleted, restored, or permanently removed with the account. Users can export their workspace. Complete account deletion revokes sessions and Agent credentials before the worker purges database rows and the workspace object directory.

Backups may retain deleted data until retention expires. Operators must document retention, protect encryption keys, and honor deletion requirements in every off-site copy.

## Secret handling

- Generate `.env` files locally with `scripts/generate_env.py`; never commit them.
- Never place signing keys, keystores, passwords, tokens, cookies, databases, attachments, backups, or logs in Git or Docker build context.
- Use GitHub Actions secrets or an equivalent protected secret store for release signing.
- Treat invitation URLs as temporary credentials.
- Run `python scripts/privacy_scan.py` before every push and Gitleaks in CI.
- If a secret enters Git history, revoke/rotate it first; history rewriting alone is not remediation.

For the optional Hermes integration, `%LOCALAPPDATA%\hermes`, `%LOCALAPPDATA%\PersonalWorkbench`,
`SOUL.md`, `config.yaml`, their backups, connector logs, scheduled-task exports, and chat attachment
caches are private runtime state. Never copy them into a source checkout or release archive. The public
installer accepts the workbench origin as an explicit parameter or environment variable and has no
production server default.

## Backup security

PostgreSQL and private objects form one logical backup. Encrypt both, copy them off-host, restrict restic credentials, test recovery on an isolated host, and keep recovery logs free of data values. Database-only or object-only backups are incomplete.

## Operator checklist

- Patch the OS, Docker, Caddy, PostgreSQL, Python, Node build chain, and Android build chain.
- Use a dedicated host or least-privilege service account; never run the application container as root.
- Permit public ingress only to HTTPS; do not publish PostgreSQL.
- Complete first-run setup before broad access.
- Pin release tags/digests and review migration notes.
- Configure external rate limiting, monitoring, encrypted off-site backup, and recovery tests.
- Review audit events and rotate credentials after staff or infrastructure changes.

## Reporting

Follow [SECURITY.md](../SECURITY.md). Never place a real exploit target, credential, user record, attachment, backup, or production log in a public issue.
