from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..china_calendar import calendar_days
from .models import (
    AuditEvent,
    DailyMessage,
    Project,
    ProjectPhase,
    Suggestion,
    Task,
    TaskDependency,
    TaskOccurrence,
    WorkspaceEvent,
)


QUADRANTS = {
    "important_urgent": "重要·紧急",
    "important_not_urgent": "重要·不紧急",
    "not_important_urgent": "不重要·紧急",
    "not_important_not_urgent": "不重要·不紧急",
}
TASK_STATUSES = {"planned", "in_progress", "blocked", "completed", "cancelled"}
PROJECT_STATUSES = {"active", "paused", "completed"}


def _short_message(message: str) -> str:
    compact = " ".join(str(message).split()).strip()
    if not compact:
        return ""
    sentence = re.split(r"(?<=[。！？!?])\s*", compact, maxsplit=1)[0]
    return sentence if len(sentence) <= 48 else f"{sentence[:47]}…"


def _aware(value: datetime | None, timezone_name: str) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=ZoneInfo(timezone_name))


def _as_date(value: date | str | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


class CoreRepository:
    def __init__(
        self,
        session: AsyncSession,
        workspace_id: int,
        actor_type: str,
        actor_public_id: uuid.UUID | None,
        timezone_name: str = "Asia/Shanghai",
    ) -> None:
        self.session = session
        self.workspace_id = workspace_id
        self.actor_type = actor_type
        self.actor_public_id = actor_public_id
        self.timezone_name = timezone_name

    def _changed(
        self,
        event_type: str,
        entity_type: str,
        entity_key: str,
        action: str,
        payload: dict | None = None,
    ) -> None:
        self.session.add_all(
            [
                WorkspaceEvent(
                    workspace_id=self.workspace_id,
                    event_type=event_type,
                    entity_type=entity_type,
                    entity_key=entity_key,
                    payload=payload or {},
                ),
                AuditEvent(
                    workspace_id=self.workspace_id,
                    actor_type=self.actor_type,
                    actor_public_id=self.actor_public_id,
                    action=action,
                    entity_type=entity_type,
                    entity_key=entity_key,
                    details={},
                ),
            ]
        )

    @staticmethod
    def project_payload(project: Project) -> dict:
        return {
            "id": str(project.public_id),
            "name": project.name,
            "description": project.description,
            "start_date": project.start_date.isoformat() if project.start_date else None,
            "current_stage": project.current_stage,
            "progress_percent": project.progress_percent,
            "next_milestone": project.next_milestone,
            "due_date": project.due_date.isoformat() if project.due_date else None,
            "status": project.status,
            "source": project.source,
            "deleted": project.deleted_at is not None,
            "deleted_at": project.deleted_at.isoformat() if project.deleted_at else None,
            "details": f"# {project.name}\n\n## 当前阶段\n\n{project.current_stage}",
            "updated_at": project.updated_at.isoformat(),
        }

    async def _get_project(self, project_public_id: uuid.UUID, include_deleted: bool = False) -> Project:
        statement = select(Project).where(
            Project.workspace_id == self.workspace_id,
            Project.public_id == project_public_id,
        )
        if not include_deleted:
            statement = statement.where(Project.deleted_at.is_(None))
        project = await self.session.scalar(statement)
        if project is None:
            raise KeyError(str(project_public_id))
        return project

    async def list_projects(self, include_deleted: bool = False) -> list[dict]:
        statement = select(Project).where(Project.workspace_id == self.workspace_id)
        if not include_deleted:
            statement = statement.where(Project.deleted_at.is_(None))
        projects = list((await self.session.scalars(
            statement.order_by(Project.deleted_at.is_not(None), Project.status != "active", Project.updated_at.desc(), Project.id)
        )).all())
        return [self.project_payload(project) for project in projects]

    async def create_project(
        self,
        name: str,
        description: str,
        current_stage: str,
        progress_percent: int,
        next_milestone: str,
        start_date: date | str | None,
        due_date: date | str | None,
        source: str = "user",
    ) -> dict:
        start = _as_date(start_date)
        due = _as_date(due_date)
        if start and due and due < start:
            raise ValueError("目标日期不能早于开始日期")
        project = Project(
            workspace_id=self.workspace_id,
            name=name.strip(),
            description=description.strip(),
            start_date=start,
            current_stage=current_stage.strip() or "准备中",
            progress_percent=progress_percent,
            next_milestone=next_milestone.strip(),
            due_date=due,
            source=source,
        )
        self.session.add(project)
        await self.session.flush()
        self._changed(
            "project.created",
            "project",
            str(project.public_id),
            "create_project",
            {"progress_percent": project.progress_percent},
        )
        return self.project_payload(project)

    async def update_project(self, project_public_id: uuid.UUID, updates: dict) -> dict:
        project = await self._get_project(project_public_id)
        for field in ("name", "description", "current_stage", "progress_percent", "next_milestone", "status"):
            if field in updates and updates[field] is not None:
                value = updates[field]
                setattr(project, field, value.strip() if isinstance(value, str) else value)
        if "start_date" in updates:
            project.start_date = _as_date(updates["start_date"])
        if "due_date" in updates:
            project.due_date = _as_date(updates["due_date"])
        if project.start_date and project.due_date and project.due_date < project.start_date:
            raise ValueError("目标日期不能早于开始日期")
        project.updated_at = datetime.now(timezone.utc)
        self._changed(
            "project.updated",
            "project",
            str(project.public_id),
            "update_project",
            {"progress_percent": project.progress_percent, "status": project.status},
        )
        return self.project_payload(project)

    async def delete_project(self, project_public_id: uuid.UUID) -> dict:
        project = await self._get_project(project_public_id)
        project.deleted_at = datetime.now(timezone.utc)
        project.updated_at = project.deleted_at
        self._changed("project.deleted", "project", str(project.public_id), "delete_project")
        return self.project_payload(project)

    async def restore_project(self, project_public_id: uuid.UUID) -> dict:
        project = await self._get_project(project_public_id, include_deleted=True)
        project.deleted_at = None
        project.updated_at = datetime.now(timezone.utc)
        self._changed("project.restored", "project", str(project.public_id), "restore_project")
        return self.project_payload(project)

    @staticmethod
    def phase_payload(phase: ProjectPhase, progress_percent: int = 0, task_count: int = 0) -> dict:
        return {
            "id": str(phase.public_id),
            "project_id": None,
            "name": phase.name,
            "description": phase.description,
            "start_date": phase.start_date.isoformat() if phase.start_date else None,
            "end_date": phase.end_date.isoformat() if phase.end_date else None,
            "status": phase.status,
            "order_index": phase.order_index,
            "progress_percent": progress_percent,
            "task_count": task_count,
            "source": phase.source,
            "deleted": phase.deleted_at is not None,
            "deleted_at": phase.deleted_at.isoformat() if phase.deleted_at else None,
            "updated_at": phase.updated_at.isoformat(),
        }

    async def _get_phase(self, phase_public_id: uuid.UUID, include_deleted: bool = False) -> ProjectPhase:
        statement = select(ProjectPhase).where(
            ProjectPhase.workspace_id == self.workspace_id,
            ProjectPhase.public_id == phase_public_id,
        )
        if not include_deleted:
            statement = statement.where(ProjectPhase.deleted_at.is_(None))
        phase = await self.session.scalar(statement)
        if phase is None:
            raise KeyError(str(phase_public_id))
        return phase

    async def _phase_progress(self, phase_ids: list[int]) -> dict[int, tuple[int, int]]:
        if not phase_ids:
            return {}
        tasks = list((await self.session.scalars(
            select(Task).where(
                Task.workspace_id == self.workspace_id,
                Task.phase_id.in_(phase_ids),
                Task.deleted_at.is_(None),
                Task.status != "cancelled",
            )
        )).all())
        values: dict[int, list[int]] = {}
        for task in tasks:
            if task.phase_id is not None:
                values.setdefault(task.phase_id, []).append(task.progress_percent)
        return {
            phase_id: (round(sum(progress) / len(progress)), len(progress))
            for phase_id, progress in values.items()
        }

    async def list_phases(self, project_public_id: uuid.UUID, include_deleted: bool = False) -> list[dict]:
        project = await self._get_project(project_public_id, include_deleted=include_deleted)
        statement = select(ProjectPhase).where(
            ProjectPhase.workspace_id == self.workspace_id,
            ProjectPhase.project_id == project.id,
        )
        if not include_deleted:
            statement = statement.where(ProjectPhase.deleted_at.is_(None))
        phases = list((await self.session.scalars(
            statement.order_by(ProjectPhase.deleted_at.is_not(None), ProjectPhase.order_index, ProjectPhase.id)
        )).all())
        progress = await self._phase_progress([phase.id for phase in phases])
        payloads = []
        for phase in phases:
            percent, task_count = progress.get(phase.id, (0, 0))
            payload = self.phase_payload(phase, percent, task_count)
            payload["project_id"] = str(project.public_id)
            payloads.append(payload)
        return payloads

    async def create_phase(
        self,
        project_public_id: uuid.UUID,
        name: str,
        description: str,
        start_date: date | str | None,
        end_date: date | str | None,
        status: str,
        order_index: int,
        source: str = "user",
    ) -> dict:
        project = await self._get_project(project_public_id)
        start, end = _as_date(start_date), _as_date(end_date)
        if start and end and end < start:
            raise ValueError("阶段结束日期不能早于开始日期")
        if status not in PROJECT_STATUSES:
            raise ValueError("不支持的阶段状态")
        phase = ProjectPhase(
            workspace_id=self.workspace_id,
            project_id=project.id,
            name=name.strip(),
            description=description.strip(),
            start_date=start,
            end_date=end,
            status=status,
            order_index=order_index,
            source=source,
        )
        self.session.add(phase)
        await self.session.flush()
        self._changed("project_phase.created", "project_phase", str(phase.public_id), "create_project_phase")
        payload = self.phase_payload(phase)
        payload["project_id"] = str(project.public_id)
        return payload

    async def update_phase(self, phase_public_id: uuid.UUID, updates: dict) -> dict:
        phase = await self._get_phase(phase_public_id)
        for field in ("name", "description", "status", "order_index"):
            if field in updates and updates[field] is not None:
                value = updates[field]
                setattr(phase, field, value.strip() if isinstance(value, str) else value)
        if "start_date" in updates:
            phase.start_date = _as_date(updates["start_date"])
        if "end_date" in updates:
            phase.end_date = _as_date(updates["end_date"])
        if phase.start_date and phase.end_date and phase.end_date < phase.start_date:
            raise ValueError("阶段结束日期不能早于开始日期")
        if phase.status not in PROJECT_STATUSES:
            raise ValueError("不支持的阶段状态")
        phase.updated_at = datetime.now(timezone.utc)
        self._changed("project_phase.updated", "project_phase", str(phase.public_id), "update_project_phase")
        project = await self.session.get(Project, phase.project_id)
        progress = await self._phase_progress([phase.id])
        percent, task_count = progress.get(phase.id, (0, 0))
        payload = self.phase_payload(phase, percent, task_count)
        payload["project_id"] = str(project.public_id) if project else None
        return payload

    async def delete_phase(self, phase_public_id: uuid.UUID) -> dict:
        phase = await self._get_phase(phase_public_id)
        phase.deleted_at = datetime.now(timezone.utc)
        phase.updated_at = phase.deleted_at
        await self._recalculate_project(phase.project_id)
        self._changed("project_phase.deleted", "project_phase", str(phase.public_id), "delete_project_phase")
        payload = self.phase_payload(phase)
        project = await self.session.get(Project, phase.project_id)
        payload["project_id"] = str(project.public_id) if project else None
        return payload

    async def restore_phase(self, phase_public_id: uuid.UUID) -> dict:
        phase = await self._get_phase(phase_public_id, include_deleted=True)
        project = await self.session.get(Project, phase.project_id)
        if project is None or project.deleted_at is not None:
            raise ValueError("请先恢复该阶段所属的项目")
        phase.deleted_at = None
        phase.updated_at = datetime.now(timezone.utc)
        await self._recalculate_project(phase.project_id)
        self._changed("project_phase.restored", "project_phase", str(phase.public_id), "restore_project_phase")
        payload = self.phase_payload(phase)
        payload["project_id"] = str(project.public_id)
        return payload

    @staticmethod
    def task_payload(
        task: Task,
        completed_occurrences: list[str] | None = None,
        project: Project | None = None,
        phase: ProjectPhase | None = None,
        predecessor_ids: list[str] | None = None,
    ) -> dict:
        return {
            "id": str(task.public_id),
            "title": task.title,
            "quadrant": task.quadrant,
            "quadrant_label": QUADRANTS.get(task.quadrant, "重要·不紧急"),
            "done": task.done,
            "due_at": task.due_at.isoformat() if task.due_at else None,
            "project_id": str(project.public_id) if project else None,
            "project_name": project.name if project else None,
            "phase_id": str(phase.public_id) if phase else None,
            "phase_name": phase.name if phase else None,
            "start_date": task.start_date.isoformat() if task.start_date else None,
            "end_date": task.end_date.isoformat() if task.end_date else None,
            "status": task.status,
            "progress_percent": task.progress_percent,
            "is_milestone": task.is_milestone,
            "order_index": task.order_index,
            "predecessor_ids": predecessor_ids or [],
            "recurrence": task.recurrence,
            "completed_occurrences": completed_occurrences or [],
            "deleted": task.deleted_at is not None,
            "deleted_at": task.deleted_at.isoformat() if task.deleted_at else None,
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
            "note": task.note,
        }

    async def _task_context_maps(
        self, tasks: list[Task]
    ) -> tuple[dict[int, Project], dict[int, ProjectPhase]]:
        project_ids = {task.project_id for task in tasks if task.project_id is not None}
        phase_ids = {task.phase_id for task in tasks if task.phase_id is not None}
        projects = list((await self.session.scalars(
            select(Project).where(Project.workspace_id == self.workspace_id, Project.id.in_(project_ids))
        )).all()) if project_ids else []
        phases = list((await self.session.scalars(
            select(ProjectPhase).where(ProjectPhase.workspace_id == self.workspace_id, ProjectPhase.id.in_(phase_ids))
        )).all()) if phase_ids else []
        return ({item.id: item for item in projects}, {item.id: item for item in phases})

    async def _dependency_map(self, task_ids: list[int]) -> dict[int, list[str]]:
        if not task_ids:
            return {}
        rows = (await self.session.execute(
            select(TaskDependency.task_id, Task.public_id)
            .join(Task, Task.id == TaskDependency.predecessor_task_id)
            .where(
                TaskDependency.workspace_id == self.workspace_id,
                TaskDependency.task_id.in_(task_ids),
            )
            .order_by(TaskDependency.id)
        )).all()
        result: dict[int, list[str]] = {}
        for task_id, predecessor_public_id in rows:
            result.setdefault(task_id, []).append(str(predecessor_public_id))
        return result

    async def _task_occurrence_map(self, task_ids: list[int]) -> dict[int, list[str]]:
        if not task_ids:
            return {}
        occurrences = list(
            (
                await self.session.scalars(
                    select(TaskOccurrence).where(
                        TaskOccurrence.workspace_id == self.workspace_id,
                        TaskOccurrence.task_id.in_(task_ids),
                    )
                )
            ).all()
        )
        result: dict[int, list[str]] = {}
        for occurrence in occurrences:
            result.setdefault(occurrence.task_id, []).append(occurrence.occurrence_date.isoformat())
        for values in result.values():
            values.sort()
        return result

    async def list_tasks(
        self,
        include_deleted: bool = False,
        project_public_id: uuid.UUID | None = None,
    ) -> list[dict]:
        statement = select(Task).where(Task.workspace_id == self.workspace_id)
        if project_public_id is not None:
            project = await self._get_project(project_public_id, include_deleted=include_deleted)
            statement = statement.where(Task.project_id == project.id)
        if not include_deleted:
            statement = statement.where(Task.deleted_at.is_(None))
        tasks = list((await self.session.scalars(statement)).all())
        project_map, phase_map = await self._task_context_maps(tasks)
        if not include_deleted:
            tasks = [
                task for task in tasks
                if (task.project_id is None or project_map.get(task.project_id) is not None and project_map[task.project_id].deleted_at is None)
                and (task.phase_id is None or phase_map.get(task.phase_id) is not None and phase_map[task.phase_id].deleted_at is None)
            ]
        occurrences = await self._task_occurrence_map([task.id for task in tasks])
        dependencies = await self._dependency_map([task.id for task in tasks])
        payloads = [
            self.task_payload(
                task,
                occurrences.get(task.id),
                project_map.get(task.project_id) if task.project_id else None,
                phase_map.get(task.phase_id) if task.phase_id else None,
                dependencies.get(task.id),
            )
            for task in tasks
        ]
        return sorted(
            payloads,
            key=lambda item: (
                item["done"],
                item.get("start_date") or item.get("due_at") or "9999",
                item.get("order_index") or 0,
                item["title"],
            ),
        )

    async def _get_task(self, task_public_id: uuid.UUID, include_deleted: bool = False) -> Task:
        statement = select(Task).where(
            Task.workspace_id == self.workspace_id,
            Task.public_id == task_public_id,
        )
        if not include_deleted:
            statement = statement.where(Task.deleted_at.is_(None))
        task = await self.session.scalar(statement)
        if task is None:
            raise KeyError(str(task_public_id))
        return task

    async def create_task(
        self,
        title: str,
        quadrant: str,
        due_at: datetime | None,
        note: str,
        recurrence: str,
        project_public_id: uuid.UUID | None = None,
        phase_public_id: uuid.UUID | None = None,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        status: str = "planned",
        progress_percent: int = 0,
        is_milestone: bool = False,
        order_index: int = 0,
        predecessor_public_ids: list[uuid.UUID] | None = None,
        source: str = "user",
    ) -> dict:
        if quadrant not in QUADRANTS:
            raise ValueError("不支持的任务象限")
        if recurrence not in {"none", "yearly"}:
            raise ValueError("不支持的重复规则")
        due_at = _aware(due_at, self.timezone_name)
        if recurrence == "yearly" and due_at is None:
            raise ValueError("每年重复的安排必须选择日期")
        project, phase = await self._resolve_task_context(project_public_id, phase_public_id)
        start, end = _as_date(start_date), _as_date(end_date)
        if start and end and end < start:
            raise ValueError("任务结束日期不能早于开始日期")
        if status not in TASK_STATUSES:
            raise ValueError("不支持的任务状态")
        if status == "completed" or progress_percent == 100:
            status, progress_percent = "completed", 100
        task = Task(
            workspace_id=self.workspace_id,
            project_id=project.id if project else None,
            phase_id=phase.id if phase else None,
            title=title.strip(),
            quadrant=quadrant,
            due_at=due_at,
            note=note.strip(),
            recurrence=recurrence,
            start_date=start,
            end_date=end,
            status=status,
            progress_percent=progress_percent,
            is_milestone=is_milestone,
            order_index=order_index,
            done=status == "completed",
            completed_at=datetime.now(timezone.utc) if status == "completed" else None,
            source=source,
        )
        self.session.add(task)
        await self.session.flush()
        predecessor_ids = await self._replace_dependencies(task, predecessor_public_ids or [], source)
        if task.project_id is not None:
            await self._recalculate_project(task.project_id)
        self._changed("task.created", "task", str(task.public_id), "create_task")
        return self.task_payload(task, project=project, phase=phase, predecessor_ids=predecessor_ids)

    async def update_task(self, task_public_id: uuid.UUID, updates: dict, source: str = "user") -> dict:
        task = await self._get_task(task_public_id, include_deleted=True)
        if task.deleted_at is not None:
            raise KeyError(str(task_public_id))
        recurrence = updates.get("recurrence", task.recurrence)
        due_at = _aware(updates.get("due_at", task.due_at), self.timezone_name)
        if recurrence not in {"none", "yearly"}:
            raise ValueError("不支持的重复规则")
        if recurrence == "yearly" and due_at is None:
            raise ValueError("每年重复的安排必须选择日期")
        old_project_id = task.project_id

        project_public_id = updates.get("project_id") if "project_id" in updates else None
        phase_public_id = updates.get("phase_id") if "phase_id" in updates else None
        if "project_id" in updates or "phase_id" in updates:
            if "project_id" not in updates:
                current_project = await self.session.get(Project, task.project_id) if task.project_id else None
                project_public_id = current_project.public_id if current_project else None
            if "project_id" in updates and "phase_id" not in updates:
                phase_public_id = None
            elif "phase_id" not in updates:
                current_phase = await self.session.get(ProjectPhase, task.phase_id) if task.phase_id else None
                phase_public_id = current_phase.public_id if current_phase else None
            project, phase = await self._resolve_task_context(project_public_id, phase_public_id)
            task.project_id = project.id if project else None
            task.phase_id = phase.id if phase else None

        start = _as_date(updates.get("start_date", task.start_date))
        end = _as_date(updates.get("end_date", task.end_date))
        if start and end and end < start:
            raise ValueError("任务结束日期不能早于开始日期")
        if "start_date" in updates:
            task.start_date = start
        if "end_date" in updates:
            task.end_date = end

        if "done" in updates and updates["done"] is not None:
            occurrence_date = updates.get("occurrence_date")
            if recurrence == "yearly" and occurrence_date:
                occurrence_day = (
                    occurrence_date
                    if isinstance(occurrence_date, date)
                    else date.fromisoformat(str(occurrence_date)[:10])
                )
                existing = await self.session.scalar(
                    select(TaskOccurrence).where(
                        TaskOccurrence.workspace_id == self.workspace_id,
                        TaskOccurrence.task_id == task.id,
                        TaskOccurrence.occurrence_date == occurrence_day,
                    )
                )
                if updates["done"] and existing is None:
                    self.session.add(
                        TaskOccurrence(
                            workspace_id=self.workspace_id,
                            task_id=task.id,
                            occurrence_date=occurrence_day,
                            source=source,
                        )
                    )
                elif not updates["done"] and existing is not None:
                    await self.session.delete(existing)
            else:
                task.done = bool(updates["done"])
                task.completed_at = datetime.now(timezone.utc) if task.done else None
                task.status = "completed" if task.done else ("in_progress" if task.progress_percent else "planned")
                task.progress_percent = 100 if task.done else min(task.progress_percent, 99)

        for field in ("title", "quadrant", "note", "recurrence", "is_milestone", "order_index"):
            if field in updates and updates[field] is not None:
                setattr(task, field, updates[field])
        if "due_at" in updates:
            task.due_at = due_at
        if "status" in updates and updates["status"] is not None:
            if updates["status"] not in TASK_STATUSES:
                raise ValueError("不支持的任务状态")
            task.status = updates["status"]
            if task.status != "completed" and task.progress_percent == 100 and "progress_percent" not in updates:
                task.progress_percent = 99
        if "progress_percent" in updates and updates["progress_percent"] is not None:
            task.progress_percent = updates["progress_percent"]
            if task.progress_percent < 100 and task.status == "completed" and "status" not in updates:
                task.status = "in_progress" if task.progress_percent else "planned"
        if task.status == "completed" or task.progress_percent == 100:
            task.status = "completed"
            task.progress_percent = 100
            task.done = True
            task.completed_at = task.completed_at or datetime.now(timezone.utc)
        elif "status" in updates or "progress_percent" in updates:
            task.done = False
            task.completed_at = None
            if task.status == "completed":
                task.status = "in_progress" if task.progress_percent else "planned"
        predecessor_ids = None
        if "predecessor_ids" in updates and updates["predecessor_ids"] is not None:
            predecessor_ids = await self._replace_dependencies(task, updates["predecessor_ids"], source)
        task.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        completed = (await self._task_occurrence_map([task.id])).get(task.id, [])
        if predecessor_ids is None:
            predecessor_ids = (await self._dependency_map([task.id])).get(task.id, [])
        for project_id in {old_project_id, task.project_id} - {None}:
            await self._recalculate_project(project_id)
        project = await self.session.get(Project, task.project_id) if task.project_id else None
        phase = await self.session.get(ProjectPhase, task.phase_id) if task.phase_id else None
        self._changed("task.updated", "task", str(task.public_id), "update_task")
        return self.task_payload(task, completed, project, phase, predecessor_ids)

    async def delete_task(self, task_public_id: uuid.UUID) -> dict:
        task = await self._get_task(task_public_id)
        task.deleted_at = datetime.now(timezone.utc)
        task.updated_at = task.deleted_at
        if task.project_id is not None:
            await self._recalculate_project(task.project_id)
        self._changed("task.deleted", "task", str(task.public_id), "delete_task")
        return self.task_payload(task)

    async def restore_task(self, task_public_id: uuid.UUID) -> dict:
        task = await self._get_task(task_public_id, include_deleted=True)
        task.deleted_at = None
        task.updated_at = datetime.now(timezone.utc)
        if task.project_id is not None:
            await self._recalculate_project(task.project_id)
        self._changed("task.restored", "task", str(task.public_id), "restore_task")
        return self.task_payload(task)

    async def _resolve_task_context(
        self,
        project_public_id: uuid.UUID | None,
        phase_public_id: uuid.UUID | None,
    ) -> tuple[Project | None, ProjectPhase | None]:
        project = await self._get_project(project_public_id) if project_public_id else None
        phase = await self._get_phase(phase_public_id) if phase_public_id else None
        if phase is not None:
            phase_project = await self.session.get(Project, phase.project_id)
            if phase_project is None or phase_project.deleted_at is not None:
                raise ValueError("阶段所属项目不可用")
            if project is not None and project.id != phase.project_id:
                raise ValueError("任务所属项目与阶段不一致")
            project = phase_project
        return project, phase

    async def _replace_dependencies(
        self,
        task: Task,
        predecessor_public_ids: list[uuid.UUID],
        source: str,
    ) -> list[str]:
        ordered_ids = list(dict.fromkeys(predecessor_public_ids))
        predecessors = list((await self.session.scalars(
            select(Task).where(
                Task.workspace_id == self.workspace_id,
                Task.public_id.in_(ordered_ids),
                Task.deleted_at.is_(None),
            )
        )).all()) if ordered_ids else []
        by_public = {item.public_id: item for item in predecessors}
        if len(by_public) != len(ordered_ids):
            raise ValueError("前置任务不存在或不属于当前工作空间")
        if any(item.id == task.id for item in predecessors):
            raise ValueError("任务不能依赖自己")

        rows = (await self.session.execute(
            select(TaskDependency.task_id, TaskDependency.predecessor_task_id).where(
                TaskDependency.workspace_id == self.workspace_id,
                TaskDependency.task_id != task.id,
            )
        )).all()
        graph: dict[int, set[int]] = {}
        for task_id, predecessor_id in rows:
            graph.setdefault(task_id, set()).add(predecessor_id)
        graph[task.id] = {item.id for item in predecessors}

        def reaches(start_id: int, target_id: int) -> bool:
            stack, seen = [start_id], set()
            while stack:
                current = stack.pop()
                if current == target_id:
                    return True
                if current in seen:
                    continue
                seen.add(current)
                stack.extend(graph.get(current, ()))
            return False

        if any(reaches(item.id, task.id) for item in predecessors):
            raise ValueError("前置任务关系不能形成循环")
        await self.session.execute(
            delete(TaskDependency).where(
                TaskDependency.workspace_id == self.workspace_id,
                TaskDependency.task_id == task.id,
            )
        )
        for public_id in ordered_ids:
            self.session.add(TaskDependency(
                workspace_id=self.workspace_id,
                task_id=task.id,
                predecessor_task_id=by_public[public_id].id,
                source=source,
            ))
        await self.session.flush()
        return [str(public_id) for public_id in ordered_ids]

    async def _recalculate_project(self, project_id: int) -> None:
        project = await self.session.get(Project, project_id)
        if project is None:
            return
        phases = list((await self.session.scalars(
            select(ProjectPhase).where(
                ProjectPhase.workspace_id == self.workspace_id,
                ProjectPhase.project_id == project_id,
                ProjectPhase.deleted_at.is_(None),
            ).order_by(ProjectPhase.order_index, ProjectPhase.id)
        )).all())
        active_phase_ids = {phase.id for phase in phases}
        tasks = list((await self.session.scalars(
            select(Task).where(
                Task.workspace_id == self.workspace_id,
                Task.project_id == project_id,
                Task.deleted_at.is_(None),
                Task.status != "cancelled",
            )
        )).all())
        tasks = [task for task in tasks if task.phase_id is None or task.phase_id in active_phase_ids]
        if not tasks:
            return
        project.progress_percent = round(sum(task.progress_percent for task in tasks) / len(tasks))
        incomplete_phase = next(
            (
                phase for phase in phases
                if any(task.phase_id == phase.id and task.progress_percent < 100 for task in tasks)
            ),
            None,
        )
        project.current_stage = incomplete_phase.name if incomplete_phase else ("已完成" if project.progress_percent == 100 else project.current_stage)
        milestones = sorted(
            (task for task in tasks if task.is_milestone and task.progress_percent < 100),
            key=lambda item: (item.end_date or item.start_date or date.max, item.order_index, item.id),
        )
        project.next_milestone = milestones[0].title if milestones else ("" if project.progress_percent == 100 else project.next_milestone)
        if project.status != "paused":
            project.status = "completed" if project.progress_percent == 100 else "active"
        project.updated_at = datetime.now(timezone.utc)

    async def project_plan(self, project_public_id: uuid.UUID, include_deleted: bool = False) -> dict:
        project = await self._get_project(project_public_id, include_deleted=include_deleted)
        phases = await self.list_phases(project_public_id, include_deleted=include_deleted)
        tasks = await self.list_tasks(include_deleted=include_deleted, project_public_id=project_public_id)
        active_tasks = [item for item in tasks if not item["deleted"]]
        dates = [
            _as_date(value)
            for item in active_tasks
            for value in (item.get("start_date"), item.get("end_date"))
            if value
        ]
        return {
            "project": self.project_payload(project),
            "phases": phases,
            "tasks": tasks,
            "unscheduled_tasks": [item for item in active_tasks if not item.get("start_date") and not item.get("end_date")],
            "date_range": {
                "start_date": min(dates).isoformat() if dates else project.start_date.isoformat() if project.start_date else None,
                "end_date": max(dates).isoformat() if dates else project.due_date.isoformat() if project.due_date else None,
            },
            "deleted_counts": {
                "phases": sum(1 for item in phases if item["deleted"]),
                "tasks": sum(1 for item in tasks if item["deleted"]),
            },
        }

    @staticmethod
    def _occurrence(task: dict, occurrence_date: date) -> dict:
        occurrence_text = occurrence_date.isoformat()
        base_due_at = str(task.get("due_at") or "")
        scheduled_at = f"{occurrence_text}{base_due_at[10:]}" if len(base_due_at) > 10 else occurrence_text
        recurring = task.get("recurrence") == "yearly"
        return {
            **task,
            "event_id": f"{task['id']}@{occurrence_text}",
            "occurrence_date": occurrence_text,
            "base_due_at": base_due_at,
            "due_at": scheduled_at,
            "done": occurrence_text in task.get("completed_occurrences", []) if recurring else task["done"],
        }

    async def calendar(self, start_date: date, end_date: date) -> dict:
        if start_date > end_date:
            raise ValueError("开始日期不能晚于结束日期")
        if (end_date - start_date).days > 370:
            raise ValueError("一次最多查看371天")
        occurrences: list[dict] = []
        undated: list[dict] = []
        for task in await self.list_tasks():
            due_at = str(task.get("due_at") or task.get("end_date") or "")
            if not due_at:
                undated.append(task)
                continue
            due_date = date.fromisoformat(due_at[:10])
            if task["recurrence"] == "yearly":
                for year in range(start_date.year, end_date.year + 1):
                    try:
                        current = date(year, due_date.month, due_date.day)
                    except ValueError:
                        continue
                    if start_date <= current <= end_date:
                        occurrences.append(self._occurrence(task, current))
            elif start_date <= due_date <= end_date:
                occurrences.append(self._occurrence(task, due_date))
        occurrences.sort(key=lambda item: (item["occurrence_date"], item.get("due_at") or "", item["title"]))
        days, notices = calendar_days(start_date, end_date)
        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "days": days,
            "tasks": occurrences,
            "undated_tasks": undated,
            "holiday_notices": notices,
        }

    async def save_daily_message(
        self,
        message: str,
        tone: str,
        target_date: date | None = None,
        source: str = "user",
    ) -> dict:
        target_date = target_date or datetime.now(ZoneInfo(self.timezone_name)).date()
        cleaned = _short_message(message)
        if not cleaned:
            raise ValueError("每日寄语不能为空")
        record = await self.session.scalar(
            select(DailyMessage).where(
                DailyMessage.workspace_id == self.workspace_id,
                DailyMessage.target_date == target_date,
            )
        )
        if record is None:
            record = DailyMessage(
                workspace_id=self.workspace_id,
                target_date=target_date,
                message=cleaned,
                tone=tone,
                source=source,
            )
            self.session.add(record)
            await self.session.flush()
        else:
            record.message = cleaned
            record.tone = tone
            record.source = source
            record.updated_at = datetime.now(timezone.utc)
        self._changed("daily_message.updated", "daily_message", target_date.isoformat(), "save_daily_message")
        return {
            "date": target_date.isoformat(),
            "message": record.message,
            "tone": record.tone,
            "generated_by": record.source,
            "updated_at": record.updated_at.isoformat(),
        }

    async def get_daily_message(self, target_date: date | None = None) -> dict:
        target_date = target_date or datetime.now(ZoneInfo(self.timezone_name)).date()
        record = await self.session.scalar(
            select(DailyMessage).where(
                DailyMessage.workspace_id == self.workspace_id,
                DailyMessage.target_date == target_date,
            )
        )
        if record is None:
            return {
                "date": target_date.isoformat(),
                "message": "今天先把最重要的一件事放稳。",
                "tone": "mixed",
                "generated_by": "fallback",
                "updated_at": None,
            }
        return {
            "date": target_date.isoformat(),
            "message": record.message,
            "tone": record.tone,
            "generated_by": record.source,
            "updated_at": record.updated_at.isoformat(),
        }

    async def latest_suggestion(self) -> dict | None:
        record = await self.session.scalar(
            select(Suggestion)
            .where(Suggestion.workspace_id == self.workspace_id, Suggestion.deleted_at.is_(None))
            .order_by(Suggestion.updated_at.desc(), Suggestion.id.desc())
            .limit(1)
        )
        if record is None:
            return None
        return {
            "id": str(record.public_id),
            "title": record.title,
            "content": record.content,
            "action_label": record.action_label,
            "source": record.source,
            "updated_at": record.updated_at.isoformat(),
        }

    async def save_suggestion(
        self,
        title: str,
        content: str,
        action_label: str = "",
        source: str = "hermes",
    ) -> dict:
        cleaned_title = title.strip()
        cleaned_content = content.strip()
        if not cleaned_title:
            raise ValueError("建议标题不能为空")
        if not cleaned_content:
            raise ValueError("建议内容不能为空")
        record = Suggestion(
            workspace_id=self.workspace_id,
            title=cleaned_title[:160],
            content=cleaned_content,
            action_label=action_label.strip()[:60],
            source=source,
            is_read=False,
        )
        self.session.add(record)
        await self.session.flush()
        self._changed(
            "suggestion.saved",
            "suggestion",
            str(record.public_id),
            "save_suggestion",
        )
        return {
            "id": str(record.public_id),
            "title": record.title,
            "content": record.content,
            "action_label": record.action_label,
            "source": record.source,
            "updated_at": record.updated_at.isoformat(),
        }
