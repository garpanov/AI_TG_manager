from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MessageSource(StrEnum):
    TEXT = "text"
    VOICE = "voice"


class ActiveTask(Contract):
    id: UUID
    title: str
    deadline: datetime | None = None


class AnalysisKind(StrEnum):
    INITIAL = "initial"
    DAY_3 = "day_3"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


class TranscriptionRequest(Contract):
    version: Literal[1] = 1
    job_id: UUID
    user_id: int
    chat_id: int
    telegram_message_id: int
    reservation_id: UUID
    quota_key: str | None = None
    local_date: str
    timezone: str | None = None
    local_datetime: datetime | None = None
    active_tasks: list[ActiveTask] = Field(default_factory=list)
    audio_file: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]+$")]
    created_at: datetime


class TranscriptionFailed(Contract):
    version: Literal[1] = 1
    job_id: UUID
    user_id: int
    chat_id: int
    reservation_id: UUID
    quota_key: str | None = None
    local_date: str
    reason: Literal["infrastructure", "transcription"]
    created_at: datetime


class AIRequest(Contract):
    version: Literal[1] = 1
    job_id: UUID
    user_id: int
    chat_id: int
    telegram_message_id: int
    source: MessageSource
    text: str
    timezone: str | None = None
    local_datetime: datetime | None = None
    active_tasks: list[ActiveTask] = Field(default_factory=list)
    created_at: datetime


class AnalysisRequest(Contract):
    version: Literal[1] = 1
    job_id: UUID
    user_id: int
    chat_id: int
    kind: AnalysisKind
    period_key: str
    context: dict
    created_at: datetime


class AnalysisResult(Contract):
    version: Literal[1] = 1
    job_id: UUID
    user_id: int
    chat_id: int
    kind: AnalysisKind
    period_key: str
    content: str
    created_at: datetime


class TaskCandidate(Contract):
    title: str
    notes: str | None = None
    deadline: datetime | None = None
    priority: Literal["low", "normal", "high"] = "normal"
    confidence: float = Field(ge=0, le=1)
    review_fields: list[str] = Field(default_factory=list)


class GoalCandidate(Contract):
    title: str
    description: str | None = None
    deadline: datetime | None = None
    priority: Literal["low", "normal", "high"] = "normal"
    confidence: float = Field(ge=0, le=1)
    review_fields: list[str] = Field(default_factory=list)


class TaskDeletionCandidate(Contract):
    title: str = Field(min_length=1, max_length=500)


class TaskAction(Contract):
    task_id: UUID | None = None
    matched_title: str | None = Field(default=None, max_length=500)
    action: Literal["delete", "complete"]


class Classification(Contract):
    cleaned_text: str
    tasks: list[TaskCandidate] = Field(default_factory=list)
    goals: list[GoalCandidate] = Field(default_factory=list)
    task_deletions: list[TaskDeletionCandidate] = Field(default_factory=list)
    task_actions: list[TaskAction] = Field(default_factory=list)
    contains_plan: bool = False
    unsupported: bool = False
    clarification: str | None = None


class AIResult(Contract):
    version: Literal[1] = 1
    job_id: UUID
    user_id: int
    chat_id: int
    telegram_message_id: int
    source: MessageSource
    classification: Classification
    created_at: datetime
