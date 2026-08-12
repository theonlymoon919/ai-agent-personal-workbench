import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import AsyncIterator, Literal

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP, Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    DailyHealthAdviceCreate,
    HealthAnalysisCreate,
    HealthRecordUpdate,
    LibraryItemCreate,
    LibraryItemUpdate,
    ProjectCreate,
    ProjectPhaseCreate,
    ProjectPhaseUpdate,
    ProjectUpdate,
    TaskCreate,
    TaskUpdate,
)
from .auth import AgentIdentity, AuthService, AuthenticationError
from .config import CloudSettings
from .core_repository import CoreRepository
from .database import CloudDatabase
from .finance_repository import FinanceRepository, yuan_to_minor
from .finance_schemas import FinanceInsightCreate, FinanceTransactionCreate
from .growth_repository import GrowthRepository
from .growth_schemas import ContentItemCreate, LearningPlanGeneratedUpdate
from .health_repository import HealthRepository
from .jobs import claim_next_job, complete_job
from .models import AgentJob, StoredObject, WorkspaceSettings
from .storage import LocalPrivateObjectStore


MCP_SCOPES = ["workbench:read"]


def _uuid(value: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} ID 格式不正确") from exc


def _date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须使用 YYYY-MM-DD 格式") from exc


def _datetime(value: str | None, label: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须使用 ISO 8601 时间格式") from exc


def _job_payload(job: AgentJob | None) -> dict | None:
    if job is None:
        return None
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


class AgentTokenVerifier(TokenVerifier):
    """Validate the same revocable, workspace-bound token used by the Agent API."""

    def __init__(self, database: CloudDatabase, auth: AuthService) -> None:
        self.database = database
        self.auth = auth

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            async with self.database.session_factory() as session:
                async with session.begin():
                    identity = await self.auth.authenticate_agent(session, token)
        except AuthenticationError:
            return None
        return AccessToken(
            token=token,
            client_id=str(identity.credential_public_id),
            scopes=list(identity.scopes),
            expires_at=None,
        )


@dataclass(slots=True)
class AgentToolContext:
    session: AsyncSession
    identity: AgentIdentity

    @property
    def core(self) -> CoreRepository:
        return CoreRepository(
            self.session,
            self.identity.workspace_id,
            "agent",
            self.identity.credential_public_id,
        )

    @property
    def health(self) -> HealthRepository:
        return HealthRepository(
            self.session,
            self.identity.workspace_id,
            self.identity.workspace_public_id,
            "agent",
            self.identity.credential_public_id,
        )

    @property
    def finance(self) -> FinanceRepository:
        return FinanceRepository(
            self.session,
            self.identity.workspace_id,
            "agent",
            self.identity.credential_public_id,
        )

    @property
    def growth(self) -> GrowthRepository:
        return GrowthRepository(
            self.session,
            self.identity.workspace_id,
            "agent",
            self.identity.credential_public_id,
        )


class AgentToolTransactions:
    def __init__(self, database: CloudDatabase, auth: AuthService) -> None:
        self.database = database
        self.auth = auth

    @asynccontextmanager
    async def open(self, required_scope: str) -> AsyncIterator[AgentToolContext]:
        access_token = get_access_token()
        if access_token is None:
            raise PermissionError("AI Agent 尚未通过身份验证")
        async with self.database.session_factory() as session:
            async with session.begin():
                try:
                    identity = await self.auth.authenticate_agent(session, access_token.token)
                except AuthenticationError as exc:
                    raise PermissionError("AI Agent 凭证已失效，请重新连接") from exc
                if required_scope not in identity.scopes:
                    raise PermissionError(f"AI Agent 缺少权限：{required_scope}")
                yield AgentToolContext(session=session, identity=identity)


def create_cloud_mcp(
    settings: CloudSettings,
    database: CloudDatabase,
    auth: AuthService,
    object_store: LocalPrivateObjectStore,
) -> FastMCP:
    public_origin = settings.public_origin.rstrip("/")
    transactions = AgentToolTransactions(database, auth)
    mcp = FastMCP(
        name="AI Agent 个人工作台接口",
        instructions=(
            "这是用户唯一的私人工作台；只能使用当前令牌对应的工作空间，禁止连接已退役的本地旧工作台。"
            "每次先调用 get_workspace_overview；收到任务时领取最早待办，读取关联记录或图片，保存结构化结果，再完成任务。"
            "长期工作使用项目、阶段、任务三级结构；用户明确要求记录时写入，仅由谈话推测的排期先征求确认，不编造日期。"
            "不得猜测图片内容、热量、金额或来源；不确定时明确标记估算。"
            "内容刷新应按用户关注方向分别写入 6 至 10 条高相关去重结果；每条保留可验证来源。"
            "抖音优先保存含数字作品 ID 的规范 source_url；media_url 只能是真实可直接播放的媒体地址，不能重复填写作品网页。"
            "财务写入前读取有效账户和分类，每笔交易关联实际账户。所有建议应简短、分段、可执行。"
        ),
        token_verifier=AgentTokenVerifier(database, auth),
        auth=AuthSettings(
            issuer_url=public_origin,
            resource_server_url=f"{public_origin}/mcp",
            required_scopes=MCP_SCOPES,
        ),
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
    )

    @mcp.tool(description="读取工作台概况、个人偏好、项目、任务、今日健康和待处理任务。每次开始工作时先调用。")
    async def get_workspace_overview() -> dict:
        async with transactions.open("workbench:read") as context:
            settings_record = await context.session.scalar(
                select(WorkspaceSettings).where(
                    WorkspaceSettings.workspace_id == context.identity.workspace_id
                )
            )
            if settings_record is None:
                raise KeyError("工作空间设置不存在")
            pending_jobs = list(
                (
                    await context.session.scalars(
                        select(AgentJob)
                        .where(
                            AgentJob.workspace_id == context.identity.workspace_id,
                            AgentJob.status.in_(("pending", "in_progress")),
                        )
                        .order_by(AgentJob.available_at, AgentJob.id)
                        .limit(20)
                    )
                ).all()
            )
            return {
                "workspace_id": str(context.identity.workspace_public_id),
                "profile": dict(settings_record.profile),
                "health_preferences": dict(settings_record.health),
                "ip_preferences": dict(settings_record.ip_preferences),
                "projects": await context.core.list_projects(),
                "tasks": await context.core.list_tasks(),
                "today_health": await context.health.today_overview(),
                "learning_plans": await context.growth.list_plans(),
                "library": await context.growth.list_library(),
                "jobs": [_job_payload(item) for item in pending_jobs],
            }

    @mcp.tool(description="列出项目；include_deleted=true 时也返回回收站项目。需要安排长期工作时先调用。")
    async def list_projects(include_deleted: bool = False) -> list[dict]:
        async with transactions.open("workbench:read") as context:
            return await context.core.list_projects(include_deleted=include_deleted)

    @mcp.tool(description="读取一个项目的阶段、任务、排期、前置关系和未排期事项。")
    async def get_project_plan(project_id: str, include_deleted: bool = False) -> dict:
        async with transactions.open("workbench:read") as context:
            return await context.core.project_plan(
                _uuid(project_id, "项目"),
                include_deleted=include_deleted,
            )

    @mcp.tool(description="新建项目。用户明确要求记录或安排时可直接创建；仅推测出的计划应先征求确认。")
    async def create_project(
        name: str,
        description: str = "",
        current_stage: str = "准备中",
        next_milestone: str = "",
        start_date: str | None = None,
        due_date: str | None = None,
    ) -> dict:
        payload = ProjectCreate(
            name=name,
            description=description,
            current_stage=current_stage,
            next_milestone=next_milestone,
            start_date=_date(start_date, "开始日期") if start_date else None,
            due_date=_date(due_date, "目标日期") if due_date else None,
        )
        async with transactions.open("workbench:write") as context:
            return await context.core.create_project(
                name=payload.name,
                description=payload.description,
                current_stage=payload.current_stage,
                progress_percent=payload.progress_percent,
                next_milestone=payload.next_milestone,
                start_date=payload.start_date,
                due_date=payload.due_date,
                source="hermes",
            )

    @mcp.tool(description="修改项目名称、说明、阶段、里程碑、起止日期或状态。只传需要修改的字段；空日期表示清除。")
    async def update_project(
        project_id: str,
        name: str | None = None,
        description: str | None = None,
        current_stage: str | None = None,
        next_milestone: str | None = None,
        start_date: str | None = None,
        due_date: str | None = None,
        status: Literal["active", "paused", "completed"] | None = None,
    ) -> dict:
        raw = {
            "name": name,
            "description": description,
            "current_stage": current_stage,
            "next_milestone": next_milestone,
            "status": status,
        }
        values = {key: value for key, value in raw.items() if value is not None}
        if start_date is not None:
            values["start_date"] = _date(start_date, "开始日期") if start_date else None
        if due_date is not None:
            values["due_date"] = _date(due_date, "目标日期") if due_date else None
        payload = ProjectUpdate.model_validate(values)
        async with transactions.open("workbench:write") as context:
            return await context.core.update_project(
                _uuid(project_id, "项目"),
                payload.model_dump(exclude_unset=True),
            )

    @mcp.tool(description="把项目移入回收站；项目下的阶段和任务会暂时隐藏，恢复项目后重新出现。")
    async def delete_project(project_id: str) -> dict:
        async with transactions.open("workbench:write") as context:
            return await context.core.delete_project(_uuid(project_id, "项目"))

    @mcp.tool(description="从回收站恢复项目及其仍保留的阶段和任务。")
    async def restore_project(project_id: str) -> dict:
        async with transactions.open("workbench:write") as context:
            return await context.core.restore_project(_uuid(project_id, "项目"))

    @mcp.tool(description="列出项目阶段；include_deleted=true 时包含已删除阶段。")
    async def list_project_phases(project_id: str, include_deleted: bool = False) -> list[dict]:
        async with transactions.open("workbench:read") as context:
            return await context.core.list_phases(
                _uuid(project_id, "项目"),
                include_deleted=include_deleted,
            )

    @mcp.tool(description="在项目中新增阶段，日期使用 YYYY-MM-DD；order_index 越小越靠前。")
    async def create_project_phase(
        project_id: str,
        name: str,
        description: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
        status: Literal["active", "paused", "completed"] = "active",
        order_index: int = 0,
    ) -> dict:
        payload = ProjectPhaseCreate(
            name=name,
            description=description,
            start_date=_date(start_date, "开始日期") if start_date else None,
            end_date=_date(end_date, "结束日期") if end_date else None,
            status=status,
            order_index=order_index,
        )
        async with transactions.open("workbench:write") as context:
            return await context.core.create_phase(
                _uuid(project_id, "项目"),
                **payload.model_dump(),
                source="hermes",
            )

    @mcp.tool(description="修改阶段名称、说明、日期、顺序或状态；空日期表示清除。")
    async def update_project_phase(
        phase_id: str,
        name: str | None = None,
        description: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        status: Literal["active", "paused", "completed"] | None = None,
        order_index: int | None = None,
    ) -> dict:
        values = {
            key: value for key, value in {
                "name": name,
                "description": description,
                "status": status,
                "order_index": order_index,
            }.items() if value is not None
        }
        if start_date is not None:
            values["start_date"] = _date(start_date, "开始日期") if start_date else None
        if end_date is not None:
            values["end_date"] = _date(end_date, "结束日期") if end_date else None
        payload = ProjectPhaseUpdate.model_validate(values)
        async with transactions.open("workbench:write") as context:
            return await context.core.update_phase(
                _uuid(phase_id, "阶段"),
                payload.model_dump(exclude_unset=True),
            )

    @mcp.tool(description="把阶段移入回收站；阶段任务会暂时隐藏，恢复阶段后重新出现。")
    async def delete_project_phase(phase_id: str) -> dict:
        async with transactions.open("workbench:write") as context:
            return await context.core.delete_phase(_uuid(phase_id, "阶段"))

    @mcp.tool(description="恢复已删除阶段；若所属项目已删除，需要先恢复项目。")
    async def restore_project_phase(phase_id: str) -> dict:
        async with transactions.open("workbench:write") as context:
            return await context.core.restore_phase(_uuid(phase_id, "阶段"))

    @mcp.tool(description="领取当前用户最早的一项待处理任务。没有任务时返回 job=null。")
    async def claim_next_agent_job() -> dict:
        async with transactions.open("jobs:claim") as context:
            job = await claim_next_job(
                context.session,
                context.identity.workspace_id,
                context.identity.credential_id,
            )
            return {"job": _job_payload(job)}

    @mcp.tool(description="完成已领取的任务。保存分析或内容后再调用；失败时填写 error_code。")
    async def complete_agent_job(
        job_id: str,
        result_summary: str,
        succeeded: bool = True,
        error_code: str | None = None,
    ) -> dict:
        async with transactions.open("jobs:claim") as context:
            job = await complete_job(
                context.session,
                context.identity.workspace_id,
                context.identity.credential_id,
                _uuid(job_id, "任务"),
                result_summary,
                succeeded,
                error_code,
            )
            return _job_payload(job) or {}

    @mcp.tool(description="列出任务；可包含已删除任务，供 AI Agent 安排当日工作和查找既有事项。")
    async def list_tasks(include_deleted: bool = False) -> list[dict]:
        async with transactions.open("workbench:read") as context:
            return await context.core.list_tasks(include_deleted=include_deleted)

    @mcp.tool(description="新增任务。可关联项目和阶段、设置日期范围、进度、里程碑及前置任务；due_at 使用 ISO 8601。")
    async def create_task(
        title: str,
        quadrant: Literal[
            "important_urgent",
            "important_not_urgent",
            "not_important_urgent",
            "not_important_not_urgent",
        ] = "important_not_urgent",
        due_at: str | None = None,
        note: str = "",
        recurrence: Literal["none", "yearly"] = "none",
        project_id: str | None = None,
        phase_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        status: Literal["planned", "in_progress", "blocked", "completed", "cancelled"] = "planned",
        progress_percent: int = 0,
        is_milestone: bool = False,
        order_index: int = 0,
        predecessor_ids: list[str] | None = None,
    ) -> dict:
        payload = TaskCreate(
            title=title,
            quadrant=quadrant,
            due_at=_datetime(due_at, "到期时间"),
            note=note,
            recurrence=recurrence,
            project_id=_uuid(project_id, "项目") if project_id else None,
            phase_id=_uuid(phase_id, "阶段") if phase_id else None,
            start_date=_date(start_date, "开始日期") if start_date else None,
            end_date=_date(end_date, "结束日期") if end_date else None,
            status=status,
            progress_percent=progress_percent,
            is_milestone=is_milestone,
            order_index=order_index,
            predecessor_ids=[_uuid(item, "前置任务") for item in predecessor_ids or []],
        )
        async with transactions.open("workbench:write") as context:
            return await context.core.create_task(
                payload.title,
                payload.quadrant,
                payload.due_at,
                payload.note,
                payload.recurrence,
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

    @mcp.tool(description="修改任务内容、归属、排期、进度、状态或前置关系。空字符串可清除归属或日期。")
    async def update_task(
        task_id: str,
        done: bool | None = None,
        title: str | None = None,
        quadrant: str | None = None,
        due_at: str | None = None,
        note: str | None = None,
        recurrence: str | None = None,
        occurrence_date: str | None = None,
        project_id: str | None = None,
        phase_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        status: Literal["planned", "in_progress", "blocked", "completed", "cancelled"] | None = None,
        progress_percent: int | None = None,
        is_milestone: bool | None = None,
        order_index: int | None = None,
        predecessor_ids: list[str] | None = None,
    ) -> dict:
        raw: dict = {
            "done": done,
            "title": title,
            "quadrant": quadrant,
            "note": note,
            "recurrence": recurrence,
            "occurrence_date": _date(occurrence_date, "发生日期") if occurrence_date else None,
            "status": status,
            "progress_percent": progress_percent,
            "is_milestone": is_milestone,
            "order_index": order_index,
        }
        values = {key: value for key, value in raw.items() if value is not None}
        if due_at is not None:
            values["due_at"] = _datetime(due_at, "到期时间") if due_at else None
        if project_id is not None:
            values["project_id"] = _uuid(project_id, "项目") if project_id else None
        if phase_id is not None:
            values["phase_id"] = _uuid(phase_id, "阶段") if phase_id else None
        if start_date is not None:
            values["start_date"] = _date(start_date, "开始日期") if start_date else None
        if end_date is not None:
            values["end_date"] = _date(end_date, "结束日期") if end_date else None
        if predecessor_ids is not None:
            values["predecessor_ids"] = [_uuid(item, "前置任务") for item in predecessor_ids]
        payload = TaskUpdate.model_validate(values)
        async with transactions.open("workbench:write") as context:
            return await context.core.update_task(
                _uuid(task_id, "任务"),
                payload.model_dump(exclude_unset=True),
                source="agent",
            )

    @mcp.tool(description="把任务移入回收站。")
    async def delete_task(task_id: str) -> dict:
        async with transactions.open("workbench:write") as context:
            return await context.core.delete_task(_uuid(task_id, "任务"))

    @mcp.tool(description="从回收站恢复任务。")
    async def restore_task(task_id: str) -> dict:
        async with transactions.open("workbench:write") as context:
            return await context.core.restore_task(_uuid(task_id, "任务"))

    @mcp.tool(description="读取指定日期范围的健康记录和日卡片。范围最多 366 天。")
    async def get_health_history(start_date: str, end_date: str) -> dict:
        async with transactions.open("workbench:read") as context:
            return await context.health.history(
                _date(start_date, "开始日期"),
                _date(end_date, "结束日期"),
            )

    @mcp.tool(description="读取单条饮食、运动或体重图片记录及当前分析状态。")
    async def get_health_record(record_id: str) -> dict:
        async with transactions.open("workbench:read") as context:
            return await context.health.get_record(_uuid(record_id, "健康记录"))

    @mcp.tool(description="修改健康图片记录的日期或餐次。")
    async def update_health_record(
        record_id: str,
        record_date: str | None = None,
        meal_slot: Literal["breakfast", "lunch", "afternoon_tea", "dinner", "snack", "late_night"] | None = None,
    ) -> dict:
        payload = HealthRecordUpdate(
            record_date=_date(record_date, "记录日期") if record_date else None,
            meal_slot=meal_slot,
        )
        async with transactions.open("workbench:write") as context:
            return await context.health.update_record(
                _uuid(record_id, "健康记录"),
                payload.record_date,
                payload.meal_slot,
            )

    @mcp.tool(description="把错误的健康图片记录移入回收站。")
    async def delete_health_record(record_id: str) -> dict:
        async with transactions.open("workbench:write") as context:
            return await context.health.set_deleted(_uuid(record_id, "健康记录"), True)

    @mcp.tool(description="从回收站恢复健康图片记录。")
    async def restore_health_record(record_id: str) -> dict:
        async with transactions.open("workbench:write") as context:
            return await context.health.set_deleted(_uuid(record_id, "健康记录"), False)

    @mcp.tool(description="加载健康记录的原始图片，用于视觉识别。必须基于实际图片给出分析。")
    async def load_health_image(record_id: str) -> Image:
        async with transactions.open("workbench:read") as context:
            record = await context.health.get_record(_uuid(record_id, "健康记录"))
            object_id = _uuid(record["asset"].split("/")[-1], "附件")
            stored = await context.session.scalar(
                select(StoredObject).where(
                    StoredObject.workspace_id == context.identity.workspace_id,
                    StoredObject.public_id == object_id,
                    StoredObject.status == "ready",
                    StoredObject.deleted_at.is_(None),
                )
            )
            if stored is None:
                raise KeyError("图片附件不存在")
            return Image(path=object_store.path_for_read(stored.object_key))

    @mcp.tool(description="保存对单张饮食、运动或体重图片的分析。热量无法可靠判断时可留空，并在文字中说明估算。")
    async def save_health_record_analysis(
        record_id: str,
        summary: str,
        advice: str = "",
        calories_kcal: int | None = None,
        exercise_kcal: int | None = None,
        weight_kg: float | None = None,
    ) -> dict:
        payload = HealthAnalysisCreate(
            summary=summary,
            advice=advice,
            calories_kcal=calories_kcal,
            exercise_kcal=exercise_kcal,
            weight_kg=weight_kg,
        )
        async with transactions.open("workbench:write") as context:
            return await context.health.analyze_record(
                _uuid(record_id, "健康记录"),
                payload.summary,
                payload.advice,
                payload.calories_kcal,
                payload.exercise_kcal,
                payload.weight_kg,
                model_name="hermes",
            )

    @mcp.tool(description="保存某一天分段式健康总结，分别填写饮食、饮水、运动和总体建议。")
    async def save_daily_health_advice(
        target_date: str,
        status: Literal["on_track", "attention", "celebrate", "neutral"],
        overall_summary: str,
        diet_summary: str = "",
        hydration_summary: str = "",
        exercise_summary: str = "",
    ) -> dict:
        payload = DailyHealthAdviceCreate(
            status=status,
            overall_summary=overall_summary,
            diet_summary=diet_summary,
            hydration_summary=hydration_summary,
            exercise_summary=exercise_summary,
        )
        async with transactions.open("workbench:write") as context:
            return await context.health.save_daily_advice(
                _date(target_date, "总结日期"),
                payload.status,
                payload.overall_summary,
                payload.diet_summary,
                payload.hydration_summary,
                payload.exercise_summary,
                generated_by="hermes",
            )

    @mcp.tool(description="记录用户告诉 AI Agent 的饮水量，单位毫升。")
    async def record_water(amount_ml: int) -> dict:
        async with transactions.open("workbench:write") as context:
            return await context.health.record_water(amount_ml, source="hermes")

    @mcp.tool(description="记录用户告诉 AI Agent 的体重，单位千克。")
    async def record_weight(weight_kg: float) -> dict:
        async with transactions.open("workbench:write") as context:
            return await context.health.record_weight(weight_kg, source="hermes")

    @mcp.tool(description="列出财务分类和账户；记账前先读取有效 ID。")
    async def get_finance_reference_data() -> dict:
        async with transactions.open("workbench:read") as context:
            await context.finance.ensure_defaults()
            return {
                "categories": await context.finance.list_categories(),
                "accounts": await context.finance.list_accounts(),
                "savings_goals": await context.finance.list_goals(),
            }

    @mcp.tool(description="记录收入、支出、转账或退款。金额单位为人民币元；相同事实请复用 idempotency_key 防止重复记账。")
    async def create_finance_transaction(
        transaction_type: Literal["income", "expense", "transfer", "refund"],
        amount_yuan: str,
        category_id: str | None = None,
        account_id: str | None = None,
        to_account_id: str | None = None,
        refund_of_id: str | None = None,
        occurred_at: str | None = None,
        local_date: str | None = None,
        merchant: str = "",
        purpose: str = "",
        note: str = "",
        tags: list[str] | None = None,
        is_fixed: bool = False,
        is_necessary: bool = False,
        idempotency_key: str | None = None,
    ) -> dict:
        payload = FinanceTransactionCreate(
            transaction_type=transaction_type,
            amount_yuan=Decimal(amount_yuan),
            category_id=_uuid(category_id, "分类") if category_id else None,
            account_id=_uuid(account_id, "账户") if account_id else None,
            to_account_id=_uuid(to_account_id, "转入账户") if to_account_id else None,
            refund_of_id=_uuid(refund_of_id, "原交易") if refund_of_id else None,
            occurred_at=_datetime(occurred_at, "发生时间"),
            local_date=_date(local_date, "记账日期") if local_date else None,
            merchant=merchant,
            purpose=purpose,
            note=note,
            tags=tags or [],
            is_fixed=is_fixed,
            is_necessary=is_necessary,
        )
        async with transactions.open("workbench:write") as context:
            return await context.finance.create_transaction(
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
                idempotency_key=(idempotency_key or f"hermes-mcp:{uuid.uuid4()}")[:160],
                source="hermes",
            )

    @mcp.tool(description="读取指定日期范围的收支、分类占比、预算和储蓄率汇总。")
    async def get_finance_summary(start_date: str, end_date: str) -> dict:
        async with transactions.open("workbench:read") as context:
            return await context.finance.summary(
                _date(start_date, "开始日期"),
                _date(end_date, "结束日期"),
            )

    @mcp.tool(description="保存有证据的分段式财务建议。不要把理财书观点表述为保证收益或专业投资意见。")
    async def save_finance_insight(
        period_start: str,
        period_end: str,
        finding: str,
        evidence: str,
        action: str,
        risk: str = "",
        next_goal: str = "",
    ) -> dict:
        payload = FinanceInsightCreate(
            period_start=_date(period_start, "开始日期"),
            period_end=_date(period_end, "结束日期"),
            finding=finding,
            evidence=evidence,
            risk=risk,
            action=action,
            next_goal=next_goal,
        )
        async with transactions.open("workbench:write") as context:
            return await context.finance.save_insight(**payload.model_dump(), source="hermes")

    @mcp.tool(description="读取学习计划、书单、影单和纪录片列表。")
    async def get_growth_overview() -> dict:
        async with transactions.open("workbench:read") as context:
            return {
                "learning_plans": await context.growth.list_plans(),
                "library": await context.growth.list_library(),
            }

    @mcp.tool(description="为既有学习项目保存分阶段学习路径和经过相关性、发布时间、可访问性验证的学习资源。B 站资源必须使用具体 BV 地址，并填写 published_at、verified_at、search_keywords、relevance_reason；不合格资源不要写入。")
    async def save_generated_learning_plan(
        plan_id: str,
        roadmap_markdown: str,
        total_lessons: int,
        resources: list[dict] | None = None,
        status: Literal["waiting_for_hermes", "active", "paused", "completed"] = "active",
        completed_lessons: int = 0,
    ) -> dict:
        payload = LearningPlanGeneratedUpdate(
            roadmap_markdown=roadmap_markdown,
            status=status,
            total_lessons=total_lessons,
            completed_lessons=completed_lessons,
            resources=resources or [],
        )
        async with transactions.open("workbench:write") as context:
            return await context.growth.update_generated_plan(
                _uuid(plan_id, "学习计划"),
                payload.roadmap_markdown,
                payload.status,
                payload.total_lessons,
                payload.completed_lessons,
                [item.model_dump(mode="json") for item in payload.resources],
            )

    @mcp.tool(description="添加 AI Agent 推荐的书、电影或纪录片。")
    async def add_library_recommendation(
        title: str,
        kind: Literal["book", "movie", "documentary"],
        reason: str = "",
    ) -> dict:
        payload = LibraryItemCreate(title=title, kind=kind, reason=reason)
        async with transactions.open("workbench:write") as context:
            return await context.growth.create_library_item(
                payload.title,
                payload.kind,
                payload.reason,
                source="hermes",
            )

    @mcp.tool(description="回应用户读书或观影心得，并保存整理后的笔记、意见和进度。")
    async def update_library_discussion(
        item_id: str,
        agent_comment: str,
        organized_notes: str = "",
        progress_percent: int | None = None,
        current_position: str | None = None,
        status: Literal["want", "in_progress", "done"] | None = None,
    ) -> dict:
        raw = {
            "agent_comment": agent_comment,
            "organized_notes": organized_notes,
            "progress_percent": progress_percent,
            "current_position": current_position,
            "status": status,
        }
        payload = LibraryItemUpdate.model_validate({key: value for key, value in raw.items() if value is not None})
        async with transactions.open("workbench:write") as context:
            return await context.growth.update_library_item(
                _uuid(item_id, "书影音条目"),
                payload.model_dump(exclude_unset=True),
            )

    @mcp.tool(description="保存短视频热点、今日资讯或选题灵感。资讯主题由用户的关注方向决定。必须附可验证 source_url；抖音使用含作品数字 ID 的规范地址。media_url 仅填写可直接播放的真实媒体文件/流，不能填写作品网页。")
    async def save_content_item(
        title: str,
        category: Literal["video_trend", "ai_news", "topic_idea"],
        source_url: str | None = None,
        summary: str = "",
        details_markdown: str = "",
        media_url: str | None = None,
        thumbnail_url: str | None = None,
        platform: str = "",
        published_at: str | None = None,
    ) -> dict:
        payload = ContentItemCreate(
            title=title,
            category=category,
            source_url=source_url,
            summary=summary,
            details_markdown=details_markdown,
            media_url=media_url,
            thumbnail_url=thumbnail_url,
            platform=platform,
            published_at=_datetime(published_at, "发布时间"),
        )
        values = payload.model_dump()
        for field in ("source_url", "media_url", "thumbnail_url"):
            values[field] = str(values[field]) if values[field] is not None else None
        async with transactions.open("workbench:write") as context:
            return await context.growth.save_content_item(**values, source="hermes")

    @mcp.tool(description="在工作台首页保存一条简短、具体、可执行的 AI Agent 建议。")
    async def save_suggestion(
        title: str,
        content: str,
        action_label: str = "",
    ) -> dict:
        async with transactions.open("workbench:write") as context:
            return await context.core.save_suggestion(
                title=title,
                content=content,
                action_label=action_label,
                source="hermes",
            )

    @mcp.tool(description="保存当天一句简短寄语；工作台只显示一句话。")
    async def save_daily_message(
        message: str,
        tone: Literal["encouraging", "comforting", "mixed"] = "mixed",
        target_date: str | None = None,
    ) -> dict:
        async with transactions.open("workbench:write") as context:
            return await context.core.save_daily_message(
                message,
                tone,
                _date(target_date, "寄语日期") if target_date else None,
                source="hermes",
            )

    return mcp
