import enum
from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TaskStatus(enum.StrEnum):
    OPEN = "open"
    DONE = "done"
    CANCELLED = "cancelled"


class GoalStatus(enum.StrEnum):
    ACTIVE = "active"
    ACHIEVED = "achieved"
    ABANDONED = "abandoned"


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    profile: Mapped["UserProfile | None"] = relationship(back_populates="user")


class UserProfile(Base):
    __tablename__ = "user_profiles"
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    timezone: Mapped[str] = mapped_column(String(64))
    planning_minutes: Mapped[int | None] = mapped_column(Integer)
    age: Mapped[int | None] = mapped_column(Integer)
    occupation: Mapped[str | None] = mapped_column(String(200))
    onboarding_complete: Mapped[bool] = mapped_column(default=False)
    user: Mapped[User] = relationship(back_populates="profile")


class AuditMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Task(AuditMixin, Base):
    __tablename__ = "tasks"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, native_enum=False), default=TaskStatus.OPEN
    )
    source: Mapped[str] = mapped_column(String(16))
    extraction_confidence: Mapped[float] = mapped_column(Float)
    needs_review: Mapped[bool] = mapped_column(default=False)


class Goal(AuditMixin, Base):
    __tablename__ = "goals"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    status: Mapped[GoalStatus] = mapped_column(
        Enum(GoalStatus, native_enum=False), default=GoalStatus.ACTIVE
    )


class AnalysisReport(Base):
    __tablename__ = "analysis_reports"
    __table_args__ = (UniqueConstraint("user_id", "kind", "period_key"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    period_key: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        Index(
            "uq_active_subscription", "user_id", unique=True, postgresql_where="status = 'active'"
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    telegram_charge_id: Mapped[str] = mapped_column(String(255), unique=True)
    status: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaymentEvent(Base):
    __tablename__ = "payment_events"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    telegram_event_id: Mapped[str] = mapped_column(String(255), unique=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    event_type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VoiceUsageEvent(Base):
    __tablename__ = "voice_usage_events"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    reservation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), unique=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    local_date: Mapped[date] = mapped_column(Date)
    outcome: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutboxJob(Base):
    __tablename__ = "outbox_jobs"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    routing_key: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(Text)


class ProcessedMessage(Base):
    __tablename__ = "processed_messages"
    consumer: Mapped[str] = mapped_column(String(64), primary_key=True)
    message_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
