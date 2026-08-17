from __future__ import annotations

import asyncio
import hashlib
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import quote

from fastapi import Depends as FastAPIDepends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import AgentIdentity, AuthService, AuthenticationError, UserIdentity
from .config import CloudSettings
from .database import CloudDatabase, set_tenant_context
from .core_repository import CoreRepository, QUADRANTS
from .finance_repository import FinanceRepository, yuan_to_minor
from .export_repository import ExportRepository
from .finance_schemas import (
    FinanceAccountCreate,
    FinanceAccountUpdate,
    FinanceBudgetUpsert,
    FinanceCategoryCreate,
    FinanceCategoryUpdate,
    FinanceInsightCreate,
    FinanceRecurringRuleCreate,
    FinanceRecurringRuleUpdate,
    FinanceTransactionCreate,
    FinanceTransactionUpdate,
    SavingsGoalCreate,
    SavingsGoalUpdate,
)
from .health_repository import HealthRepository
from .growth_repository import GrowthRepository
from .growth_schemas import ContentItemCreate, LearningPlanGeneratedUpdate
from .image_processing import normalize_health_image
from .jobs import claim_next_job, complete_job
from .mcp_server import create_cloud_mcp
from .rate_limit import MemoryRateLimiter
from .models import AgentCredential, AgentJob, DeletionRequest, StoredObject, User, Workspace, WorkspaceEvent, WorkspaceSettings
from .security import hash_password, normalize_username, verify_password
from .storage import LocalPrivateObjectStore
from ..version import CLOUD_APP_VERSION
from ..models import (
    DailyHealthAdviceCreate,
    DailyMessageCreate,
    HealthAnalysisCreate,
    HealthGoalsUpdate,
    HealthRecordUpdate,
    IPPreferencesUpdate,
    LearningPlanCreate,
    LearningPlanProgressUpdate,
    LearningPlanUpdate,
    LibraryItemCreate,
    LibraryItemUpdate,
    ProjectCreate,
    ProjectPhaseCreate,
    ProjectPhaseUpdate,
    ProjectUpdate,
    StartupUpdate,
    TaskCreate,
    TaskUpdate,
    WaterRecord,
    WeightRecord,
)


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


def Depends(dependency):
    """Finish transaction-backed dependencies before sending the response."""
    return FastAPIDepends(dependency, scope="function")


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class AccountDeletionRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    confirmation: str = Field(min_length=1, max_length=40)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class UsernameChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_username: str = Field(min_length=3, max_length=80)


class RegistrationRequest(BaseModel):
    invite_code: str = Field(min_length=16, max_length=256)
    username: str = Field(min_length=3, max_length=80)
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=12, max_length=256)


class InitialSetupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=12, max_length=256)


class InviteCreateRequest(BaseModel):
    expires_in_hours: int = Field(default=72, ge=1, le=168)


class AgentTokenIssueRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    confirmation: str = Field(min_length=1, max_length=40)


class ProfileUpdate(BaseModel):
    nickname: str = Field(min_length=1, max_length=30)
    daily_message_style: str = Field(default="mixed", pattern="^(mixed|encouraging|comforting)$")


class AgentJobCompleteRequest(BaseModel):
    result_summary: str = Field(default="", max_length=4000)
    succeeded: bool = True
    error_code: str | None = Field(default=None, max_length=80)


@dataclass(slots=True)
class RequestContext:
    session: AsyncSession
    identity: UserIdentity
    auth_source: str


@dataclass(slots=True)
class AgentRequestContext:
    session: AsyncSession
    identity: AgentIdentity


def _bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def _identity_payload(identity: UserIdentity) -> dict:
    return {
        "user": {
            "id": str(identity.user_public_id),
            "username": identity.username,
            "display_name": identity.display_name,
            "can_invite": identity.can_invite,
        },
        "workspace": {"id": str(identity.workspace_public_id)},
    }


def _public_uuid(value: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"{label}不存在") from exc


def _agent_job_payload(job: AgentJob) -> dict:
    return {
        "id": str(job.public_id),
        "type": job.job_type,
        "subject_type": job.subject_type,
        "subject_key": job.subject_key,
        "title": job.title,
        "payload": dict(job.payload),
        "status": job.status,
        "attempts": job.attempts,
        "available_at": job.available_at.isoformat(),
        "claimed_at": job.claimed_at.isoformat() if job.claimed_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "result_summary": job.result_summary,
        "error_code": job.error_code,
    }


def create_cloud_app(
    settings: CloudSettings | None = None,
    database: CloudDatabase | None = None,
) -> FastAPI:
    resolved_settings = settings or CloudSettings.from_env()
    resolved_database = database or CloudDatabase.create(resolved_settings)
    auth = AuthService(resolved_settings)
    object_store = LocalPrivateObjectStore(resolved_settings.data_root)
    login_limiter = MemoryRateLimiter(maximum=8, window_seconds=5 * 60)
    registration_limiter = MemoryRateLimiter(maximum=5, window_seconds=10 * 60)
    setup_limiter = MemoryRateLimiter(maximum=5, window_seconds=10 * 60)
    cloud_mcp = create_cloud_mcp(
        resolved_settings,
        resolved_database,
        auth,
        object_store,
    )
    cloud_mcp_app = cloud_mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with cloud_mcp.session_manager.run():
            yield
        await resolved_database.close()

    app = FastAPI(title="AI Agent 个人工作台", version=CLOUD_APP_VERSION, lifespan=lifespan)
    app.state.cloud_settings = resolved_settings
    app.state.cloud_database = resolved_database
    app.state.auth_service = auth
    app.state.cloud_mcp = cloud_mcp
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved_settings.public_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "Idempotency-Key"],
    )
    app.mount("/mcp", cloud_mcp_app, name="hermes-mcp")

    def login_response(result, status_code: int = 200) -> JSONResponse:
        response = JSONResponse(
            {
                **_identity_payload(result.identity),
                "expires_at": result.expires_at.isoformat(),
                "csrf_token": result.csrf_token,
            },
            status_code=status_code,
        )
        cookie_base = {
            "secure": resolved_settings.secure_cookies,
            "samesite": "lax",
            "path": "/",
            "max_age": resolved_settings.session_days * 24 * 60 * 60,
        }
        response.set_cookie(
            resolved_settings.session_cookie_name,
            result.session_token,
            httponly=True,
            **cookie_base,
        )
        response.set_cookie(
            resolved_settings.csrf_cookie_name,
            result.csrf_token,
            httponly=False,
            **cookie_base,
        )
        return response

    async def current_context(request: Request) -> AsyncIterator[RequestContext]:
        bearer = _bearer_token(request)
        cookie_token = request.cookies.get(resolved_settings.session_cookie_name)
        token = bearer or cookie_token
        source = "bearer" if bearer else "cookie"
        if not token:
            raise HTTPException(status_code=401, detail="请先登录")
        async with resolved_database.session_factory() as session:
            async with session.begin():
                try:
                    identity = await auth.authenticate_session(session, token)
                    if source == "cookie" and request.method.upper() not in SAFE_METHODS:
                        header_token = request.headers.get("x-csrf-token", "")
                        cookie_csrf = request.cookies.get(resolved_settings.csrf_cookie_name, "")
                        expected_hash = await auth.session_csrf_hash(session, identity.session_id)
                        if not header_token or header_token != cookie_csrf or not auth.verify_csrf(
                            header_token, expected_hash
                        ):
                            raise HTTPException(status_code=403, detail="页面安全校验已失效，请刷新后重试")
                except AuthenticationError as exc:
                    raise HTTPException(status_code=401, detail=str(exc)) from exc
                yield RequestContext(session=session, identity=identity, auth_source=source)

    async def agent_context(request: Request) -> AsyncIterator[AgentRequestContext]:
        token = _bearer_token(request)
        if not token:
            raise HTTPException(status_code=401, detail="AI Agent 需要使用专属 Bearer 令牌")
        async with resolved_database.session_factory() as session:
            async with session.begin():
                try:
                    identity = await auth.authenticate_agent(session, token)
                except AuthenticationError as exc:
                    raise HTTPException(status_code=401, detail=str(exc)) from exc
                yield AgentRequestContext(session=session, identity=identity)

    def require_agent_scope(context: AgentRequestContext, scope: str) -> None:
        if scope not in context.identity.scopes:
            raise HTTPException(status_code=403, detail=f"AI Agent 缺少权限：{scope}")

    @app.get("/api/cloud/info")
    async def cloud_info() -> dict:
        return {
            "name": "AI Agent 个人工作台",
            "status": "foundation_ready",
            "message": "云端数据底座已启动，业务模块正在分阶段迁移。",
        }

    @app.get("/api/cloud/health")
    async def healthcheck() -> JSONResponse:
        try:
            database_ok = await asyncio.wait_for(resolved_database.healthcheck(), timeout=3)
        except Exception:
            database_ok = False
        return JSONResponse(
            {
                "ok": database_ok,
                "mode": "cloud",
                "database": "ready" if database_ok else "unavailable",
                "version": CLOUD_APP_VERSION,
            },
            status_code=200 if database_ok else 503,
        )

    @app.post("/api/auth/login")
    async def login(request: Request, payload: LoginRequest) -> JSONResponse:
        client_host = request.client.host if request.client else "unknown"
        login_key = hashlib.sha256(
            f"{client_host}:{payload.username.strip().casefold()}".encode("utf-8")
        ).hexdigest()
        allowed, retry_after = await login_limiter.consume(login_key)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="登录尝试过多，请稍后再试",
                headers={"Retry-After": str(retry_after)},
            )
        async with resolved_database.session_factory() as session:
            async with session.begin():
                try:
                    result = await auth.login(
                        session,
                        payload.username,
                        payload.password,
                        request.headers.get("user-agent", ""),
                    )
                except AuthenticationError as exc:
                    raise HTTPException(status_code=401, detail=str(exc)) from exc
        await login_limiter.reset(login_key)
        return login_response(result)

    @app.get("/api/auth/setup-status")
    async def setup_status() -> JSONResponse:
        async with resolved_database.session_factory() as session:
            async with session.begin():
                setup_required = await auth.initial_setup_required(session)
        response = JSONResponse({"setup_required": setup_required})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/auth/setup", status_code=201)
    async def setup_initial_admin(request: Request, payload: InitialSetupRequest) -> JSONResponse:
        client_host = request.client.host if request.client else "unknown"
        setup_key = hashlib.sha256(f"setup:{client_host}".encode("utf-8")).hexdigest()
        allowed, retry_after = await setup_limiter.consume(setup_key)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="初始化尝试过多，请稍后再试",
                headers={"Retry-After": str(retry_after)},
            )
        async with resolved_database.session_factory() as session:
            async with session.begin():
                try:
                    await auth.create_initial_admin(
                        session,
                        payload.username,
                        payload.display_name,
                        payload.password,
                    )
                    result = await auth.login(
                        session,
                        payload.username,
                        payload.password,
                        request.headers.get("user-agent", ""),
                    )
                except AuthenticationError as exc:
                    status_code = 409 if exc.code == "setup_closed" else 400
                    raise HTTPException(status_code=status_code, detail=str(exc)) from exc
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
        await setup_limiter.reset(setup_key)
        return login_response(result, status_code=201)

    @app.post("/api/auth/register", status_code=201)
    async def register(request: Request, payload: RegistrationRequest) -> JSONResponse:
        client_host = request.client.host if request.client else "unknown"
        registration_key = hashlib.sha256(f"register:{client_host}".encode("utf-8")).hexdigest()
        allowed, retry_after = await registration_limiter.consume(registration_key)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="注册尝试过多，请稍后再试",
                headers={"Retry-After": str(retry_after)},
            )
        async with resolved_database.session_factory() as session:
            async with session.begin():
                try:
                    invite = await auth.consume_registration_invite(session, payload.invite_code)
                    user = await auth.create_user(
                        session,
                        payload.username,
                        payload.display_name,
                        payload.password,
                    )
                    invite.used_at = datetime.now(timezone.utc)
                    invite.used_by_user_id = user.id
                    result = await auth.login(
                        session,
                        payload.username,
                        payload.password,
                        request.headers.get("user-agent", ""),
                    )
                except AuthenticationError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
        await registration_limiter.reset(registration_key)
        return login_response(result, status_code=201)

    @app.get("/api/auth/me")
    async def me(context: RequestContext = Depends(current_context)) -> dict:
        return _identity_payload(context.identity)

    @app.post("/api/auth/logout")
    async def logout(context: RequestContext = Depends(current_context)) -> JSONResponse:
        await auth.revoke_session(context.session, context.identity.session_id)
        response = JSONResponse({"ok": True})
        response.delete_cookie(resolved_settings.session_cookie_name, path="/")
        response.delete_cookie(resolved_settings.csrf_cookie_name, path="/")
        return response

    @app.post("/api/account/password")
    async def change_password(
        payload: PasswordChangeRequest,
        context: RequestContext = Depends(current_context),
    ) -> JSONResponse:
        user = await context.session.get(User, context.identity.user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="账号不存在")
        password_ok, _ = await asyncio.to_thread(
            verify_password,
            payload.current_password,
            user.password_hash,
        )
        if not password_ok:
            raise HTTPException(status_code=401, detail="当前密码不正确")
        if payload.current_password == payload.new_password:
            raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")
        user.password_hash = await asyncio.to_thread(hash_password, payload.new_password)
        user.password_changed_at = datetime.now(timezone.utc)
        await auth.revoke_all_user_sessions(context.session, context.identity.user_id)
        response = JSONResponse({"changed": True, "message": "密码已更新，请重新登录。"})
        response.delete_cookie(resolved_settings.session_cookie_name, path="/")
        response.delete_cookie(resolved_settings.csrf_cookie_name, path="/")
        return response

    @app.post("/api/account/username")
    async def change_username(
        payload: UsernameChangeRequest,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        user = await context.session.get(User, context.identity.user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="账号不存在")
        password_ok, _ = await asyncio.to_thread(verify_password, payload.current_password, user.password_hash)
        if not password_ok:
            raise HTTPException(status_code=401, detail="当前密码不正确")
        try:
            normalized = normalize_username(payload.new_username)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if normalized == user.username_normalized:
            raise HTTPException(status_code=400, detail="新用户名不能与当前用户名相同")
        existing = await context.session.scalar(
            select(User.id).where(User.username_normalized == normalized, User.id != user.id)
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="这个用户名已经被使用")
        user.username = payload.new_username.strip()
        user.username_normalized = normalized
        user.updated_at = datetime.now(timezone.utc)
        await context.session.flush()
        return {
            "changed": True,
            "username": user.username,
            "message": "登录用户名已更新，工作空间和 AI Agent 连接保持不变。",
        }

    @app.post("/api/account/invites", status_code=201)
    async def create_registration_invite(
        payload: InviteCreateRequest,
        context: RequestContext = Depends(current_context),
    ) -> JSONResponse:
        creator = await context.session.get(User, context.identity.user_id)
        if creator is None:
            raise HTTPException(status_code=404, detail="账号不存在")
        try:
            result = await auth.create_registration_invite(
                context.session,
                creator,
                datetime.now(timezone.utc) + timedelta(hours=payload.expires_in_hours),
            )
        except AuthenticationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        token = result.token
        response = JSONResponse(
            {
                "invite_code": token,
                "registration_url": f"{resolved_settings.public_origin}/?invite={quote(token, safe='')}",
                "expires_at": result.invite.expires_at.isoformat(),
                "note": "邀请码只能使用一次，请通过私密渠道发送给对应的新用户。",
            },
            status_code=201,
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/account/agent-token", status_code=201)
    async def issue_own_agent_token(
        payload: AgentTokenIssueRequest,
        context: RequestContext = Depends(current_context),
    ) -> JSONResponse:
        if payload.confirmation.strip() != "重新生成Agent令牌":
            raise HTTPException(status_code=400, detail="请输入“重新生成Agent令牌”进行确认")
        user = await context.session.get(User, context.identity.user_id)
        workspace = await context.session.get(Workspace, context.identity.workspace_id)
        if user is None or workspace is None:
            raise HTTPException(status_code=404, detail="账号不存在")
        password_ok, _ = await asyncio.to_thread(verify_password, payload.current_password, user.password_hash)
        if not password_ok:
            raise HTTPException(status_code=401, detail="当前密码不正确")
        result = await auth.create_agent_credential(context.session, workspace)
        response = JSONResponse(
            {
                "agent_token": result.token,
                "mcp_url": f"{resolved_settings.public_origin}/mcp/",
                "note": "令牌只显示这一次；旧 AI Agent 令牌已经失效。",
            },
            status_code=201,
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/account/delete", status_code=202)
    async def delete_account(
        payload: AccountDeletionRequest,
        context: RequestContext = Depends(current_context),
    ) -> JSONResponse:
        if payload.confirmation.strip() != "彻底删除我的数据":
            raise HTTPException(status_code=400, detail="请输入“彻底删除我的数据”进行确认")
        user = await context.session.get(User, context.identity.user_id)
        workspace = await context.session.get(Workspace, context.identity.workspace_id)
        if user is None or workspace is None:
            raise HTTPException(status_code=404, detail="账号不存在")
        password_ok, _ = await asyncio.to_thread(verify_password, payload.password, user.password_hash)
        if not password_ok:
            raise HTTPException(status_code=401, detail="密码不正确")
        existing = await context.session.scalar(
            select(DeletionRequest).where(
                DeletionRequest.workspace_id == context.identity.workspace_id,
                DeletionRequest.status.in_(("pending", "running")),
            )
        )
        if existing is None:
            context.session.add(
                DeletionRequest(
                    workspace_id=context.identity.workspace_id,
                    requested_by_user_id=context.identity.user_id,
                    execute_after=datetime.now(timezone.utc),
                )
            )
        user.status = "deleting"
        workspace.status = "deleting"
        await auth.revoke_all_user_sessions(context.session, context.identity.user_id)
        await context.session.execute(
            update(AgentCredential)
            .where(
                AgentCredential.workspace_id == context.identity.workspace_id,
                AgentCredential.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(timezone.utc))
        )
        response = JSONResponse(
            {
                "accepted": True,
                "message": "账号已注销，服务器正在彻底删除数据库记录和私人附件。",
            },
            status_code=202,
        )
        response.delete_cookie(resolved_settings.session_cookie_name, path="/")
        response.delete_cookie(resolved_settings.csrf_cookie_name, path="/")
        return response

    @app.get("/api/settings/profile")
    async def get_profile(context: RequestContext = Depends(current_context)) -> dict:
        settings_record = await context.session.scalar(
            select(WorkspaceSettings).where(
                WorkspaceSettings.workspace_id == context.identity.workspace_id
            )
        )
        if settings_record is None:
            raise HTTPException(status_code=404, detail="个人设置不存在")
        return dict(settings_record.profile)

    @app.get("/api/dashboard")
    async def dashboard(context: RequestContext = Depends(current_context)) -> dict:
        settings_record = await context.session.scalar(
            select(WorkspaceSettings).where(
                WorkspaceSettings.workspace_id == context.identity.workspace_id
            )
        )
        if settings_record is None:
            raise HTTPException(status_code=404, detail="个人设置不存在")
        repository = CoreRepository(
            context.session,
            context.identity.workspace_id,
            "user",
            context.identity.user_public_id,
        )
        projects = await repository.list_projects()
        tasks = await repository.list_tasks()
        greeting = await repository.get_daily_message()
        suggestion = await repository.latest_suggestion()
        health_repository = HealthRepository(
            context.session,
            context.identity.workspace_id,
            context.identity.workspace_public_id,
            "user",
            context.identity.user_public_id,
        )
        health = await health_repository.today_overview()
        recent_health_records = await health_repository.list_records(limit=6)
        growth_repository = GrowthRepository(
            context.session,
            context.identity.workspace_id,
            "user",
            context.identity.user_public_id,
        )
        growth = await growth_repository.list_plans()
        library = await growth_repository.list_library()
        content = await growth_repository.list_content(limit_per_category=12)
        grouped_tasks = {quadrant: [] for quadrant in QUADRANTS}
        for task in tasks:
            grouped_tasks.setdefault(task["quadrant"], []).append(task)
        upcoming = [
            task
            for task in tasks
            if task.get("due_at") and not task["done"]
        ][:5]
        completed = sum(1 for task in tasks if task["done"])
        health_settings = dict(settings_record.health)
        health = {
            "calories_kcal": 0,
            "exercise_kcal": 0,
            "meal_count": 0,
            "daily_advice": None,
            "recommendations": [],
            **health,
        }
        active_agent = await context.session.scalar(
            select(AgentCredential)
            .where(
                AgentCredential.workspace_id == context.identity.workspace_id,
                AgentCredential.revoked_at.is_(None),
            )
            .limit(1)
        )
        active_jobs = list(
            (
                await context.session.scalars(
                    select(AgentJob)
                    .where(
                        AgentJob.workspace_id == context.identity.workspace_id,
                        AgentJob.status.in_(("pending", "in_progress")),
                    )
                    .order_by(AgentJob.status == "pending", AgentJob.created_at, AgentJob.id)
                    .limit(5)
                )
            ).all()
        )
        recent_events = list(
            (
                await context.session.scalars(
                    select(WorkspaceEvent)
                    .where(WorkspaceEvent.workspace_id == context.identity.workspace_id)
                    .order_by(WorkspaceEvent.id.desc())
                    .limit(8)
                )
            ).all()
        )
        return {
            "date": greeting["date"],
            "profile": dict(settings_record.profile),
            "greeting": greeting,
            "preferences": {
                "health": health_settings,
                "ip": dict(settings_record.ip_preferences),
            },
            "projects": projects,
            "tasks": grouped_tasks,
            "upcoming_tasks": upcoming,
            "task_progress": {"completed": completed, "total": len(tasks)},
            "health": health,
            "growth": growth,
            "library": library,
            "health_records": recent_health_records,
            "content": content,
            "hermes": {
                "connected": bool(active_agent and active_agent.last_used_at),
                "label": "已接入" if active_agent else "尚未接入",
                "last_seen": active_agent.last_used_at.isoformat() if active_agent and active_agent.last_used_at else None,
                "pending_jobs": sum(1 for item in active_jobs if item.status == "pending"),
                "processing_jobs": sum(1 for item in active_jobs if item.status == "in_progress"),
                "current_job": _agent_job_payload(active_jobs[0]) if active_jobs else None,
            },
            "suggestion": suggestion,
            "activity": [
                {
                    "time": item.created_at.isoformat(),
                    "action": item.event_type,
                    "summary": item.payload.get("title") or item.entity_key,
                    "source": "agent" if item.event_type.startswith(("agent_job", "health.record_analyzed", "content.")) else "user",
                }
                for item in recent_events
            ],
            "index": {"documents": 0, "path": "postgresql"},
        }

    @app.get("/api/projects")
    async def list_projects(
        include_deleted: bool = Query(default=False),
        context: RequestContext = Depends(current_context),
    ) -> list[dict]:
        return await CoreRepository(
            context.session, context.identity.workspace_id, "user", context.identity.user_public_id
        ).list_projects(include_deleted=include_deleted)

    @app.get("/api/projects/deleted")
    async def list_deleted_projects(context: RequestContext = Depends(current_context)) -> list[dict]:
        projects = await CoreRepository(
            context.session, context.identity.workspace_id, "user", context.identity.user_public_id
        ).list_projects(include_deleted=True)
        return [project for project in projects if project["deleted"]]

    @app.post("/api/projects", status_code=201)
    async def create_project(
        payload: ProjectCreate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await CoreRepository(
                context.session, context.identity.workspace_id, "user", context.identity.user_public_id
            ).create_project(
                name=payload.name,
                description=payload.description,
                current_stage=payload.current_stage,
                progress_percent=payload.progress_percent,
                next_milestone=payload.next_milestone,
                start_date=payload.start_date,
                due_date=payload.due_date,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/projects/{project_id}")
    async def delete_project(
        project_id: str,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await CoreRepository(
                context.session, context.identity.workspace_id, "user", context.identity.user_public_id
            ).delete_project(_public_uuid(project_id, "项目"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="项目不存在") from exc

    @app.post("/api/projects/{project_id}/restore")
    async def restore_project(
        project_id: str,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await CoreRepository(
                context.session, context.identity.workspace_id, "user", context.identity.user_public_id
            ).restore_project(_public_uuid(project_id, "项目"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="项目不存在") from exc

    @app.get("/api/projects/{project_id}/plan")
    async def project_plan(
        project_id: str,
        include_deleted: bool = Query(default=False),
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await CoreRepository(
                context.session, context.identity.workspace_id, "user", context.identity.user_public_id
            ).project_plan(_public_uuid(project_id, "项目"), include_deleted=include_deleted)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="项目不存在") from exc

    @app.get("/api/projects/{project_id}/phases")
    async def list_project_phases(
        project_id: str,
        include_deleted: bool = Query(default=False),
        context: RequestContext = Depends(current_context),
    ) -> list[dict]:
        try:
            return await CoreRepository(
                context.session, context.identity.workspace_id, "user", context.identity.user_public_id
            ).list_phases(_public_uuid(project_id, "项目"), include_deleted=include_deleted)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="项目不存在") from exc

    @app.post("/api/projects/{project_id}/phases", status_code=201)
    async def create_project_phase(
        project_id: str,
        payload: ProjectPhaseCreate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await CoreRepository(
                context.session, context.identity.workspace_id, "user", context.identity.user_public_id
            ).create_phase(
                _public_uuid(project_id, "项目"),
                **payload.model_dump(),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="项目不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/project-phases/{phase_id}")
    async def update_project_phase(
        phase_id: str,
        payload: ProjectPhaseUpdate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await CoreRepository(
                context.session, context.identity.workspace_id, "user", context.identity.user_public_id
            ).update_phase(_public_uuid(phase_id, "阶段"), payload.model_dump(exclude_unset=True))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="阶段不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/project-phases/{phase_id}")
    async def delete_project_phase(
        phase_id: str,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await CoreRepository(
                context.session, context.identity.workspace_id, "user", context.identity.user_public_id
            ).delete_phase(_public_uuid(phase_id, "阶段"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="阶段不存在") from exc

    @app.post("/api/project-phases/{phase_id}/restore")
    async def restore_project_phase(
        phase_id: str,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await CoreRepository(
                context.session, context.identity.workspace_id, "user", context.identity.user_public_id
            ).restore_phase(_public_uuid(phase_id, "阶段"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="阶段不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.patch("/api/projects/{project_id}")
    async def update_project(
        project_id: str,
        payload: ProjectUpdate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await CoreRepository(
                context.session, context.identity.workspace_id, "user", context.identity.user_public_id
            ).update_project(
                _public_uuid(project_id, "项目"),
                payload.model_dump(exclude_unset=True),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="项目不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/tasks")
    async def list_tasks(context: RequestContext = Depends(current_context)) -> list[dict]:
        return await CoreRepository(
            context.session, context.identity.workspace_id, "user", context.identity.user_public_id
        ).list_tasks()

    @app.get("/api/tasks/deleted")
    async def list_deleted_tasks(context: RequestContext = Depends(current_context)) -> list[dict]:
        tasks = await CoreRepository(
            context.session, context.identity.workspace_id, "user", context.identity.user_public_id
        ).list_tasks(include_deleted=True)
        return [task for task in tasks if task["deleted"]]

    @app.post("/api/tasks", status_code=201)
    async def create_task(
        payload: TaskCreate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await CoreRepository(
                context.session, context.identity.workspace_id, "user", context.identity.user_public_id
            ).create_task(
                title=payload.title,
                quadrant=payload.quadrant,
                due_at=payload.due_at,
                note=payload.note,
                recurrence=payload.recurrence,
                project_public_id=payload.project_id,
                phase_public_id=payload.phase_id,
                start_date=payload.start_date,
                end_date=payload.end_date,
                status=payload.status,
                progress_percent=payload.progress_percent,
                is_milestone=payload.is_milestone,
                order_index=payload.order_index,
                predecessor_public_ids=payload.predecessor_ids,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/tasks/{task_id}")
    async def update_task(
        task_id: str,
        payload: TaskUpdate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await CoreRepository(
                context.session, context.identity.workspace_id, "user", context.identity.user_public_id
            ).update_task(
                _public_uuid(task_id, "任务"),
                payload.model_dump(exclude_unset=True),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="任务不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/tasks/{task_id}")
    async def delete_task(
        task_id: str,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await CoreRepository(
                context.session, context.identity.workspace_id, "user", context.identity.user_public_id
            ).delete_task(_public_uuid(task_id, "任务"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="任务不存在") from exc

    @app.post("/api/tasks/{task_id}/restore")
    async def restore_task(
        task_id: str,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await CoreRepository(
                context.session, context.identity.workspace_id, "user", context.identity.user_public_id
            ).restore_task(_public_uuid(task_id, "任务"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="任务不存在") from exc

    @app.get("/api/calendar")
    async def calendar(
        start_date: date,
        end_date: date,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await CoreRepository(
                context.session, context.identity.workspace_id, "user", context.identity.user_public_id
            ).calendar(start_date, end_date)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/greeting", status_code=201)
    async def save_daily_message(
        payload: DailyMessageCreate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await CoreRepository(
                context.session, context.identity.workspace_id, "user", context.identity.user_public_id
            ).save_daily_message(payload.message, payload.tone)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/settings/profile")
    async def update_profile(
        payload: ProfileUpdate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        settings_record = await context.session.scalar(
            select(WorkspaceSettings).where(
                WorkspaceSettings.workspace_id == context.identity.workspace_id
            )
        )
        user = await context.session.get(User, context.identity.user_id)
        if settings_record is None or user is None:
            raise HTTPException(status_code=404, detail="个人设置不存在")
        settings_record.profile = {
            **dict(settings_record.profile),
            "nickname": payload.nickname,
            "daily_message_style": payload.daily_message_style,
        }
        user.display_name = payload.nickname
        context.session.add(
            WorkspaceEvent(
                workspace_id=context.identity.workspace_id,
                event_type="profile.updated",
                entity_type="workspace_settings",
                entity_key=str(context.identity.workspace_public_id),
                payload={},
            )
        )
        return dict(settings_record.profile)

    @app.put("/api/settings/ip")
    async def update_ip_preferences(
        payload: IPPreferencesUpdate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        settings_record = await context.session.scalar(
            select(WorkspaceSettings).where(
                WorkspaceSettings.workspace_id == context.identity.workspace_id
            )
        )
        if settings_record is None:
            raise HTTPException(status_code=404, detail="个人 IP 设置不存在")
        preferences = {
            "video_topics": list(dict.fromkeys(item.strip() for item in payload.video_topics if item.strip())),
            "ai_topics": list(dict.fromkeys(item.strip() for item in payload.ai_topics if item.strip())),
        }
        settings_record.ip_preferences = preferences
        context.session.add(
            WorkspaceEvent(
                workspace_id=context.identity.workspace_id,
                event_type="settings.ip_updated",
                entity_type="workspace_settings",
                entity_key=str(context.identity.workspace_public_id),
                payload={},
            )
        )
        return preferences

    @app.get("/api/settings/health")
    async def get_health_goals(context: RequestContext = Depends(current_context)) -> dict:
        settings_record = await context.session.scalar(
            select(WorkspaceSettings).where(
                WorkspaceSettings.workspace_id == context.identity.workspace_id
            )
        )
        if settings_record is None:
            raise HTTPException(status_code=404, detail="健康设置不存在")
        return dict(settings_record.health)

    @app.put("/api/settings/health")
    async def update_health_goals(
        payload: HealthGoalsUpdate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        repository = HealthRepository(
            context.session,
            context.identity.workspace_id,
            context.identity.workspace_public_id,
            "user",
            context.identity.user_public_id,
        )
        return await repository.update_goals(**payload.model_dump())

    @app.post("/api/health/water")
    async def record_water(
        payload: WaterRecord,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        return await HealthRepository(
            context.session,
            context.identity.workspace_id,
            context.identity.workspace_public_id,
            "user",
            context.identity.user_public_id,
        ).record_water(payload.ml, record_date=payload.record_date)

    @app.post("/api/health/weight")
    async def record_weight(
        payload: WeightRecord,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        return await HealthRepository(
            context.session,
            context.identity.workspace_id,
            context.identity.workspace_public_id,
            "user",
            context.identity.user_public_id,
        ).record_weight(payload.kg, record_date=payload.record_date)

    async def _store_health_upload(
        kind: str,
        file: UploadFile,
        record_date: str | None,
        meal_slot: str | None,
        idempotency_key: str | None,
        repository: HealthRepository,
        source: str,
    ) -> dict:
        if kind not in {"meal", "weight", "exercise"}:
            raise HTTPException(status_code=400, detail="不支持的上传类型")
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="图片不能超过 15MB")
        try:
            normalized = await asyncio.to_thread(normalize_health_image, content)
            target_date = date.fromisoformat(record_date) if record_date else date.today()
            if kind == "meal" and not meal_slot:
                meal_slot = "lunch"
            key = (idempotency_key or f"upload:{uuid.uuid4()}")[:160]
            return await repository.create_upload(
                kind,
                file.filename or f"{kind}.jpg",
                normalized,
                object_store,
                key,
                target_date,
                meal_slot,
                source=source,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/uploads/{kind}", status_code=201)
    async def upload_health_record(
        kind: str,
        file: UploadFile = File(...),
        record_date: str | None = Form(default=None),
        meal_slot: str | None = Form(default=None),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        context: RequestContext = Depends(current_context),
    ) -> dict:
        return await _store_health_upload(
            kind,
            file,
            record_date,
            meal_slot,
            idempotency_key,
            HealthRepository(
                context.session,
                context.identity.workspace_id,
                context.identity.workspace_public_id,
                "user",
                context.identity.user_public_id,
            ),
            "user",
        )

    @app.get("/api/health/records")
    async def list_health_records(
        status: str | None = None,
        context: RequestContext = Depends(current_context),
    ) -> list[dict]:
        return await HealthRepository(
            context.session,
            context.identity.workspace_id,
            context.identity.workspace_public_id,
            "user",
            context.identity.user_public_id,
        ).list_records(status=status)

    @app.get("/api/health/records/page")
    async def page_health_records(
        start_date: date | None = Query(default=None),
        end_date: date | None = Query(default=None),
        kind: str | None = Query(default=None, pattern="^(meal|weight_photo|exercise)$"),
        status: str | None = Query(default=None, pattern="^(queued|in_progress|analyzed|failed)$"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=8, ge=1, le=30),
        context: RequestContext = Depends(current_context),
    ) -> dict:
        if (start_date is None) != (end_date is None):
            raise HTTPException(status_code=400, detail="健康明细筛选必须同时填写开始和结束日期")
        return await HealthRepository(
            context.session,
            context.identity.workspace_id,
            context.identity.workspace_public_id,
            "user",
            context.identity.user_public_id,
        ).list_records_page(
            start_date=start_date,
            end_date=end_date,
            kind=kind,
            status=status,
            page=page,
            page_size=page_size,
        )

    @app.get("/api/health/records/deleted")
    async def list_deleted_health_records(
        context: RequestContext = Depends(current_context),
    ) -> list[dict]:
        records = await HealthRepository(
            context.session,
            context.identity.workspace_id,
            context.identity.workspace_public_id,
            "user",
            context.identity.user_public_id,
        ).list_records(include_deleted=True)
        return [record for record in records if record["deleted"]]

    @app.patch("/api/health/records/{record_id}")
    async def update_health_record(
        record_id: str,
        payload: HealthRecordUpdate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await HealthRepository(
                context.session,
                context.identity.workspace_id,
                context.identity.workspace_public_id,
                "user",
                context.identity.user_public_id,
            ).update_record(
                _public_uuid(record_id, "健康记录"),
                payload.record_date,
                payload.meal_slot,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="健康记录不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/health/records/{record_id}")
    async def delete_health_record(
        record_id: str,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await HealthRepository(
                context.session,
                context.identity.workspace_id,
                context.identity.workspace_public_id,
                "user",
                context.identity.user_public_id,
            ).set_deleted(_public_uuid(record_id, "健康记录"), True)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="健康记录不存在") from exc

    @app.post("/api/health/records/{record_id}/restore")
    async def restore_health_record(
        record_id: str,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await HealthRepository(
                context.session,
                context.identity.workspace_id,
                context.identity.workspace_public_id,
                "user",
                context.identity.user_public_id,
            ).set_deleted(_public_uuid(record_id, "健康记录"), False)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="健康记录不存在") from exc

    @app.get("/api/health/history")
    async def health_history(
        days: int = Query(default=30, ge=1, le=366),
        start_date: date | None = Query(default=None),
        end_date: date | None = Query(default=None),
        context: RequestContext = Depends(current_context),
    ) -> dict:
        if (start_date is None) != (end_date is None):
            raise HTTPException(status_code=400, detail="自定义周期需要同时填写开始日期和结束日期")
        end = end_date or date.today()
        start = start_date or (end - timedelta(days=days - 1))
        try:
            return await HealthRepository(
                context.session,
                context.identity.workspace_id,
                context.identity.workspace_public_id,
                "user",
                context.identity.user_public_id,
            ).history(start, end)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/health/records/{record_id}/analysis")
    async def analyze_health_record(
        record_id: str,
        payload: HealthAnalysisCreate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await HealthRepository(
                context.session,
                context.identity.workspace_id,
                context.identity.workspace_public_id,
                "user",
                context.identity.user_public_id,
            ).analyze_record(
                _public_uuid(record_id, "健康记录"),
                payload.summary,
                payload.advice,
                payload.calories_kcal,
                payload.exercise_kcal,
                payload.weight_kg,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="健康记录不存在") from exc

    @app.post("/api/health/advice", status_code=201)
    async def save_health_advice(
        payload: DailyHealthAdviceCreate,
        target_date: date | None = Query(default=None),
        context: RequestContext = Depends(current_context),
    ) -> dict:
        return await HealthRepository(
            context.session,
            context.identity.workspace_id,
            context.identity.workspace_public_id,
            "user",
            context.identity.user_public_id,
        ).save_daily_advice(
            target_date or date.today(),
            payload.status,
            payload.overall_summary or payload.summary,
            payload.diet_summary,
            payload.hydration_summary,
            payload.exercise_summary,
            generated_by="user",
        )

    def growth_repository(context: RequestContext) -> GrowthRepository:
        return GrowthRepository(
            context.session,
            context.identity.workspace_id,
            "user",
            context.identity.user_public_id,
        )

    @app.post("/api/growth/plans", status_code=201)
    async def create_learning_plan(
        payload: LearningPlanCreate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        return await growth_repository(context).create_plan(payload.name, payload.goal, "user")

    @app.get("/api/growth/plans")
    async def list_learning_plans(
        context: RequestContext = Depends(current_context),
    ) -> list[dict]:
        return await growth_repository(context).list_plans()

    @app.get("/api/growth/plans/deleted")
    async def list_deleted_learning_plans(
        context: RequestContext = Depends(current_context),
    ) -> list[dict]:
        plans = await growth_repository(context).list_plans(include_deleted=True)
        return [plan for plan in plans if plan["deleted"]]

    @app.get("/api/growth/plans/{plan_id}")
    async def get_learning_plan(
        plan_id: str,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await growth_repository(context).get_plan(_public_uuid(plan_id, "学习计划"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="学习计划不存在") from exc

    @app.patch("/api/growth/plans/{plan_id}")
    async def update_learning_plan(
        plan_id: str,
        payload: LearningPlanUpdate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await growth_repository(context).update_plan(
                _public_uuid(plan_id, "学习计划"),
                payload.model_dump(exclude_unset=True),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="学习计划不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/growth/plans/{plan_id}/progress")
    async def update_learning_progress(
        plan_id: str,
        payload: LearningPlanProgressUpdate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await growth_repository(context).update_plan_progress(
                _public_uuid(plan_id, "学习计划"),
                payload.completed_lessons,
                payload.status,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="学习计划不存在") from exc

    @app.delete("/api/growth/plans/{plan_id}")
    async def delete_learning_plan(
        plan_id: str,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await growth_repository(context).set_plan_deleted(
                _public_uuid(plan_id, "学习计划"), True
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="学习计划不存在") from exc

    @app.post("/api/growth/plans/{plan_id}/restore")
    async def restore_learning_plan(
        plan_id: str,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await growth_repository(context).set_plan_deleted(
                _public_uuid(plan_id, "学习计划"), False
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="学习计划不存在") from exc

    @app.post("/api/library", status_code=201)
    async def create_library_item(
        payload: LibraryItemCreate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        return await growth_repository(context).create_library_item(
            payload.title, payload.kind, payload.reason, "user"
        )

    @app.get("/api/library/{item_id}")
    async def get_library_item(
        item_id: str,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await growth_repository(context).get_library_item(
                _public_uuid(item_id, "书影音条目")
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="书影音条目不存在") from exc

    @app.patch("/api/library/{item_id}")
    async def update_library_item(
        item_id: str,
        payload: LibraryItemUpdate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await growth_repository(context).update_library_item(
                _public_uuid(item_id, "书影音条目"),
                payload.model_dump(exclude_unset=True),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="书影音条目不存在") from exc

    @app.get("/api/content/{item_id}")
    async def get_content_item(
        item_id: str,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await growth_repository(context).get_content_item(
                _public_uuid(item_id, "专栏内容")
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="专栏内容不存在") from exc

    @app.get("/api/workbench-assets/{asset_path:path}")
    async def private_workbench_asset(
        asset_path: str,
        context: RequestContext = Depends(current_context),
    ) -> FileResponse:
        parts = asset_path.strip("/").split("/")
        if len(parts) != 2 or parts[0] != "objects":
            raise HTTPException(status_code=404, detail="附件不存在")
        object_public_id = _public_uuid(parts[1], "附件")
        stored = await context.session.scalar(
            select(StoredObject).where(
                StoredObject.workspace_id == context.identity.workspace_id,
                StoredObject.public_id == object_public_id,
                StoredObject.status == "ready",
                StoredObject.deleted_at.is_(None),
            )
        )
        if stored is None:
            raise HTTPException(status_code=404, detail="附件不存在")
        try:
            target = object_store.path_for_read(stored.object_key)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="附件不存在") from exc
        return FileResponse(
            target,
            media_type=stored.content_type,
            headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
        )

    def finance_repository(context: RequestContext) -> FinanceRepository:
        return FinanceRepository(
            context.session,
            context.identity.workspace_id,
            "user",
            context.identity.user_public_id,
        )

    @app.get("/api/finance/categories")
    async def list_finance_categories(
        include_inactive: bool = False,
        context: RequestContext = Depends(current_context),
    ) -> list[dict]:
        return await finance_repository(context).list_categories(include_inactive)

    @app.post("/api/finance/categories", status_code=201)
    async def create_finance_category(
        payload: FinanceCategoryCreate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await finance_repository(context).create_category(
                payload.category_type, payload.name, payload.icon, payload.color
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/finance/categories/{category_id}")
    async def update_finance_category(
        category_id: str,
        payload: FinanceCategoryUpdate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await finance_repository(context).update_category(
                _public_uuid(category_id, "财务分类"),
                payload.model_dump(exclude_unset=True),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="财务分类不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/finance/accounts")
    async def list_finance_accounts(
        include_archived: bool = False,
        context: RequestContext = Depends(current_context),
    ) -> list[dict]:
        return await finance_repository(context).list_accounts(include_archived)

    @app.get("/api/finance/accounts/{account_id}/detail")
    async def get_finance_account_detail(
        account_id: str,
        selected_date: date = Query(alias="date"),
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await finance_repository(context).account_detail(
                _public_uuid(account_id, "财务账户"),
                selected_date,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="财务账户不存在") from exc

    @app.post("/api/finance/accounts", status_code=201)
    async def create_finance_account(
        payload: FinanceAccountCreate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await finance_repository(context).create_account(
                payload.name,
                payload.account_type,
                yuan_to_minor(payload.opening_balance_yuan),
                payload.currency,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/finance/accounts/{account_id}")
    async def update_finance_account(
        account_id: str,
        payload: FinanceAccountUpdate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await finance_repository(context).update_account(
                _public_uuid(account_id, "财务账户"),
                payload.model_dump(exclude_unset=True),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="财务账户不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/finance/transactions")
    async def list_finance_transactions(
        start_date: date | None = Query(default=None),
        end_date: date | None = Query(default=None),
        transaction_type: str | None = Query(default=None, pattern="^(income|expense|transfer|refund)$"),
        category_id: str | None = Query(default=None),
        account_id: str | None = Query(default=None),
        search: str | None = Query(default=None, max_length=100),
        include_deleted: bool = False,
        cursor: str | None = Query(default=None),
        limit: int = Query(default=30, ge=1, le=100),
        page: int | None = Query(default=None, ge=1),
        page_size: int = Query(default=12, ge=1, le=50),
        context: RequestContext = Depends(current_context),
    ) -> dict:
        if (start_date is None) != (end_date is None):
            raise HTTPException(status_code=400, detail="日期筛选必须同时填写开始和结束日期")
        try:
            return await finance_repository(context).list_transactions(
                start_date=start_date,
                end_date=end_date,
                transaction_type=transaction_type,
                category_public_id=_public_uuid(category_id, "财务分类") if category_id else None,
                account_public_id=_public_uuid(account_id, "财务账户") if account_id else None,
                search=search,
                include_deleted=include_deleted,
                cursor=cursor,
                limit=page_size if page is not None else limit,
                page=page,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/finance/transactions", status_code=201)
    async def create_finance_transaction(
        payload: FinanceTransactionCreate,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await finance_repository(context).create_transaction(
                transaction_type=payload.transaction_type,
                amount_minor=yuan_to_minor(payload.amount_yuan),
                occurred_at=payload.occurred_at,
                local_date=payload.local_date,
                category_public_id=payload.category_id,
                account_public_id=payload.account_id,
                to_account_public_id=payload.to_account_id,
                refund_of_public_id=payload.refund_of_id,
                merchant=payload.merchant,
                purpose=payload.purpose,
                note=payload.note,
                tags=payload.tags,
                is_fixed=payload.is_fixed,
                is_necessary=payload.is_necessary,
                currency=payload.currency,
                idempotency_key=(idempotency_key or f"finance:{uuid.uuid4()}")[:160],
                source="user",
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/finance/transactions/{transaction_id}")
    async def get_finance_transaction(
        transaction_id: str,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await finance_repository(context).get_transaction(
                _public_uuid(transaction_id, "财务记录")
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="财务记录不存在") from exc

    @app.patch("/api/finance/transactions/{transaction_id}")
    async def update_finance_transaction(
        transaction_id: str,
        payload: FinanceTransactionUpdate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await finance_repository(context).update_transaction(
                _public_uuid(transaction_id, "财务记录"),
                payload.model_dump(exclude_unset=True),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="财务记录不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/finance/transactions/{transaction_id}")
    async def delete_finance_transaction(
        transaction_id: str,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await finance_repository(context).set_deleted(
                _public_uuid(transaction_id, "财务记录"), True
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="财务记录不存在") from exc

    @app.post("/api/finance/transactions/{transaction_id}/restore")
    async def restore_finance_transaction(
        transaction_id: str,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await finance_repository(context).set_deleted(
                _public_uuid(transaction_id, "财务记录"), False
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="财务记录不存在") from exc

    @app.get("/api/finance/summary")
    async def finance_summary(
        start_date: date | None = Query(default=None),
        end_date: date | None = Query(default=None),
        context: RequestContext = Depends(current_context),
    ) -> dict:
        if (start_date is None) != (end_date is None):
            raise HTTPException(status_code=400, detail="统计周期必须同时填写开始和结束日期")
        end = end_date or date.today()
        start = start_date or end.replace(day=1)
        try:
            return await finance_repository(context).summary(start, end)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/finance/archive")
    async def finance_archive(
        start_month: date,
        end_month: date,
        context: RequestContext = Depends(current_context),
    ) -> list[dict]:
        try:
            return await finance_repository(context).archive(start_month, end_month)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/finance/recurring")
    async def list_finance_recurring_rules(
        include_inactive: bool = False,
        context: RequestContext = Depends(current_context),
    ) -> list[dict]:
        return await finance_repository(context).list_recurring_rules(include_inactive)

    @app.post("/api/finance/recurring", status_code=201)
    async def create_finance_recurring_rule(
        payload: FinanceRecurringRuleCreate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await finance_repository(context).create_recurring_rule(
                name=payload.name,
                transaction_type=payload.transaction_type,
                amount_minor=yuan_to_minor(payload.amount_yuan),
                category_public_id=payload.category_id,
                account_public_id=payload.account_id,
                to_account_public_id=payload.to_account_id,
                frequency=payload.frequency,
                interval_count=payload.interval_count,
                next_due_date=payload.next_due_date,
                purpose=payload.purpose,
                currency=payload.currency,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/finance/recurring/{rule_id}")
    async def update_finance_recurring_rule(
        rule_id: str,
        payload: FinanceRecurringRuleUpdate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await finance_repository(context).update_recurring_rule(
                _public_uuid(rule_id, "周期规则"),
                payload.model_dump(exclude_unset=True),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="周期规则不存在") from exc

    @app.put("/api/finance/budgets")
    async def upsert_finance_budget(
        payload: FinanceBudgetUpsert,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await finance_repository(context).upsert_budget(
                period_start=payload.period_start,
                period_end=payload.period_end,
                amount_minor=yuan_to_minor(payload.amount_yuan),
                category_public_id=payload.category_id,
                currency=payload.currency,
                rollover=payload.rollover,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/finance/budgets")
    async def list_finance_budgets(
        start_date: date | None = Query(default=None),
        end_date: date | None = Query(default=None),
        include_archived: bool = False,
        context: RequestContext = Depends(current_context),
    ) -> list[dict]:
        if (start_date is None) != (end_date is None):
            raise HTTPException(status_code=400, detail="预算筛选必须同时填写开始和结束日期")
        return await finance_repository(context).list_budgets(
            start_date,
            end_date,
            include_archived,
        )

    @app.delete("/api/finance/budgets/{budget_id}")
    async def delete_finance_budget(
        budget_id: str,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await finance_repository(context).delete_budget(
                _public_uuid(budget_id, "财务预算")
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="财务预算不存在") from exc

    @app.get("/api/finance/goals")
    async def list_savings_goals(
        context: RequestContext = Depends(current_context),
    ) -> list[dict]:
        return await finance_repository(context).list_goals()

    @app.post("/api/finance/goals", status_code=201)
    async def create_savings_goal(
        payload: SavingsGoalCreate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        return await finance_repository(context).create_goal(
            payload.name,
            yuan_to_minor(payload.target_amount_yuan),
            yuan_to_minor(payload.current_amount_yuan),
            payload.target_date,
            payload.currency,
        )

    @app.patch("/api/finance/goals/{goal_id}")
    async def update_savings_goal(
        goal_id: str,
        payload: SavingsGoalUpdate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        try:
            return await finance_repository(context).update_goal(
                _public_uuid(goal_id, "储蓄目标"),
                payload.model_dump(exclude_unset=True),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="储蓄目标不存在") from exc

    @app.get("/api/finance/insights")
    async def list_finance_insights(
        limit: int = Query(default=12, ge=1, le=50),
        context: RequestContext = Depends(current_context),
    ) -> list[dict]:
        return await finance_repository(context).list_insights(limit)

    @app.post("/api/finance/insights", status_code=201)
    async def create_finance_insight(
        payload: FinanceInsightCreate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        return await finance_repository(context).save_insight(
            **payload.model_dump(), source="user"
        )

    @app.get("/api/system/info")
    async def cloud_system_info(
        context: RequestContext = Depends(current_context),
    ) -> dict:
        stored_bytes = await context.session.scalar(
            select(func.coalesce(func.sum(StoredObject.size_bytes), 0)).where(
                StoredObject.workspace_id == context.identity.workspace_id,
                StoredObject.status == "ready",
                StoredObject.deleted_at.is_(None),
            )
        )
        return {
            "mode": "cloud",
            "app_version": CLOUD_APP_VERSION,
            "packaged": True,
            "storage": {
                "size_mb": round(int(stored_bytes or 0) / 1024 / 1024, 2),
                "data_path": "阿里云私有数据库与附件卷",
                "backup_path": "按账号生成的 ZIP 导出",
            },
            "startup": {
                "available": False,
                "enabled": True,
                "label": "云端服务持续运行，无需手机或电脑开机",
            },
            "remote_access": {
                "installed": True,
                "connected": True,
                "url": resolved_settings.public_origin,
                "label": "已通过 HTTPS 连接云端",
            },
        }

    @app.get("/api/system/backups")
    async def cloud_exports(
        context: RequestContext = Depends(current_context),
    ) -> list[dict]:
        exports = await ExportRepository(
            context.session,
            context.identity.workspace_id,
            context.identity.workspace_public_id,
            object_store,
        ).list_exports()
        return [
            {
                **item,
                "name": item["id"],
                "size_mb": None,
                "app_version": CLOUD_APP_VERSION,
            }
            for item in exports
        ]

    @app.post("/api/system/backups", status_code=201)
    async def create_cloud_export(
        context: RequestContext = Depends(current_context),
    ) -> dict:
        result = await ExportRepository(
            context.session,
            context.identity.workspace_id,
            context.identity.workspace_public_id,
            object_store,
        ).create_export()
        context.session.add(
            WorkspaceEvent(
                workspace_id=context.identity.workspace_id,
                event_type="data.export_ready",
                entity_type="data_export",
                entity_key=result["id"],
                payload={},
            )
        )
        return {**result, "name": result["id"], "app_version": CLOUD_APP_VERSION}

    @app.get("/api/system/backups/{export_id}")
    async def download_cloud_export(
        export_id: str,
        context: RequestContext = Depends(current_context),
    ) -> FileResponse:
        try:
            _, stored, path = await ExportRepository(
                context.session,
                context.identity.workspace_id,
                context.identity.workspace_public_id,
                object_store,
            ).export_file(_public_uuid(export_id, "数据导出"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="数据导出不存在或已经过期") from exc
        return FileResponse(
            path,
            media_type="application/zip",
            filename=stored.original_filename,
            headers={"Cache-Control": "private, no-store"},
        )

    @app.post("/api/system/backups/{export_id}/restore")
    async def reject_cloud_restore(
        export_id: str,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        del export_id, context
        raise HTTPException(status_code=409, detail="云端导出用于迁移与自留备份，不支持覆盖恢复；导入功能将在校验后单独提供")

    @app.put("/api/system/startup")
    async def cloud_startup_setting(
        payload: StartupUpdate,
        context: RequestContext = Depends(current_context),
    ) -> dict:
        del payload, context
        return {"available": False, "enabled": True, "label": "云端服务持续运行"}

    @app.post("/api/system/remote-access")
    async def cloud_remote_access(
        context: RequestContext = Depends(current_context),
    ) -> dict:
        del context
        return {"enabled": True, "url": resolved_settings.public_origin}

    @app.get("/api/agent/me")
    async def agent_me(context: AgentRequestContext = Depends(agent_context)) -> dict:
        return {
            "credential_id": str(context.identity.credential_public_id),
            "workspace_id": str(context.identity.workspace_public_id),
            "scopes": list(context.identity.scopes),
        }

    @app.post("/api/agent/uploads/{kind}", status_code=201)
    async def agent_upload_health_record(
        kind: str,
        file: UploadFile = File(...),
        record_date: str | None = Form(default=None),
        meal_slot: str | None = Form(default=None),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "attachments:write")
        return await _store_health_upload(
            kind,
            file,
            record_date,
            meal_slot,
            idempotency_key,
            HealthRepository(
                context.session,
                context.identity.workspace_id,
                context.identity.workspace_public_id,
                "agent",
                context.identity.credential_public_id,
            ),
            "hermes",
        )

    @app.post("/api/agent/jobs/claim")
    async def agent_claim_job(
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "jobs:claim")
        job = await claim_next_job(
            context.session,
            context.identity.workspace_id,
            context.identity.credential_id,
        )
        return {"job": _agent_job_payload(job) if job else None}

    @app.post("/api/agent/jobs/{job_id}/complete")
    async def agent_complete_job(
        job_id: str,
        payload: AgentJobCompleteRequest,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "jobs:claim")
        try:
            job = await complete_job(
                context.session,
                context.identity.workspace_id,
                context.identity.credential_id,
                _public_uuid(job_id, "AI Agent 任务"),
                payload.result_summary,
                payload.succeeded,
                payload.error_code,
            )
            return _agent_job_payload(job)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="AI Agent 任务不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/agent/health/records/{record_id}")
    async def agent_get_health_record(
        record_id: str,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:read")
        try:
            return await HealthRepository(
                context.session,
                context.identity.workspace_id,
                context.identity.workspace_public_id,
                "agent",
                context.identity.credential_public_id,
            ).get_record(_public_uuid(record_id, "健康记录"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="健康记录不存在") from exc

    @app.patch("/api/agent/health/records/{record_id}")
    async def agent_update_health_record(
        record_id: str,
        payload: HealthRecordUpdate,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        try:
            return await HealthRepository(
                context.session,
                context.identity.workspace_id,
                context.identity.workspace_public_id,
                "agent",
                context.identity.credential_public_id,
            ).update_record(
                _public_uuid(record_id, "健康记录"),
                payload.record_date,
                payload.meal_slot,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="健康记录不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/agent/health/records/{record_id}")
    async def agent_delete_health_record(
        record_id: str,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        try:
            return await HealthRepository(
                context.session,
                context.identity.workspace_id,
                context.identity.workspace_public_id,
                "agent",
                context.identity.credential_public_id,
            ).set_deleted(_public_uuid(record_id, "健康记录"), True)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="健康记录不存在") from exc

    @app.post("/api/agent/health/records/{record_id}/restore")
    async def agent_restore_health_record(
        record_id: str,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        try:
            return await HealthRepository(
                context.session,
                context.identity.workspace_id,
                context.identity.workspace_public_id,
                "agent",
                context.identity.credential_public_id,
            ).set_deleted(_public_uuid(record_id, "健康记录"), False)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="健康记录不存在") from exc

    @app.post("/api/agent/health/records/{record_id}/analysis")
    async def agent_analyze_health_record(
        record_id: str,
        payload: HealthAnalysisCreate,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        try:
            return await HealthRepository(
                context.session,
                context.identity.workspace_id,
                context.identity.workspace_public_id,
                "agent",
                context.identity.credential_public_id,
            ).analyze_record(
                _public_uuid(record_id, "健康记录"),
                payload.summary,
                payload.advice,
                payload.calories_kcal,
                payload.exercise_kcal,
                payload.weight_kg,
                model_name="hermes",
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="健康记录不存在") from exc

    @app.post("/api/agent/health/advice", status_code=201)
    async def agent_save_health_advice(
        payload: DailyHealthAdviceCreate,
        target_date: date | None = Query(default=None),
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        return await HealthRepository(
            context.session,
            context.identity.workspace_id,
            context.identity.workspace_public_id,
            "agent",
            context.identity.credential_public_id,
        ).save_daily_advice(
            target_date or date.today(),
            payload.status,
            payload.overall_summary or payload.summary,
            payload.diet_summary,
            payload.hydration_summary,
            payload.exercise_summary,
            generated_by="hermes",
        )

    @app.get("/api/agent/assets/{object_id}")
    async def agent_private_asset(
        object_id: str,
        context: AgentRequestContext = Depends(agent_context),
    ) -> FileResponse:
        require_agent_scope(context, "workbench:read")
        stored = await context.session.scalar(
            select(StoredObject).where(
                StoredObject.workspace_id == context.identity.workspace_id,
                StoredObject.public_id == _public_uuid(object_id, "附件"),
                StoredObject.status == "ready",
                StoredObject.deleted_at.is_(None),
            )
        )
        if stored is None:
            raise HTTPException(status_code=404, detail="附件不存在")
        try:
            target = object_store.path_for_read(stored.object_key)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="附件不存在") from exc
        return FileResponse(
            target,
            media_type=stored.content_type,
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )

    def agent_finance_repository(context: AgentRequestContext) -> FinanceRepository:
        return FinanceRepository(
            context.session,
            context.identity.workspace_id,
            "agent",
            context.identity.credential_public_id,
        )

    @app.post("/api/agent/finance/transactions", status_code=201)
    async def agent_create_finance_transaction(
        payload: FinanceTransactionCreate,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        try:
            return await agent_finance_repository(context).create_transaction(
                transaction_type=payload.transaction_type,
                amount_minor=yuan_to_minor(payload.amount_yuan),
                occurred_at=payload.occurred_at,
                local_date=payload.local_date,
                category_public_id=payload.category_id,
                account_public_id=payload.account_id,
                to_account_public_id=payload.to_account_id,
                refund_of_public_id=payload.refund_of_id,
                merchant=payload.merchant,
                purpose=payload.purpose,
                note=payload.note,
                tags=payload.tags,
                is_fixed=payload.is_fixed,
                is_necessary=payload.is_necessary,
                currency=payload.currency,
                idempotency_key=(idempotency_key or f"hermes-finance:{uuid.uuid4()}")[:160],
                source="hermes",
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/agent/finance/summary")
    async def agent_finance_summary(
        start_date: date,
        end_date: date,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:read")
        try:
            return await agent_finance_repository(context).summary(start_date, end_date)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/agent/finance/insights", status_code=201)
    async def agent_create_finance_insight(
        payload: FinanceInsightCreate,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        return await agent_finance_repository(context).save_insight(
            **payload.model_dump(), source="hermes"
        )

    def agent_growth_repository(context: AgentRequestContext) -> GrowthRepository:
        return GrowthRepository(
            context.session,
            context.identity.workspace_id,
            "agent",
            context.identity.credential_public_id,
        )

    @app.get("/api/agent/settings/ip")
    async def agent_get_ip_preferences(
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:read")
        settings_record = await context.session.scalar(
            select(WorkspaceSettings).where(
                WorkspaceSettings.workspace_id == context.identity.workspace_id
            )
        )
        if settings_record is None:
            raise HTTPException(status_code=404, detail="个人 IP 设置不存在")
        return dict(settings_record.ip_preferences)

    @app.post("/api/agent/growth/plans/{plan_id}/generated")
    async def agent_update_generated_learning_plan(
        plan_id: str,
        payload: LearningPlanGeneratedUpdate,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        try:
            return await agent_growth_repository(context).update_generated_plan(
                _public_uuid(plan_id, "学习计划"),
                payload.roadmap_markdown,
                payload.status,
                payload.total_lessons,
                payload.completed_lessons,
                [item.model_dump(mode="json") for item in payload.resources],
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="学习计划不存在") from exc

    @app.post("/api/agent/library", status_code=201)
    async def agent_create_library_item(
        payload: LibraryItemCreate,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        return await agent_growth_repository(context).create_library_item(
            payload.title, payload.kind, payload.reason, "hermes"
        )

    @app.patch("/api/agent/library/{item_id}")
    async def agent_update_library_item(
        item_id: str,
        payload: LibraryItemUpdate,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        try:
            return await agent_growth_repository(context).update_library_item(
                _public_uuid(item_id, "书影音条目"),
                payload.model_dump(exclude_unset=True),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="书影音条目不存在") from exc

    @app.post("/api/agent/content", status_code=201)
    async def agent_save_content_item(
        payload: ContentItemCreate,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        values = payload.model_dump()
        for field in ("source_url", "media_url", "thumbnail_url"):
            values[field] = str(values[field]) if values[field] is not None else None
        return await agent_growth_repository(context).save_content_item(
            **values,
            source="hermes",
        )

    @app.get("/api/agent/projects")
    async def agent_list_projects(
        include_deleted: bool = Query(default=False),
        context: AgentRequestContext = Depends(agent_context),
    ) -> list[dict]:
        require_agent_scope(context, "workbench:read")
        return await CoreRepository(
            context.session,
            context.identity.workspace_id,
            "agent",
            context.identity.credential_public_id,
        ).list_projects(include_deleted=include_deleted)

    @app.post("/api/agent/projects", status_code=201)
    async def agent_create_project(
        payload: ProjectCreate,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        try:
            return await CoreRepository(
                context.session,
                context.identity.workspace_id,
                "agent",
                context.identity.credential_public_id,
            ).create_project(
                name=payload.name,
                description=payload.description,
                current_stage=payload.current_stage,
                progress_percent=payload.progress_percent,
                next_milestone=payload.next_milestone,
                start_date=payload.start_date,
                due_date=payload.due_date,
                source="hermes",
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/agent/projects/{project_id}/plan")
    async def agent_project_plan(
        project_id: str,
        include_deleted: bool = Query(default=False),
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:read")
        try:
            return await CoreRepository(
                context.session,
                context.identity.workspace_id,
                "agent",
                context.identity.credential_public_id,
            ).project_plan(_public_uuid(project_id, "项目"), include_deleted=include_deleted)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="项目不存在") from exc

    @app.patch("/api/agent/projects/{project_id}")
    async def agent_update_project(
        project_id: str,
        payload: ProjectUpdate,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        try:
            return await CoreRepository(
                context.session,
                context.identity.workspace_id,
                "agent",
                context.identity.credential_public_id,
            ).update_project(
                _public_uuid(project_id, "项目"),
                payload.model_dump(exclude_unset=True),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="项目不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/agent/projects/{project_id}")
    async def agent_delete_project(
        project_id: str,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        try:
            return await CoreRepository(
                context.session,
                context.identity.workspace_id,
                "agent",
                context.identity.credential_public_id,
            ).delete_project(_public_uuid(project_id, "项目"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="项目不存在") from exc

    @app.post("/api/agent/projects/{project_id}/restore")
    async def agent_restore_project(
        project_id: str,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        try:
            return await CoreRepository(
                context.session,
                context.identity.workspace_id,
                "agent",
                context.identity.credential_public_id,
            ).restore_project(_public_uuid(project_id, "项目"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="项目不存在") from exc

    @app.get("/api/agent/projects/{project_id}/phases")
    async def agent_list_project_phases(
        project_id: str,
        include_deleted: bool = Query(default=False),
        context: AgentRequestContext = Depends(agent_context),
    ) -> list[dict]:
        require_agent_scope(context, "workbench:read")
        try:
            return await CoreRepository(
                context.session,
                context.identity.workspace_id,
                "agent",
                context.identity.credential_public_id,
            ).list_phases(_public_uuid(project_id, "项目"), include_deleted=include_deleted)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="项目不存在") from exc

    @app.post("/api/agent/projects/{project_id}/phases", status_code=201)
    async def agent_create_project_phase(
        project_id: str,
        payload: ProjectPhaseCreate,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        try:
            return await CoreRepository(
                context.session,
                context.identity.workspace_id,
                "agent",
                context.identity.credential_public_id,
            ).create_phase(
                _public_uuid(project_id, "项目"),
                **payload.model_dump(),
                source="hermes",
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="项目不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/agent/project-phases/{phase_id}")
    async def agent_update_project_phase(
        phase_id: str,
        payload: ProjectPhaseUpdate,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        try:
            return await CoreRepository(
                context.session,
                context.identity.workspace_id,
                "agent",
                context.identity.credential_public_id,
            ).update_phase(_public_uuid(phase_id, "阶段"), payload.model_dump(exclude_unset=True))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="阶段不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/agent/project-phases/{phase_id}")
    async def agent_delete_project_phase(
        phase_id: str,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        try:
            return await CoreRepository(
                context.session,
                context.identity.workspace_id,
                "agent",
                context.identity.credential_public_id,
            ).delete_phase(_public_uuid(phase_id, "阶段"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="阶段不存在") from exc

    @app.post("/api/agent/project-phases/{phase_id}/restore")
    async def agent_restore_project_phase(
        phase_id: str,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        try:
            return await CoreRepository(
                context.session,
                context.identity.workspace_id,
                "agent",
                context.identity.credential_public_id,
            ).restore_phase(_public_uuid(phase_id, "阶段"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="阶段不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/agent/tasks", status_code=201)
    async def agent_create_task(
        payload: TaskCreate,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        try:
            return await CoreRepository(
                context.session,
                context.identity.workspace_id,
                "agent",
                context.identity.credential_public_id,
            ).create_task(
                title=payload.title,
                quadrant=payload.quadrant,
                due_at=payload.due_at,
                note=payload.note,
                recurrence=payload.recurrence,
                project_public_id=payload.project_id,
                phase_public_id=payload.phase_id,
                start_date=payload.start_date,
                end_date=payload.end_date,
                status=payload.status,
                progress_percent=payload.progress_percent,
                is_milestone=payload.is_milestone,
                order_index=payload.order_index,
                predecessor_public_ids=payload.predecessor_ids,
                source="hermes",
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/agent/tasks/{task_id}")
    async def agent_delete_task(
        task_id: str,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        try:
            return await CoreRepository(
                context.session,
                context.identity.workspace_id,
                "agent",
                context.identity.credential_public_id,
            ).delete_task(_public_uuid(task_id, "任务"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="任务不存在") from exc

    @app.post("/api/agent/tasks/{task_id}/restore")
    async def agent_restore_task(
        task_id: str,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        try:
            return await CoreRepository(
                context.session,
                context.identity.workspace_id,
                "agent",
                context.identity.credential_public_id,
            ).restore_task(_public_uuid(task_id, "任务"))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="任务不存在") from exc

    @app.patch("/api/agent/tasks/{task_id}")
    async def agent_update_task(
        task_id: str,
        payload: TaskUpdate,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        try:
            return await CoreRepository(
                context.session,
                context.identity.workspace_id,
                "agent",
                context.identity.credential_public_id,
            ).update_task(
                _public_uuid(task_id, "任务"),
                payload.model_dump(exclude_unset=True),
                source="agent",
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="任务不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/agent/greeting", status_code=201)
    async def agent_save_daily_message(
        payload: DailyMessageCreate,
        context: AgentRequestContext = Depends(agent_context),
    ) -> dict:
        require_agent_scope(context, "workbench:write")
        return await CoreRepository(
            context.session,
            context.identity.workspace_id,
            "agent",
            context.identity.credential_public_id,
        ).save_daily_message(payload.message, payload.tone, source="hermes")

    @app.get("/api/events")
    async def list_events(
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=200),
        context: RequestContext = Depends(current_context),
    ) -> dict:
        events = list(
            (
                await context.session.scalars(
                    select(WorkspaceEvent)
                    .where(
                        WorkspaceEvent.workspace_id == context.identity.workspace_id,
                        WorkspaceEvent.id > after,
                    )
                    .order_by(WorkspaceEvent.id)
                    .limit(limit)
                )
            ).all()
        )
        return {
            "items": [
                {
                    "cursor": item.id,
                    "type": item.event_type,
                    "entity_type": item.entity_type,
                    "entity_key": item.entity_key,
                    "payload": item.payload,
                    "created_at": item.created_at.isoformat(),
                }
                for item in events
            ],
            "next_cursor": events[-1].id if events else after,
        }

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        token = websocket.cookies.get(resolved_settings.session_cookie_name)
        if not token:
            await websocket.close(code=4401)
            return
        async with resolved_database.session_factory() as session:
            async with session.begin():
                try:
                    identity = await auth.authenticate_session(session, token)
                except AuthenticationError:
                    await websocket.close(code=4401)
                    return
        await websocket.accept()
        requested_cursor = websocket.query_params.get("after")
        if requested_cursor and requested_cursor.isdigit():
            last_cursor = int(requested_cursor)
        else:
            async with resolved_database.session_factory() as session:
                async with session.begin():
                    await set_tenant_context(session, identity.workspace_id)
                    last_cursor = await session.scalar(
                        select(WorkspaceEvent.id)
                        .where(WorkspaceEvent.workspace_id == identity.workspace_id)
                        .order_by(WorkspaceEvent.id.desc())
                        .limit(1)
                    ) or 0
        await websocket.send_json({
            "type": "connected",
            "workspace_id": str(identity.workspace_public_id),
            "cursor": last_cursor,
        })
        try:
            while True:
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=2)
                except TimeoutError:
                    pass
                async with resolved_database.session_factory() as session:
                    async with session.begin():
                        await set_tenant_context(session, identity.workspace_id)
                        events = list(
                            (
                                await session.scalars(
                                    select(WorkspaceEvent)
                                    .where(
                                        WorkspaceEvent.workspace_id == identity.workspace_id,
                                        WorkspaceEvent.id > last_cursor,
                                    )
                                    .order_by(WorkspaceEvent.id)
                                    .limit(100)
                                )
                            ).all()
                        )
                for event in events:
                    last_cursor = event.id
                    await websocket.send_json(
                        {
                            "type": "workspace.event",
                            "cursor": event.id,
                            "event": event.event_type,
                            "entity_type": event.entity_type,
                            "entity_key": event.entity_key,
                            "payload": event.payload,
                            "created_at": event.created_at.isoformat(),
                        }
                    )
        except WebSocketDisconnect:
            return

    @app.websocket("/ws/agent")
    async def agent_websocket_endpoint(websocket: WebSocket) -> None:
        authorization = websocket.headers.get("authorization", "")
        token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        if not token:
            await websocket.close(code=4401)
            return
        async with resolved_database.session_factory() as session:
            async with session.begin():
                try:
                    identity = await auth.authenticate_agent(session, token)
                except AuthenticationError:
                    await websocket.close(code=4401)
                    return
        if "jobs:claim" not in identity.scopes:
            await websocket.close(code=4403)
            return
        await websocket.accept()
        await websocket.send_json(
            {"type": "connected", "workspace_id": str(identity.workspace_public_id)}
        )
        last_job_id = 0
        try:
            while True:
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=2)
                except TimeoutError:
                    pass
                async with resolved_database.session_factory() as session:
                    async with session.begin():
                        await set_tenant_context(session, identity.workspace_id)
                        jobs = list(
                            (
                                await session.scalars(
                                    select(AgentJob)
                                    .where(
                                        AgentJob.workspace_id == identity.workspace_id,
                                        AgentJob.status == "pending",
                                        AgentJob.id > last_job_id,
                                    )
                                    .order_by(AgentJob.id)
                                    .limit(20)
                                )
                            ).all()
                        )
                for job in jobs:
                    last_job_id = job.id
                    await websocket.send_json(
                        {"type": "job.available", "job": _agent_job_payload(job)}
                    )
        except WebSocketDisconnect:
            return

    static_directory = Path(__file__).resolve().parents[3] / "static"
    if static_directory.is_dir():
        app.mount("/", StaticFiles(directory=static_directory, html=True), name="cloud-frontend")

    return app
