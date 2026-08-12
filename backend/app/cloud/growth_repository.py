from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .core_repository import CoreRepository
from .jobs import enqueue_job
from .models import AgentJob, ContentItem, LearningPlan, LibraryItem


class GrowthRepository:
    def __init__(
        self,
        session: AsyncSession,
        workspace_id: int,
        actor_type: str,
        actor_public_id: uuid.UUID | None,
    ) -> None:
        self.session = session
        self.workspace_id = workspace_id
        self.actor_type = actor_type
        self.actor_public_id = actor_public_id
        self.core = CoreRepository(session, workspace_id, actor_type, actor_public_id)

    @staticmethod
    def _job_payload(job: AgentJob | None) -> dict | None:
        if job is None:
            return None
        return {
            "id": str(job.public_id),
            "type": job.job_type,
            "title": job.title,
            "status": job.status,
            "result_summary": job.result_summary,
            "error_code": job.error_code,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
        }

    async def _latest_job(self, subject_key: str, job_type: str) -> AgentJob | None:
        return await self.session.scalar(
            select(AgentJob)
            .where(
                AgentJob.workspace_id == self.workspace_id,
                AgentJob.subject_key == subject_key,
                AgentJob.job_type == job_type,
            )
            .order_by(AgentJob.id.desc())
            .limit(1)
        )

    async def plan_payload(self, plan: LearningPlan) -> dict:
        job = await self._latest_job(str(plan.public_id), "learning_plan_generation")
        return {
            "id": str(plan.public_id),
            "name": plan.name,
            "goal": plan.goal,
            "status": plan.status,
            "completed_lessons": plan.completed_lessons,
            "total_lessons": plan.total_lessons,
            "details": plan.details_markdown,
            "resources": list(plan.resources),
            "source": plan.source,
            "agent_job": self._job_payload(job),
            "created_at": plan.created_at.isoformat(),
            "updated_at": plan.updated_at.isoformat(),
            "deleted": plan.deleted_at is not None,
        }

    async def list_plans(self, include_deleted: bool = False) -> list[dict]:
        statement = select(LearningPlan).where(LearningPlan.workspace_id == self.workspace_id)
        if not include_deleted:
            statement = statement.where(LearningPlan.deleted_at.is_(None))
        plans = list((await self.session.scalars(statement.order_by(LearningPlan.updated_at.desc(), LearningPlan.id.desc()))).all())
        return [await self.plan_payload(item) for item in plans]

    async def _plan(self, public_id: uuid.UUID, include_deleted: bool = False) -> LearningPlan:
        statement = select(LearningPlan).where(
            LearningPlan.workspace_id == self.workspace_id,
            LearningPlan.public_id == public_id,
        )
        if not include_deleted:
            statement = statement.where(LearningPlan.deleted_at.is_(None))
        plan = await self.session.scalar(statement)
        if plan is None:
            raise KeyError(str(public_id))
        return plan

    async def get_plan(self, public_id: uuid.UUID, include_deleted: bool = False) -> dict:
        return await self.plan_payload(await self._plan(public_id, include_deleted=include_deleted))

    async def create_plan(self, name: str, goal: str, source: str) -> dict:
        plan = LearningPlan(
            workspace_id=self.workspace_id,
            name=" ".join(name.split()).strip(),
            goal=goal.strip(),
            status="waiting_for_hermes",
            details_markdown=(
                f"# {name.strip()}\n\n## 学习目标\n\n{goal.strip() or '等待补充'}\n\n"
                "## AI Agent 学习路径\n\n等待 AI Agent 生成并由你确认。"
            ),
            source=source,
        )
        self.session.add(plan)
        await self.session.flush()
        await enqueue_job(
            self.session,
            self.workspace_id,
            "learning_plan_generation",
            "learning_plan",
            str(plan.public_id),
            f"制定学习计划：{plan.name}",
            f"learning-plan:{plan.public_id}",
            {"plan_id": str(plan.public_id), "name": plan.name, "goal": plan.goal},
        )
        self.core._changed("growth.plan_created", "learning_plan", str(plan.public_id), "create_learning_plan")
        await self.session.flush()
        return await self.plan_payload(plan)

    async def update_plan(self, public_id: uuid.UUID, changes: dict) -> dict:
        plan = await self._plan(public_id)
        if "name" in changes and changes["name"] is not None:
            name = " ".join(str(changes["name"]).split()).strip()
            if not name:
                raise ValueError("学习计划名称不能为空")
            plan.name = name
            if plan.details_markdown:
                lines = plan.details_markdown.splitlines()
                if lines and lines[0].startswith("# "):
                    lines[0] = f"# {name}"
                    plan.details_markdown = "\n".join(lines)
        if "goal" in changes and changes["goal"] is not None:
            plan.goal = str(changes["goal"]).strip()
        if "status" in changes and changes["status"] is not None:
            status = str(changes["status"])
            if status not in {"waiting_for_hermes", "active", "paused", "completed"}:
                raise ValueError("不支持的学习计划状态")
            plan.status = status
        plan.updated_at = datetime.now(timezone.utc)
        self.core._changed("growth.plan_updated", "learning_plan", str(plan.public_id), "update_learning_plan")
        await self.session.flush()
        return await self.plan_payload(plan)

    async def set_plan_deleted(self, public_id: uuid.UUID, deleted: bool) -> dict:
        plan = await self._plan(public_id, include_deleted=True)
        if deleted and plan.deleted_at is not None:
            raise KeyError(str(public_id))
        plan.deleted_at = datetime.now(timezone.utc) if deleted else None
        plan.updated_at = datetime.now(timezone.utc)
        event = "growth.plan_deleted" if deleted else "growth.plan_restored"
        action = "delete_learning_plan" if deleted else "restore_learning_plan"
        self.core._changed(event, "learning_plan", str(plan.public_id), action)
        await self.session.flush()
        return await self.plan_payload(plan)

    async def update_generated_plan(
        self,
        public_id: uuid.UUID,
        roadmap_markdown: str,
        status: str,
        total_lessons: int,
        completed_lessons: int,
        resources: list[dict],
    ) -> dict:
        plan = await self._plan(public_id)
        plan.status = status
        plan.total_lessons = total_lessons
        plan.completed_lessons = min(completed_lessons, total_lessons or completed_lessons)
        plan.details_markdown = f"# {plan.name}\n\n{roadmap_markdown.strip()}"
        plan.resources = resources
        plan.updated_at = datetime.now(timezone.utc)
        self.core._changed("growth.plan_generated", "learning_plan", str(plan.public_id), "update_learning_plan")
        await self.session.flush()
        return await self.plan_payload(plan)

    async def update_plan_progress(
        self,
        public_id: uuid.UUID,
        completed_lessons: int,
        status: str | None,
    ) -> dict:
        plan = await self._plan(public_id)
        plan.completed_lessons = min(completed_lessons, plan.total_lessons or completed_lessons)
        if status:
            plan.status = status
        elif plan.total_lessons and plan.completed_lessons >= plan.total_lessons:
            plan.status = "completed"
        elif plan.status == "completed":
            plan.status = "active"
        plan.updated_at = datetime.now(timezone.utc)
        self.core._changed("growth.plan_progress_updated", "learning_plan", str(plan.public_id), "update_learning_progress")
        await self.session.flush()
        return await self.plan_payload(plan)

    @staticmethod
    def library_payload(item: LibraryItem) -> dict:
        details = (
            f"# {item.title}\n\n## 推荐理由\n\n{item.reason}\n\n"
            f"## 当前进度\n\n{item.current_position}\n\n## 我的心得\n\n{item.reflection}\n\n"
            f"## AI Agent 意见\n\n{item.agent_comment}\n\n## 整理后的笔记\n\n{item.organized_notes}"
        )
        return {
            "id": str(item.public_id),
            "title": item.title,
            "kind": item.kind,
            "status": item.status,
            "progress_percent": item.progress_percent,
            "current_position": item.current_position,
            "reason": item.reason,
            "reflection": item.reflection,
            "agent_comment": item.agent_comment,
            "organized_notes": item.organized_notes,
            "source": item.source,
            "details": details,
            "updated_at": item.updated_at.isoformat(),
            "deleted": item.deleted_at is not None,
        }

    async def list_library(self, include_deleted: bool = False) -> list[dict]:
        statement = select(LibraryItem).where(LibraryItem.workspace_id == self.workspace_id)
        if not include_deleted:
            statement = statement.where(LibraryItem.deleted_at.is_(None))
        items = list((await self.session.scalars(statement.order_by(LibraryItem.updated_at.desc(), LibraryItem.id.desc()))).all())
        return [self.library_payload(item) for item in items]

    async def get_library_item(self, public_id: uuid.UUID, include_deleted: bool = False) -> dict:
        statement = select(LibraryItem).where(
            LibraryItem.workspace_id == self.workspace_id,
            LibraryItem.public_id == public_id,
        )
        if not include_deleted:
            statement = statement.where(LibraryItem.deleted_at.is_(None))
        item = await self.session.scalar(statement)
        if item is None:
            raise KeyError(str(public_id))
        return self.library_payload(item)

    async def create_library_item(
        self, title: str, kind: str, reason: str, source: str, status: str = "want"
    ) -> dict:
        item = LibraryItem(
            workspace_id=self.workspace_id,
            title=" ".join(title.split()).strip(),
            kind=kind,
            status=status,
            reason=reason.strip(),
            source=source,
        )
        self.session.add(item)
        await self.session.flush()
        self.core._changed("library.item_created", "library_item", str(item.public_id), "create_library_item")
        return self.library_payload(item)

    async def update_library_item(self, public_id: uuid.UUID, changes: dict) -> dict:
        item = await self.session.scalar(
            select(LibraryItem).where(
                LibraryItem.workspace_id == self.workspace_id,
                LibraryItem.public_id == public_id,
                LibraryItem.deleted_at.is_(None),
            )
        )
        if item is None:
            raise KeyError(str(public_id))
        reflection_changed = False
        for key, value in changes.items():
            if value is None:
                continue
            if key == "reflection" and value.strip() and value.strip() != item.reflection:
                reflection_changed = True
            setattr(item, key, value.strip() if isinstance(value, str) else value)
        if item.progress_percent >= 100:
            item.status = "done"
        elif item.progress_percent > 0 and item.status == "want":
            item.status = "in_progress"
        item.updated_at = datetime.now(timezone.utc)
        if reflection_changed and self.actor_type == "user":
            await enqueue_job(
                self.session,
                self.workspace_id,
                "library_discussion",
                "library_item",
                str(item.public_id),
                f"回应并整理：{item.title}",
                f"library-discussion:{item.public_id}:{item.updated_at.isoformat()}",
                {
                    "library_item_id": str(item.public_id),
                    "title": item.title,
                    "reflection": item.reflection,
                    "current_position": item.current_position,
                },
            )
        self.core._changed("library.item_updated", "library_item", str(item.public_id), "update_library_item")
        await self.session.flush()
        return self.library_payload(item)

    @staticmethod
    def content_payload(item: ContentItem) -> dict:
        return {
            "id": str(item.public_id),
            "category": item.category,
            "title": item.title,
            "summary": item.summary,
            "details": item.details_markdown,
            "source_url": item.source_url or "",
            "media_url": item.media_url,
            "thumbnail_url": item.thumbnail_url,
            "platform": item.platform,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "updated_at": item.updated_at.isoformat(),
            "deleted": item.deleted_at is not None,
        }

    async def list_content(self, limit_per_category: int = 12) -> dict[str, list[dict]]:
        result = {"video_trend": [], "ai_news": [], "topic_idea": []}
        for category in result:
            items = list(
                (
                    await self.session.scalars(
                        select(ContentItem)
                        .where(
                            ContentItem.workspace_id == self.workspace_id,
                            ContentItem.category == category,
                            ContentItem.deleted_at.is_(None),
                        )
                        .order_by(ContentItem.published_at.desc().nullslast(), ContentItem.updated_at.desc(), ContentItem.id.desc())
                        .limit(limit_per_category)
                    )
                ).all()
            )
            result[category] = [self.content_payload(item) for item in items]
        return result

    async def get_content_item(self, public_id: uuid.UUID) -> dict:
        item = await self.session.scalar(
            select(ContentItem).where(
                ContentItem.workspace_id == self.workspace_id,
                ContentItem.public_id == public_id,
                ContentItem.deleted_at.is_(None),
            )
        )
        if item is None:
            raise KeyError(str(public_id))
        return self.content_payload(item)

    async def save_content_item(
        self,
        *,
        title: str,
        category: str,
        source_url: str | None,
        summary: str,
        details_markdown: str,
        media_url: str | None,
        thumbnail_url: str | None,
        platform: str,
        published_at: datetime | None,
        source: str,
    ) -> dict:
        item = None
        if source_url:
            item = await self.session.scalar(
                select(ContentItem).where(
                    ContentItem.workspace_id == self.workspace_id,
                    ContentItem.category == category,
                    ContentItem.source_url == source_url,
                )
            )
        if item is None:
            item = ContentItem(
                workspace_id=self.workspace_id,
                title=title.strip(),
                category=category,
                source_url=source_url,
            )
            self.session.add(item)
        item.title = title.strip()
        item.category = category
        item.summary = summary.strip()
        item.details_markdown = details_markdown.strip() or summary.strip()
        item.media_url = media_url or ""
        item.thumbnail_url = thumbnail_url or ""
        item.platform = platform.strip()
        item.published_at = published_at
        item.source = source
        item.deleted_at = None
        item.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        self.core._changed("content.item_saved", "content_item", str(item.public_id), "save_content_item")
        return self.content_payload(item)
