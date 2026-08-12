from __future__ import annotations

import hashlib
import hmac
import secrets
import unicodedata
import uuid
from dataclasses import dataclass

from pwdlib import PasswordHash


PASSWORD_HASHER = PasswordHash.recommended()
SESSION_PREFIX = "wbs"
AGENT_PREFIX = "wba"
INVITE_PREFIX = "wbi"


def normalize_username(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    if not 3 <= len(normalized) <= 80:
        raise ValueError("用户名长度必须在 3–80 个字符之间")
    if any(character.isspace() for character in normalized):
        raise ValueError("用户名不能包含空格")
    return normalized


def validate_password(value: str) -> None:
    if len(value) < 10:
        raise ValueError("密码至少需要 10 个字符")
    if len(value) > 256:
        raise ValueError("密码不能超过 256 个字符")


def hash_password(password: str) -> str:
    validate_password(password)
    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> tuple[bool, str | None]:
    return PASSWORD_HASHER.verify_and_update(password, password_hash)


def secret_digest(secret: str, pepper: str) -> bytes:
    return hmac.new(pepper.encode("utf-8"), secret.encode("utf-8"), hashlib.sha256).digest()


def secure_equals(first: bytes, second: bytes) -> bool:
    return hmac.compare_digest(first, second)


@dataclass(frozen=True, slots=True)
class ParsedSessionToken:
    workspace_public_id: uuid.UUID
    token: str


@dataclass(frozen=True, slots=True)
class ParsedAgentToken:
    workspace_public_id: uuid.UUID
    token_prefix: str
    token: str


@dataclass(frozen=True, slots=True)
class ParsedInviteToken:
    token_prefix: str
    token: str


def create_session_token(workspace_public_id: uuid.UUID) -> str:
    return f"{SESSION_PREFIX}.{workspace_public_id}.{secrets.token_urlsafe(32)}"


def parse_session_token(token: str) -> ParsedSessionToken:
    parts = token.strip().split(".")
    if len(parts) != 3 or parts[0] != SESSION_PREFIX or len(parts[2]) < 32:
        raise ValueError("会话令牌格式无效")
    try:
        workspace_public_id = uuid.UUID(parts[1])
    except ValueError as exc:
        raise ValueError("会话令牌格式无效") from exc
    return ParsedSessionToken(workspace_public_id=workspace_public_id, token=token.strip())


def create_agent_token(workspace_public_id: uuid.UUID) -> str:
    token_prefix = secrets.token_hex(4)
    return f"{AGENT_PREFIX}.{workspace_public_id}.{token_prefix}.{secrets.token_urlsafe(40)}"


def create_invite_token() -> str:
    token_prefix = secrets.token_hex(4)
    return f"{INVITE_PREFIX}.{token_prefix}.{secrets.token_urlsafe(32)}"


def parse_agent_token(token: str) -> ParsedAgentToken:
    parts = token.strip().split(".")
    if len(parts) != 4 or parts[0] != AGENT_PREFIX or len(parts[2]) != 8 or len(parts[3]) < 40:
        raise ValueError("AI Agent 令牌格式无效")
    try:
        workspace_public_id = uuid.UUID(parts[1])
    except ValueError as exc:
        raise ValueError("AI Agent 令牌格式无效") from exc
    return ParsedAgentToken(
        workspace_public_id=workspace_public_id,
        token_prefix=parts[2],
        token=token.strip(),
    )


def parse_invite_token(token: str) -> ParsedInviteToken:
    parts = token.strip().split(".")
    if len(parts) != 3 or parts[0] != INVITE_PREFIX or len(parts[1]) != 8 or len(parts[2]) < 32:
        raise ValueError("邀请码格式无效")
    return ParsedInviteToken(token_prefix=parts[1], token=token.strip())


def create_csrf_token() -> str:
    return secrets.token_urlsafe(32)
