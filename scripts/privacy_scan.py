from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


IGNORED_PARTS = {
    ".git",
    ".gradle",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "cache",
    "dist",
    "node_modules",
    "release",
    "venv",
}
BLOCKED_ROOTS = {"attachments", "backups", "data", "dev-vault", "logs", "objects", "uploads", "work"}
BLOCKED_SUFFIXES = {
    ".aab",
    ".apk",
    ".cer",
    ".crt",
    ".db",
    ".dump",
    ".jks",
    ".key",
    ".keystore",
    ".log",
    ".p12",
    ".pem",
    ".pfx",
    ".sqlite",
    ".sqlite3",
}
BLOCKED_FILENAMES = {"HERMES_HANDOFF.md", "SOUL.md", "config.yaml"}
ALLOWED_ENV_FILES = {".env.example", ".env.cloud.example"}


@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    pattern: re.Pattern[str]


def rules() -> tuple[Rule, ...]:
    private_owner = "".join(("yue", "jie"))
    private_nickname = "".join(("玥", "姐"))
    return (
        Rule("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
        Rule("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
        Rule("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
        Rule("long-bearer-token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{24,}\b", re.I)),
        Rule("agent-token", re.compile(r"\bwba\.[0-9a-f-]{20,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{16,}\b", re.I)),
        Rule("windows-user-path", re.compile(r"\b[A-Za-z]:[\\/]Users[\\/][^\\/\s]+[\\/]", re.I)),
        Rule("mac-user-path", re.compile("/" + "Users" + r"/[^/\s]+/")),
        Rule("production-like-sslip", re.compile(r"\b\d{1,3}(?:-\d{1,3}){3}\.sslip\.io\b", re.I)),
        Rule("private-owner-identity", re.compile(rf"\b{re.escape(private_owner)}\b|{re.escape(private_nickname)}", re.I)),
    )


def tracked_files(root: Path) -> list[Path] | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return [root / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def candidate_files(root: Path, force_all: bool) -> list[Path]:
    if not force_all:
        tracked = tracked_files(root)
        if tracked:
            return tracked
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and not any(part in IGNORED_PARTS for part in path.relative_to(root).parts)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Fail when public-source candidates contain private or secret material.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--all", action="store_true", help="Scan all non-ignored files even inside a Git repository")
    args = parser.parse_args()
    root = args.root.resolve()
    findings: set[tuple[str, str]] = set()

    for blocked in BLOCKED_ROOTS:
        if (root / blocked).exists():
            findings.add((blocked, "blocked-root"))

    for path in candidate_files(root, args.all):
        relative = path.relative_to(root)
        if path.name in BLOCKED_FILENAMES or path.suffix.lower() == ".bak":
            findings.add((relative.as_posix(), "private-runtime-file"))
            continue
        if path.name.startswith(".env") and path.name not in ALLOWED_ENV_FILES:
            findings.add((relative.as_posix(), "private-env-file"))
            continue
        if path.suffix.lower() in BLOCKED_SUFFIXES:
            findings.add((relative.as_posix(), "blocked-file-type"))
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            findings.add((relative.as_posix(), "unreadable-file"))
            continue
        if len(raw) > 5 * 1024 * 1024 or b"\0" in raw:
            continue
        text = raw.decode("utf-8", errors="replace")
        for rule in rules():
            if rule.pattern.search(text):
                findings.add((relative.as_posix(), rule.name))

    if findings:
        print(f"Privacy scan failed with {len(findings)} finding(s):")
        for relative, rule_name in sorted(findings):
            print(f"- {relative}: {rule_name}")
        raise SystemExit(1)
    print(f"Privacy scan passed: {len(candidate_files(root, args.all))} files checked; no blocked material found.")


if __name__ == "__main__":
    main()
