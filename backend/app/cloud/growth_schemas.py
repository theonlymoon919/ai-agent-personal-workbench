from __future__ import annotations

from datetime import datetime
import re
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


class LearningResource(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    url: HttpUrl
    resource_type: Literal["video", "article", "course", "tool"] = "article"
    platform: str = Field(default="", max_length=80)
    note: str = Field(default="", max_length=1000)
    published_at: datetime | None = None
    verified_at: datetime | None = None
    search_keywords: list[str] = Field(default_factory=list, max_length=12)
    relevance_reason: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_bilibili_resource(self) -> "LearningResource":
        host = str(self.url.host or "").lower()
        if host == "bilibili.com" or host.endswith(".bilibili.com"):
            if not re.fullmatch(r"/video/BV[0-9A-Za-z]+/?", self.url.path or ""):
                raise ValueError("B 站学习资源必须使用可定位具体视频的规范 BV 地址")
            if self.published_at is None:
                raise ValueError("B 站学习资源必须填写视频发布时间")
            if self.verified_at is None:
                raise ValueError("B 站学习资源必须填写最近验证时间")
            if not self.search_keywords:
                raise ValueError("B 站学习资源必须填写实际使用的搜索关键词")
            if not self.relevance_reason.strip():
                raise ValueError("B 站学习资源必须说明与学习目标的具体匹配点")
        return self


class LearningPlanGeneratedUpdate(BaseModel):
    roadmap_markdown: str = Field(min_length=1, max_length=50000)
    status: Literal["waiting_for_hermes", "active", "paused", "completed"] = "active"
    total_lessons: int = Field(default=0, ge=0, le=10000)
    completed_lessons: int = Field(default=0, ge=0, le=10000)
    resources: list[LearningResource] = Field(default_factory=list, max_length=100)


class ContentItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    category: Literal["video_trend", "ai_news", "topic_idea"]
    source_url: HttpUrl | None = None
    summary: str = Field(default="", max_length=5000)
    details_markdown: str = Field(default="", max_length=50000)
    media_url: HttpUrl | None = None
    thumbnail_url: HttpUrl | None = None
    platform: str = Field(default="", max_length=80)
    published_at: datetime | None = None
