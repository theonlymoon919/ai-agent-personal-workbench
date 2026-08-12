from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


Quadrant = Literal["important_urgent", "important_not_urgent", "not_important_urgent", "not_important_not_urgent"]
TaskRecurrence = Literal["none", "yearly"]
TaskStatus = Literal["planned", "in_progress", "blocked", "completed", "cancelled"]
ProjectStatus = Literal["active", "paused", "completed"]


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    quadrant: Quadrant = "important_not_urgent"
    due_at: datetime | None = None
    note: str = Field(default="", max_length=4000)
    recurrence: TaskRecurrence = "none"
    project_id: UUID | None = None
    phase_id: UUID | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: TaskStatus = "planned"
    progress_percent: int = Field(default=0, ge=0, le=100)
    is_milestone: bool = False
    order_index: int = Field(default=0, ge=0, le=100000)
    predecessor_ids: list[UUID] = Field(default_factory=list, max_length=50)


class TaskUpdate(BaseModel):
    done: bool | None = None
    title: str | None = Field(default=None, min_length=1, max_length=160)
    quadrant: Quadrant | None = None
    due_at: datetime | None = None
    note: str | None = Field(default=None, max_length=4000)
    recurrence: TaskRecurrence | None = None
    occurrence_date: date | None = None
    project_id: UUID | None = None
    phase_id: UUID | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: TaskStatus | None = None
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    is_milestone: bool | None = None
    order_index: int | None = Field(default=None, ge=0, le=100000)
    predecessor_ids: list[UUID] | None = Field(default=None, max_length=50)


class HealthRecordUpdate(BaseModel):
    record_date: date | None = None
    meal_slot: Literal["breakfast", "lunch", "afternoon_tea", "dinner", "snack", "late_night"] | None = None


class BackupCreate(BaseModel):
    label: str = Field(default="manual", max_length=40)


class StartupUpdate(BaseModel):
    enabled: bool


class WaterRecord(BaseModel):
    ml: int = Field(gt=0, le=3000)


class WeightRecord(BaseModel):
    kg: float = Field(gt=20, le=400)


class LearningPlanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    goal: str = Field(default="", max_length=1000)


class LearningPlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    goal: str | None = Field(default=None, max_length=1000)
    status: Literal["waiting_for_hermes", "active", "paused", "completed"] | None = None


class LearningPlanProgressUpdate(BaseModel):
    completed_lessons: int = Field(ge=0, le=10000)
    status: Literal["waiting_for_hermes", "active", "paused", "completed"] | None = None


class AgentSuggestionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=8000)
    action_label: str = Field(default="", max_length=60)


class HealthAnalysisCreate(BaseModel):
    summary: str = Field(min_length=1, max_length=8000)
    advice: str = Field(default="", max_length=4000)
    calories_kcal: int | None = Field(default=None, ge=0, le=10000)
    exercise_kcal: int | None = Field(default=None, ge=0, le=10000)
    weight_kg: float | None = Field(default=None, gt=20, le=400)


class LibraryItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    kind: Literal["book", "movie", "documentary"]
    reason: str = Field(default="", max_length=4000)


class LibraryItemUpdate(BaseModel):
    status: Literal["want", "in_progress", "done"] | None = None
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    current_position: str | None = Field(default=None, max_length=240)
    reflection: str | None = Field(default=None, max_length=12000)
    agent_comment: str | None = Field(default=None, max_length=8000)
    organized_notes: str | None = Field(default=None, max_length=20000)


class ProfileSettingsUpdate(BaseModel):
    nickname: str = Field(min_length=1, max_length=30)
    daily_message_style: Literal["mixed", "encouraging", "comforting"] = "mixed"


class HealthGoalsUpdate(BaseModel):
    gender: Literal["female", "male"]
    height_cm: float = Field(ge=120, le=230)
    current_weight_kg: float = Field(gt=20, le=400)
    target_weight_kg: float = Field(gt=20, le=400)
    cup_ml: int = Field(default=250, ge=50, le=2000)
    age: int | None = Field(default=None, ge=18, le=100)
    activity_level: Literal["sedentary", "light", "moderate", "active"] | None = None


class IPPreferencesUpdate(BaseModel):
    video_topics: list[str] = Field(default_factory=list, max_length=20)
    ai_topics: list[str] = Field(default_factory=list, max_length=20)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    current_stage: str = Field(default="准备中", max_length=200)
    progress_percent: int = Field(default=0, ge=0, le=100)
    next_milestone: str = Field(default="", max_length=500)
    start_date: date | None = None
    due_date: date | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    current_stage: str | None = Field(default=None, max_length=200)
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    next_milestone: str | None = Field(default=None, max_length=500)
    start_date: date | None = None
    due_date: date | None = None
    status: ProjectStatus | None = None


class ProjectPhaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    start_date: date | None = None
    end_date: date | None = None
    status: ProjectStatus = "active"
    order_index: int = Field(default=0, ge=0, le=100000)


class ProjectPhaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    start_date: date | None = None
    end_date: date | None = None
    status: ProjectStatus | None = None
    order_index: int | None = Field(default=None, ge=0, le=100000)


class DailyMessageCreate(BaseModel):
    message: str = Field(min_length=1, max_length=120)
    tone: Literal["encouraging", "comforting", "mixed"] = "mixed"


class DailyHealthAdviceCreate(BaseModel):
    summary: str = Field(default="", max_length=8000)
    overall_summary: str = Field(default="", max_length=3000)
    diet_summary: str = Field(default="", max_length=3000)
    hydration_summary: str = Field(default="", max_length=2000)
    exercise_summary: str = Field(default="", max_length=3000)
    status: Literal["on_track", "attention", "celebrate", "neutral"] = "neutral"
