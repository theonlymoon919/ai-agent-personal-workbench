from __future__ import annotations

import argparse
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit


def random_secret() -> str:
    return secrets.token_urlsafe(48)


def validated_origin(value: str) -> str:
    origin = value.strip().rstrip("/")
    try:
        parsed = urlsplit(origin)
        parsed.port
    except ValueError as exc:
        raise SystemExit("Origin is not a valid URL") from exc
    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (
        not parsed.hostname
        or not (parsed.scheme == "https" or local_http)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise SystemExit("Origin must use HTTPS; localhost HTTP is allowed for development")
    return origin


def validated_domain(value: str) -> str:
    domain = value.strip().rstrip(".").lower()
    if not domain or len(domain) > 253 or not re.fullmatch(r"[a-z0-9.-]+", domain):
        raise SystemExit("Domain must be a plain DNS hostname")
    labels = domain.split(".")
    if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in labels):
        raise SystemExit("Domain must be a plain DNS hostname")
    return domain


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a local Personal Workbench environment file.")
    parser.add_argument("--output", type=Path, default=Path(".env"))
    parser.add_argument("--origin", default="http://localhost:8787")
    parser.add_argument("--domain", default="", help="Public HTTPS hostname for the Caddy deployment")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite existing file: {args.output}")
    if not 1 <= args.port <= 65535:
        raise SystemExit("Port must be between 1 and 65535")
    origin = validated_origin(args.origin)
    domain = validated_domain(args.domain) if args.domain else ""
    if domain and (not origin.startswith("https://") or urlsplit(origin).hostname != domain):
        raise SystemExit("Domain must match the HTTPS origin hostname")
    secure_cookies = str(origin.startswith("https://")).lower()
    values = [
            f"WORKBENCH_PUBLIC_ORIGIN={origin}",
            f"WORKBENCH_SECURE_COOKIES={secure_cookies}",
            f"WORKBENCH_PORT={args.port}",
            "POSTGRES_DB=workbench",
            "POSTGRES_USER=workbench_owner",
            f"POSTGRES_PASSWORD={random_secret()}",
            f"WORKBENCH_DB_RUNTIME_PASSWORD={random_secret()}",
            f"WORKBENCH_TOKEN_PEPPER={random_secret()}",
            "WORKBENCH_DB_POOL_SIZE=3",
            "WORKBENCH_DB_MAX_OVERFLOW=2",
            "WORKBENCH_IMAGE=personal-workbench",
            "WORKBENCH_IMAGE_TAG=local",
    ]
    if domain:
        values.insert(0, f"WORKBENCH_DOMAIN={domain}")
    values.append("")
    content = "\n".join(values)
    args.output.write_text(content, encoding="utf-8", newline="\n")
    try:
        args.output.chmod(0o600)
    except OSError:
        pass
    print(f"Created {args.output}. Keep this file private and never commit it.")


if __name__ == "__main__":
    main()
