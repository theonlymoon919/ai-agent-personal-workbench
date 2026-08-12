from __future__ import annotations

import asyncio
import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from .config import CloudSettings
from .database import set_tenant_context
from .models import AgentCredential, InstanceState, RegistrationInvite, User, UserSession, Workspace, WorkspaceSettings
from .security import (
    PASSWORD_HASHER,
    create_agent_token,
    create_csrf_token,
    create_invite_token,
    create_session_token,
    hash_password,
    normalize_username,
    parse_agent_token,
    parse_invite_token,
    parse_session_token,
    secret_digest,
    verify_password,
)


DUMMY_PASSWORD_HASH = PASSWORD_HASHER.hash("not-a-real-user-password")
INITIAL_SETUP_LOCK_ID = 5_768_322_301_245_534_789


class AuthenticationError(ValueError):
    def __init__(self, code: str, message: str = "登录信息无效") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class UserIdentity:
    user_id: int
    user_public_id: uuid.UUID
    workspace_id: int
    workspace_public_id: uuid.UUID
    username: str
    display_name: str
    can_invite: bool
    session_id: int


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    credential_id: int
    credential_public_id: uuid.UUID
    workspace_id: int
    workspace_public_id: uuid.UUID
    scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LoginResult:
    identity: UserIdentity
    session_token: str
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AgentTokenResult:
    identity: AgentIdentity
    token: str


@dataclass(frozen=True, slots=True)
class RegistrationInviteResult:
    invite: RegistrationInvite
    token: str


class AuthService:
    def __init__(self, settings: CloudSettings) -> None:
        self.settings = settings

    async def create_user(
        self,
        session: AsyncSession,
        username: str,
        display_name: str,
        password: str,
        timezone_name: str = "Asia/Shanghai",
    ) -> User:
        normalized = normalize_username(username)
        existing = await session.scalar(select(User.id).where(User.username_normalized == normalized))
        if existing is not None:
            raise ValueError("用户名已经存在")

        password_hash = await asyncio.to_thread(hash_password, password)
        workspace = Workspace(timezone=timezone_name)
        session.add(workspace)
        await session.flush()
        user = User(
            workspace_id=workspace.id,
            username=username.strip(),
            username_normalized=normalized,
            display_name=display_name.strip() or username.strip(),
            password_hash=password_hash,
        )
        session.add(user)
        await session.flush()
        await set_tenant_context(session, workspace.id)
        session.add(
            WorkspaceSettings(
                workspace_id=workspace.id,
                profile={"nickname": user.display_name, "daily_message_style": "mixed"},
                health={},
                ip_preferences={"video_topics": [], "ai_topics": []},
                notification_preferences={"hide_sensitive_details": True},
            )
        )
        await session.flush()
        return user

    async def initial_setup_required(self, session: AsyncSession) -> bool:
        initialized = await session.scalar(select(InstanceState.id).where(InstanceState.id == 1))
        if initialized is not None:
            return False
        user_count = await session.scalar(select(func.count(User.id)))
        return not bool(user_count)

    async def create_initial_admin(
        self,
        session: AsyncSession,
        username: str,
        display_name: str,
        password: str,
        timezone_name: str = "Asia/Shanghai",
    ) -> User:
        # Serialize competing first-run requests. The count is checked again
        # after the lock is acquired, so only one request can ever become the
        # initial administrator.
        await session.execute(
            text("select pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": INITIAL_SETUP_LOCK_ID},
        )
        if not await self.initial_setup_required(session):
            raise AuthenticationError("setup_closed", "初始管理员已经创建")
        user = await self.create_user(
            session,
            username,
            display_name,
            password,
            timezone_name,
        )
        user.can_invite = True
        session.add(InstanceState(id=1))
        await session.flush()
        return user

    async def login(
        self,
        session: AsyncSession,
        username: str,
        password: str,
        user_agent: str = "",
    ) -> LoginResult:
        try:
            normalized = normalize_username(username)
        except ValueError as exc:
            await asyncio.to_thread(PASSWORD_HASHER.verify, password, DUMMY_PASSWORD_HASH)
            raise AuthenticationError("invalid_credentials") from exc

        user = await session.scalar(select(User).where(User.username_normalized == normalized))
        password_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
        verified, upgraded_hash = await asyncio.to_thread(verify_password, password, password_hash)
        if user is None or not verified or user.status != "active":
            raise AuthenticationError("invalid_credentials")

        workspace = await session.get(Workspace, user.workspace_id)
        if workspace is None or workspace.status != "active":
            raise AuthenticationError("workspace_unavailable", "工作空间当前不可用")
        if upgraded_hash:
            user.password_hash = upgraded_hash
            user.password_changed_at = datetime.now(timezone.utc)

        await set_tenant_context(session, workspace.id)
        token = create_session_token(workspace.public_id)
        csrf_token = create_csrf_token()
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=self.settings.session_days)
        record = UserSession(
            workspace_id=workspace.id,
            user_id=user.id,
            token_hash=secret_digest(token, self.settings.token_pepper),
            csrf_hash=secret_digest(csrf_token, self.settings.token_pepper),
            user_agent_hash=(
                hashlib.sha256(user_agent.encode("utf-8")).digest() if user_agent else None
            ),
            expires_at=expires_at,
        )
        session.add(record)
        await session.flush()
        return LoginResult(
            identity=UserIdentity(
                user_id=user.id,
                user_public_id=user.public_id,
                workspace_id=workspace.id,
                workspace_public_id=workspace.public_id,
                username=user.username,
                display_name=user.display_name,
                can_invite=user.can_invite,
                session_id=record.id,
            ),
            session_token=token,
            csrf_token=csrf_token,
            expires_at=expires_at,
        )

    async def authenticate_session(self, session: AsyncSession, token: str) -> UserIdentity:
        try:
            parsed = parse_session_token(token)
        except ValueError as exc:
            raise AuthenticationError("invalid_session", "会话已失效，请重新登录") from exc

        workspace = await session.scalar(
            select(Workspace).where(Workspace.public_id == parsed.workspace_public_id)
        )
        if workspace is None or workspace.status != "active":
            raise AuthenticationError("invalid_session", "会话已失效，请重新登录")
        await set_tenant_context(session, workspace.id)

        token_hash = secret_digest(parsed.token, self.settings.token_pepper)
        row = (
            await session.execute(
                select(UserSession, User)
                .join(User, User.id == UserSession.user_id)
                .where(
                    UserSession.workspace_id == workspace.id,
                    UserSession.token_hash == token_hash,
                    UserSession.revoked_at.is_(None),
                )
            )
        ).one_or_none()
        now = datetime.now(timezone.utc)
        if row is None:
            raise AuthenticationError("invalid_session", "会话已失效，请重新登录")
        session_record, user = row
        if session_record.expires_at <= now or user.status != "active":
            raise AuthenticationError("expired_session", "会话已过期，请重新登录")
        if session_record.last_seen_at <= now - timedelta(minutes=5):
            session_record.last_seen_at = now
        return UserIdentity(
            user_id=user.id,
            user_public_id=user.public_id,
            workspace_id=workspace.id,
            workspace_public_id=workspace.public_id,
            username=user.username,
            display_name=user.display_name,
            can_invite=user.can_invite,
            session_id=session_record.id,
        )

    async def create_registration_invite(
        self,
        session: AsyncSession,
        creator: User,
        expires_at: datetime,
    ) -> RegistrationInviteResult:
        if not creator.can_invite or creator.status != "active":
            raise AuthenticationError("invite_forbidden", "当前账号不能邀请新用户")
        token = create_invite_token()
        parsed = parse_invite_token(token)
        invite = RegistrationInvite(
            created_by_user_id=creator.id,
            token_prefix=parsed.token_prefix,
            secret_hash=secret_digest(token, self.settings.token_pepper),
            expires_at=expires_at,
        )
        session.add(invite)
        await session.flush()
        return RegistrationInviteResult(invite=invite, token=token)

    async def consume_registration_invite(
        self,
        session: AsyncSession,
        token: str,
    ) -> RegistrationInvite:
        try:
            parsed = parse_invite_token(token)
        except ValueError as exc:
            raise AuthenticationError("invalid_invite", "邀请码无效或已经失效") from exc
        digest = secret_digest(parsed.token, self.settings.token_pepper)
        invite = await session.scalar(
            select(RegistrationInvite)
            .where(
                RegistrationInvite.token_prefix == parsed.token_prefix,
                RegistrationInvite.secret_hash == digest,
            )
            .with_for_update()
        )
        now = datetime.now(timezone.utc)
        if invite is None or invite.used_at is not None or invite.expires_at <= now:
            raise AuthenticationError("invalid_invite", "邀请码无效或已经失效")
        return invite

    def verify_csrf(self, csrf_token: str, expected_hash: bytes) -> bool:
        if not csrf_token:
            return False
        candidate = secret_digest(csrf_token, self.settings.token_pepper)
        return hmac.compare_digest(candidate, expected_hash)

    async def session_csrf_hash(self, session: AsyncSession, session_id: int) -> bytes:
        value = await session.scalar(select(UserSession.csrf_hash).where(UserSession.id == session_id))
        if value is None:
            raise AuthenticationError("invalid_session", "会话已失效，请重新登录")
        return value

    async def revoke_session(self, session: AsyncSession, session_id: int) -> None:
        await session.execute(
            update(UserSession)
            .where(UserSession.id == session_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
        )

    async def revoke_all_user_sessions(self, session: AsyncSession, user_id: int) -> None:
        await session.execute(
            update(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
        )

    async def create_agent_credential(
        self,
        session: AsyncSession,
        workspace: Workspace,
        scopes: tuple[str, ...] = (
            "workbench:read",
            "workbench:write",
            "attachments:write",
            "jobs:claim",
        ),
    ) -> AgentTokenResult:
        await set_tenant_context(session, workspace.id)
        now = datetime.now(timezone.utc)
        await session.execute(
            update(AgentCredential)
            .where(
                AgentCredential.workspace_id == workspace.id,
                AgentCredential.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        token = create_agent_token(workspace.public_id)
        parsed = parse_agent_token(token)
        credential = AgentCredential(
            workspace_id=workspace.id,
            token_prefix=parsed.token_prefix,
            secret_hash=secret_digest(token, self.settings.token_pepper),
            scopes=list(scopes),
        )
        session.add(credential)
        await session.flush()
        return AgentTokenResult(
            identity=AgentIdentity(
                credential_id=credential.id,
                credential_public_id=credential.public_id,
                workspace_id=workspace.id,
                workspace_public_id=workspace.public_id,
                scopes=tuple(credential.scopes),
            ),
            token=token,
        )

    async def authenticate_agent(self, session: AsyncSession, token: str) -> AgentIdentity:
        try:
            parsed = parse_agent_token(token)
        except ValueError as exc:
            raise AuthenticationError("invalid_agent_token", "AI Agent 令牌无效") from exc
        workspace = await session.scalar(
            select(Workspace).where(Workspace.public_id == parsed.workspace_public_id)
        )
        if workspace is None or workspace.status != "active":
            raise AuthenticationError("invalid_agent_token", "AI Agent 令牌无效")
        await set_tenant_context(session, workspace.id)
        digest = secret_digest(parsed.token, self.settings.token_pepper)
        credential = await session.scalar(
            select(AgentCredential).where(
                AgentCredential.workspace_id == workspace.id,
                AgentCredential.token_prefix == parsed.token_prefix,
                AgentCredential.secret_hash == digest,
                AgentCredential.revoked_at.is_(None),
            )
        )
        if credential is None:
            raise AuthenticationError("invalid_agent_token", "AI Agent 令牌无效")
        credential.last_used_at = datetime.now(timezone.utc)
        return AgentIdentity(
            credential_id=credential.id,
            credential_public_id=credential.public_id,
            workspace_id=workspace.id,
            workspace_public_id=workspace.public_id,
            scopes=tuple(credential.scopes),
        )
