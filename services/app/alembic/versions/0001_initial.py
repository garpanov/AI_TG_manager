"""Initial persistent model."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def audit_columns():
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "user_profiles",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("planning_minutes", sa.Integer()),
        sa.Column("age", sa.Integer()),
        sa.Column("occupation", sa.String(200)),
        sa.Column("onboarding_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("deadline", sa.DateTime(timezone=True)),
        sa.Column("priority", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("extraction_confidence", sa.Float(), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        *audit_columns(),
    )
    op.create_index("ix_tasks_user_id", "tasks", ["user_id"])
    op.create_index("ix_tasks_deadline", "tasks", ["deadline"])
    op.create_table(
        "goals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("deadline", sa.DateTime(timezone=True)),
        sa.Column("priority", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        *audit_columns(),
    )
    op.create_index("ix_goals_user_id", "goals", ["user_id"])
    op.create_table(
        "analysis_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("period_key", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "kind", "period_key"),
    )
    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("telegram_charge_id", sa.String(255), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])
    op.create_index(
        "uq_active_subscription",
        "subscriptions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "payment_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("telegram_event_id", sa.String(255), nullable=False, unique=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_payment_events_user_id", "payment_events", ["user_id"])
    op.create_table(
        "voice_usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("reservation_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_voice_usage_events_user_id", "voice_usage_events", ["user_id"])
    op.create_table(
        "outbox_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("routing_key", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
    )
    op.create_index("ix_outbox_jobs_routing_key", "outbox_jobs", ["routing_key"])
    op.create_index("ix_outbox_jobs_published_at", "outbox_jobs", ["published_at"])
    op.create_table(
        "processed_messages",
        sa.Column("consumer", sa.String(64), primary_key=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "processed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    for table in [
        "processed_messages",
        "outbox_jobs",
        "voice_usage_events",
        "payment_events",
        "subscriptions",
        "analysis_reports",
        "goals",
        "tasks",
        "user_profiles",
        "users",
    ]:
        op.drop_table(table)
