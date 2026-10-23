import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from ai_manager_contracts import AnalysisKind, AnalysisRequest
from sqlalchemy import select

from .db import session_factory
from .models import AnalysisReport, Goal, OutboxJob, Task, User, UserProfile
from .outbox import run_publisher
from .rabbit import ANALYSIS_REQUEST


def due_analysis(local: datetime, registered_local: datetime) -> list[tuple[AnalysisKind, str]]:
    if local.hour != 8:
        return []
    due: list[tuple[AnalysisKind, str]] = []
    if local.date() == (registered_local + timedelta(days=3)).date():
        due.append((AnalysisKind.DAY_3, local.date().isoformat()))
    if local.weekday() == 0:
        previous_week = (local.date() - timedelta(days=7)).isocalendar()
        due.append((AnalysisKind.WEEKLY, f"{previous_week.year}-W{previous_week.week:02d}"))
    if local.day == 1:
        previous_month = (local.replace(day=1) - timedelta(days=1)).date()
        due.append((AnalysisKind.MONTHLY, previous_month.strftime("%Y-%m")))
    if local.month == 1 and local.day == 1:
        due.append((AnalysisKind.YEARLY, str(local.year - 1)))
    return due


async def enqueue_due() -> None:
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        users = (await session.execute(select(User, UserProfile).join(UserProfile))).all()
        for user, profile in users:
            local = now.astimezone(ZoneInfo(profile.timezone))
            registered = user.registered_at.astimezone(ZoneInfo(profile.timezone))
            for kind, period_key in due_analysis(local, registered):
                exists = await session.scalar(
                    select(AnalysisReport.id).where(
                        AnalysisReport.user_id == user.id,
                        AnalysisReport.kind == kind.value,
                        AnalysisReport.period_key == period_key,
                    )
                )
                queued = await session.scalar(
                    select(OutboxJob.id).where(
                        OutboxJob.routing_key == ANALYSIS_REQUEST,
                        OutboxJob.payload["user_id"].astext == str(user.id),
                        OutboxJob.payload["kind"].astext == kind.value,
                        OutboxJob.payload["period_key"].astext == period_key,
                    )
                )
                if exists or queued:
                    continue
                tasks = list(await session.scalars(select(Task).where(Task.user_id == user.id)))
                goals = list(await session.scalars(select(Goal).where(Goal.user_id == user.id)))
                context = {
                    "profile": {
                        "planning_minutes": profile.planning_minutes,
                        "age": profile.age,
                        "occupation": profile.occupation,
                    },
                    "tasks": [
                        {
                            "title": task.title,
                            "status": task.status.value,
                            "deadline": task.deadline.isoformat() if task.deadline else None,
                        }
                        for task in tasks
                    ],
                    "goals": [
                        {
                            "title": goal.title,
                            "status": goal.status.value,
                            "deadline": goal.deadline.isoformat() if goal.deadline else None,
                        }
                        for goal in goals
                    ],
                }
                job_id = uuid4()
                request = AnalysisRequest(
                    job_id=job_id,
                    user_id=user.id,
                    chat_id=user.chat_id,
                    kind=kind,
                    period_key=period_key,
                    context=context,
                    created_at=now,
                )
                session.add(
                    OutboxJob(
                        id=job_id,
                        routing_key=ANALYSIS_REQUEST,
                        payload=request.model_dump(mode="json"),
                    )
                )


async def scheduler_loop() -> None:
    while True:
        await enqueue_due()
        await asyncio.sleep(60)


async def main() -> None:
    async with asyncio.TaskGroup() as group:
        group.create_task(run_publisher())
        group.create_task(scheduler_loop())


def run() -> None:
    asyncio.run(main())
