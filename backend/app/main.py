from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager, suppress
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .backup import BackupManager
from .mcp_server import create_mcp_server
from .models import (
    AgentSuggestionCreate,
    BackupCreate,
    DailyHealthAdviceCreate,
    DailyMessageCreate,
    HealthAnalysisCreate,
    HealthRecordUpdate,
    HealthGoalsUpdate,
    IPPreferencesUpdate,
    LearningPlanCreate,
    LearningPlanProgressUpdate,
    LibraryItemCreate,
    LibraryItemUpdate,
    ProfileSettingsUpdate,
    ProjectCreate,
    ProjectUpdate,
    StartupUpdate,
    TaskCreate,
    TaskUpdate,
    WaterRecord,
    WeightRecord,
)
from .store import MarkdownStore
from .system_service import enable_remote_access, remote_access_status, startup_status, update_startup
from .version import APP_VERSION


PROJECT_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
WORKBENCH_PATH = Path(os.getenv("WORKBENCH_PATH", PROJECT_ROOT / "data"))
CACHE_PATH = Path(os.getenv("CACHE_PATH", PROJECT_ROOT / "cache"))
BACKUP_PATH = Path(os.getenv("BACKUP_PATH", Path.home() / "Documents" / "个人工作台备份"))
STATIC_DIR = Path(os.getenv("STATIC_DIR", PROJECT_ROOT / "frontend" / "dist"))
DEFAULT_WATER_TARGET_ML = int(os.getenv("DEFAULT_WATER_TARGET_ML", "2000"))
MAX_UPLOAD_BYTES = 15 * 1024 * 1024

store = MarkdownStore(WORKBENCH_PATH, CACHE_PATH, DEFAULT_WATER_TARGET_ML)
backups = BackupManager(WORKBENCH_PATH, BACKUP_PATH)
store.rebuild_index()
if os.getenv("WORKBENCH_SEED_DEMO", "false").lower() == "true":
    store.seed_demo()

mcp = create_mcp_server(store)
mcp_app = mcp.streamable_http_app()


class ConnectionHub:
    def __init__(self) -> None:
        self.connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.connections.discard(websocket)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for websocket in list(self.connections):
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(websocket)


hub = ConnectionHub()


async def watch_markdown() -> None:
    previous = store.fingerprint()
    while True:
        await asyncio.sleep(1.5)
        current = store.fingerprint()
        if current != previous:
            previous = current
            await hub.broadcast({"type": "refresh", "reason": "markdown_changed"})


@asynccontextmanager
async def lifespan(_: FastAPI):
    watcher = asyncio.create_task(watch_markdown())
    async with mcp.session_manager.run():
        yield
    watcher.cancel()
    with suppress(asyncio.CancelledError):
        await watcher


api = FastAPI(title="AI Agent 个人工作台", version=APP_VERSION, lifespan=lifespan)
api.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5174", "http://localhost:5174", "http://127.0.0.1:8787"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id"],
)


async def changed(reason: str) -> None:
    await hub.broadcast({"type": "refresh", "reason": reason})


@api.get("/api/health")
async def healthcheck() -> dict:
    return {
        "ok": True,
        "app_version": APP_VERSION,
        "markdown_files": store.fingerprint()[0],
        "hermes": store.hermes_status(),
    }


@api.get("/api/system/info")
async def system_info() -> dict:
    files = [path for path in store.root.rglob("*") if path.is_file()]
    data_size = sum(path.stat().st_size for path in files)
    return {
        "app_version": APP_VERSION,
        "packaged": bool(getattr(sys, "frozen", False)) or os.getenv("WORKBENCH_INSTALLED", "").lower() == "true",
        "storage": {
            "mode": "markdown",
            "data_path": str(store.root),
            "cache_path": str(store.cache_dir),
            "backup_path": str(backups.backup_root),
            "file_count": len(files),
            "size_bytes": data_size,
            "size_mb": round(data_size / 1024 / 1024, 2),
            "obsidian_required": False,
        },
        "startup": startup_status(),
        "remote_access": remote_access_status(),
    }


@api.get("/api/system/backups")
async def list_backups() -> list[dict]:
    return backups.list()


@api.post("/api/system/backups", status_code=201)
async def create_backup(payload: BackupCreate) -> dict:
    record = backups.create(payload.label)
    store._log_event("create_backup", record["name"], "user")
    await changed("backup_created")
    return record


@api.get("/api/system/backups/{backup_name}")
async def download_backup(backup_name: str) -> FileResponse:
    try:
        target = backups.get(backup_name)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="备份不存在") from exc
    return FileResponse(target, filename=target.name, media_type="application/zip")


@api.post("/api/system/backups/{backup_name}/restore")
async def restore_backup(backup_name: str) -> dict:
    try:
        result = backups.restore(backup_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="备份不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store._log_event("restore_backup", backup_name, "user")
    store.rebuild_index()
    await changed("backup_restored")
    return result


@api.put("/api/system/startup")
async def set_startup(payload: StartupUpdate) -> dict:
    try:
        result = update_startup(payload.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await changed("startup_updated")
    return result


@api.post("/api/system/remote-access")
async def set_remote_access() -> dict:
    try:
        result = enable_remote_access()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await changed("remote_access_enabled")
    return result


@api.get("/api/dashboard")
async def dashboard() -> dict:
    return store.dashboard()


@api.get("/api/settings/profile")
async def get_profile_settings() -> dict:
    return store.get_profile_settings()


@api.put("/api/settings/profile")
async def update_profile_settings(payload: ProfileSettingsUpdate) -> dict:
    record = store.update_profile_settings(payload.nickname, payload.daily_message_style)
    await changed("profile_settings_updated")
    return record


@api.get("/api/settings/health")
async def get_health_goals() -> dict:
    return store.get_health_goals()


@api.put("/api/settings/health")
async def update_health_goals(payload: HealthGoalsUpdate) -> dict:
    record = store.update_health_goals(
        payload.gender,
        payload.height_cm,
        payload.current_weight_kg,
        payload.target_weight_kg,
        payload.cup_ml,
        payload.age,
        payload.activity_level,
    )
    store.record_weight(payload.current_weight_kg)
    await changed("health_goals_updated")
    return record


@api.get("/api/settings/ip")
async def get_ip_preferences() -> dict:
    return store.get_ip_preferences()


@api.put("/api/settings/ip")
async def update_ip_preferences(payload: IPPreferencesUpdate) -> dict:
    record = store.update_ip_preferences(payload.video_topics, payload.ai_topics)
    await changed("ip_preferences_updated")
    return record


@api.post("/api/greeting", status_code=201)
async def save_daily_message(payload: DailyMessageCreate) -> dict:
    record = store.save_daily_message(payload.message, payload.tone, source="user")
    await changed("daily_message_updated")
    return record


@api.get("/api/projects")
async def list_projects() -> list[dict]:
    return store.list_projects()


@api.post("/api/projects", status_code=201)
async def create_project(payload: ProjectCreate) -> dict:
    record = store.create_project(
        payload.name,
        payload.current_stage,
        payload.progress_percent,
        payload.next_milestone,
        payload.due_date,
    )
    await changed("project_created")
    return record


@api.patch("/api/projects/{project_id}")
async def update_project(project_id: str, payload: ProjectUpdate) -> dict:
    try:
        record = store.update_project(project_id, payload.model_dump(exclude_unset=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="项目不存在") from exc
    await changed("project_updated")
    return record


@api.get("/api/tasks")
async def list_tasks() -> list[dict]:
    return store.list_tasks()


@api.get("/api/tasks/deleted")
async def list_deleted_tasks() -> list[dict]:
    return [task for task in store.list_tasks(include_deleted=True) if task.get("deleted")]


@api.get("/api/calendar")
async def calendar_view(start_date: date, end_date: date) -> dict:
    try:
        return store.calendar(start_date, end_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@api.post("/api/tasks", status_code=201)
async def create_task(payload: TaskCreate) -> dict:
    record = store.create_task(
        payload.title,
        payload.quadrant,
        payload.due_at.isoformat() if payload.due_at else None,
        payload.note,
        payload.recurrence,
    )
    await changed("task_created")
    return record


@api.patch("/api/tasks/{task_id}")
async def update_task(task_id: str, payload: TaskUpdate) -> dict:
    try:
        record = store.update_task(task_id, payload.model_dump(mode="json", exclude_unset=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await changed("task_updated")
    return record


@api.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str) -> dict:
    try:
        record = store.delete_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    await changed("task_deleted")
    return record


@api.post("/api/tasks/{task_id}/restore")
async def restore_task(task_id: str) -> dict:
    try:
        record = store.restore_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    await changed("task_restored")
    return record


@api.post("/api/health/water")
async def record_water(payload: WaterRecord) -> dict:
    record = store.record_water(payload.ml)
    await changed("water_recorded")
    return record


@api.post("/api/health/weight")
async def record_weight(payload: WeightRecord) -> dict:
    record = store.record_weight(payload.kg)
    await changed("weight_recorded")
    return record


@api.post("/api/growth/plans", status_code=201)
async def create_learning_plan(payload: LearningPlanCreate) -> dict:
    record = store.create_learning_plan(payload.name, payload.goal)
    await changed("learning_plan_created")
    return record


@api.get("/api/growth/plans")
async def list_learning_plans() -> list[dict]:
    return store.get_growth()


@api.get("/api/growth/plans/{plan_id}")
async def get_learning_plan(plan_id: str) -> dict:
    try:
        return store.get_learning_plan(plan_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="学习计划不存在") from exc


@api.patch("/api/growth/plans/{plan_id}/progress")
async def update_learning_progress(plan_id: str, payload: LearningPlanProgressUpdate) -> dict:
    try:
        record = store.update_learning_progress(plan_id, payload.completed_lessons, payload.status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="学习计划不存在") from exc
    await changed("learning_progress_updated")
    return record


@api.get("/api/library")
async def list_library() -> list[dict]:
    return store.get_library()


@api.get("/api/library/{item_id}")
async def get_library_item(item_id: str) -> dict:
    try:
        return store.get_library_item(item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="书影音条目不存在") from exc


@api.post("/api/library", status_code=201)
async def create_library_item(payload: LibraryItemCreate) -> dict:
    record = store.create_library_item(payload.title, payload.kind, payload.reason)
    await changed("library_item_created")
    return record


@api.patch("/api/library/{item_id}")
async def update_library_item(item_id: str, payload: LibraryItemUpdate) -> dict:
    try:
        record = store.update_library_item(
            item_id,
            payload.status,
            payload.reflection,
            payload.agent_comment,
            payload.progress_percent,
            payload.current_position,
            payload.organized_notes,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="书影条目不存在") from exc
    await changed("library_item_updated")
    return record


@api.get("/api/content/{item_id}")
async def get_content_item(item_id: str) -> dict:
    try:
        return store.get_content_item(item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="内容不存在") from exc


@api.post("/api/hermes/suggestions", status_code=201)
async def create_suggestion(payload: AgentSuggestionCreate) -> dict:
    record = store.save_suggestion(payload.title, payload.content, payload.action_label)
    await changed("suggestion_created")
    return record


@api.get("/api/hermes/jobs")
async def list_agent_jobs(status: str | None = None, job_type: str | None = None) -> list[dict]:
    return store.list_agent_jobs(status=status, job_type=job_type)


@api.post("/api/uploads/{kind}", status_code=201)
async def upload_record(
    kind: str,
    file: UploadFile = File(...),
    record_date: str | None = Form(default=None),
    meal_slot: str | None = Form(default=None),
) -> dict:
    if kind not in {"meal", "weight", "exercise"}:
        raise HTTPException(status_code=400, detail="不支持的上传类型")
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="只支持图片文件")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="图片不能超过15MB")
    try:
        record = store.upload_record(
            kind,
            file.filename or f"{kind}.jpg",
            content,
            record_date=record_date,
            meal_slot=meal_slot,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await changed("image_uploaded")
    return record


@api.get("/api/health/records")
async def list_health_records(status: str | None = None) -> list[dict]:
    return store.list_health_records(status=status)


@api.get("/api/health/records/deleted")
async def list_deleted_health_records() -> list[dict]:
    return [record for record in store.list_health_records(limit=4000, include_deleted=True) if record.get("deleted")]


@api.patch("/api/health/records/{record_id}")
async def update_health_record(record_id: str, payload: HealthRecordUpdate) -> dict:
    try:
        record = store.update_health_record(
            record_id,
            payload.record_date.isoformat() if payload.record_date else None,
            payload.meal_slot,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="健康记录不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await changed("health_record_updated")
    return record


@api.delete("/api/health/records/{record_id}")
async def delete_health_record(record_id: str) -> dict:
    try:
        record = store.delete_health_record(record_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="健康记录不存在") from exc
    await changed("health_record_deleted")
    return record


@api.post("/api/health/records/{record_id}/restore")
async def restore_health_record(record_id: str) -> dict:
    try:
        record = store.restore_health_record(record_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="健康记录不存在") from exc
    await changed("health_record_restored")
    return record


@api.get("/api/health/history")
async def health_history(
    days: int = Query(default=30, ge=1, le=366),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
) -> dict:
    if (start_date is None) != (end_date is None):
        raise HTTPException(status_code=400, detail="自定义周期需要同时填写开始日期和结束日期")
    try:
        return store.health_history(days, start_date=start_date, end_date=end_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@api.get("/api/workbench-assets/{asset_path:path}")
async def workbench_asset(asset_path: str) -> FileResponse:
    target = (store.root / asset_path).resolve()
    try:
        target.relative_to(store.root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="附件路径无效") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="附件不存在")
    return FileResponse(target)


@api.post("/api/health/records/{record_id}/analysis")
async def analyze_health_record(record_id: str, payload: HealthAnalysisCreate) -> dict:
    try:
        record = store.analyze_health_record(
            record_id,
            payload.summary,
            payload.advice,
            payload.calories_kcal,
            payload.exercise_kcal,
            payload.weight_kg,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="健康记录不存在") from exc
    await changed("health_record_analyzed")
    return record


@api.post("/api/health/advice", status_code=201)
async def save_health_advice(payload: DailyHealthAdviceCreate) -> dict:
    record = store.save_daily_health_advice(
        payload.summary,
        payload.status,
        source="user",
        overall_summary=payload.overall_summary,
        diet_summary=payload.diet_summary,
        hydration_summary=payload.hydration_summary,
        exercise_summary=payload.exercise_summary,
    )
    await changed("health_advice_updated")
    return record


@api.post("/api/index/rebuild")
async def rebuild_index() -> dict:
    return store.rebuild_index()


@api.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await hub.connect(websocket)
    try:
        await websocket.send_json({"type": "connected"})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(websocket)


api.mount("/mcp", mcp_app)

if STATIC_DIR.exists():
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.exists():
        api.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @api.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str) -> FileResponse:
        candidate = (STATIC_DIR / path).resolve()
        if path and candidate.is_file() and STATIC_DIR.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
else:
    @api.get("/", include_in_schema=False)
    async def frontend_missing() -> JSONResponse:
        return JSONResponse({"message": "Frontend has not been built yet", "api": "/docs"})


class MCPBearerAuth:
    def __init__(self, application: Any) -> None:
        self.application = application
        self.token = os.getenv("WORKBENCH_MCP_TOKEN", "").strip()

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        path = scope.get("path", "")
        if self.token and path.startswith("/mcp"):
            headers = {key.lower(): value for key, value in scope.get("headers", [])}
            expected = f"Bearer {self.token}".encode()
            if headers.get(b"authorization") != expected:
                response = JSONResponse({"detail": "MCP token无效"}, status_code=401)
                await response(scope, receive, send)
                return
            store.touch_hermes()
        await self.application(scope, receive, send)


app = MCPBearerAuth(api)
