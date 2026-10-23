from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ai_manager_contracts import ActiveTask, AIRequest, MessageSource, TranscriptionRequest
from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)
from redis.asyncio import Redis
from sqlalchemy import select

from .config import get_settings
from .db import session_factory
from .models import (
    Goal,
    GoalStatus,
    OutboxJob,
    PaymentEvent,
    Subscription,
    Task,
    TaskStatus,
    User,
    UserProfile,
)
from .pinning import pin_with_fallback
from .quota import refund_voice, reserve_voice
from .rabbit import AI_REQUEST, TRANSCRIPTION_REQUEST

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)


def user_zone(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def local_day_bounds(
    timezone: str, now: datetime | None = None
) -> tuple[datetime, datetime, datetime]:
    """Return UTC boundaries for today, tomorrow, and the day after tomorrow."""
    zone = user_zone(timezone)
    local_now = (now or datetime.now(UTC)).astimezone(zone)
    today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    day_after_tomorrow = tomorrow + timedelta(days=1)
    return today.astimezone(UTC), tomorrow.astimezone(UTC), day_after_tomorrow.astimezone(UTC)


def start_of_next_week(timezone: str, now: datetime | None = None) -> datetime:
    zone = user_zone(timezone)
    local_now = (now or datetime.now(UTC)).astimezone(zone)
    today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    next_monday = today + timedelta(days=7 - today.weekday())
    return next_monday.astimezone(UTC)


async def ensure_user(message: Message) -> tuple[User, UserProfile]:
    async with session_factory() as session, session.begin():
        user = await session.get(User, message.from_user.id)
        if user is None:
            user = User(id=message.from_user.id, chat_id=message.chat.id)
            session.add(user)
            await session.flush()
        profile = await session.get(UserProfile, user.id)
        if profile is None:
            profile = UserProfile(
                user_id=user.id, timezone="UTC", planning_minutes=None, age=None, occupation=None
            )
            session.add(profile)
        await session.flush()
        return user, profile


async def get_active_tasks(user_id: int) -> list[ActiveTask]:
    async with session_factory() as session:
        tasks = list(
            await session.scalars(
                select(Task)
                .where(Task.user_id == user_id, Task.status == TaskStatus.OPEN)
                .order_by(Task.created_at)
            )
        )
    return [ActiveTask(id=task.id, title=task.title, deadline=task.deadline) for task in tasks]


@router.message(CommandStart())
async def start(message: Message) -> None:
    await ensure_user(message)
    await message.answer(
        "Welcome. Send tasks, goals, or plans in text or voice. "
        "Your timezone is UTC until onboarding is completed."
    )


@router.message(Command("tasks"))
async def tasks(message: Message) -> None:
    _user, profile = await ensure_user(message)
    today, tomorrow, _day_after_tomorrow = local_day_bounds(profile.timezone)
    async with session_factory() as session:
        rows = list(
            await session.scalars(
                select(Task)
                .where(
                    Task.user_id == message.from_user.id,
                    Task.status == TaskStatus.OPEN,
                    Task.deadline >= today,
                    Task.deadline < tomorrow,
                )
                .order_by(Task.deadline.nulls_last(), Task.created_at)
            )
        )
    text = "\n".join(f"• {item.title}" for item in rows) or "No tasks are due today."
    await message.answer(text)


@router.message(Command("calendar"))
async def calendar(message: Message) -> None:
    _user, profile = await ensure_user(message)
    _today, tomorrow, day_after_tomorrow = local_day_bounds(profile.timezone)
    next_week = start_of_next_week(profile.timezone)
    async with session_factory() as session:
        rows = list(
            await session.scalars(
                select(Task)
                .where(
                    Task.user_id == message.from_user.id,
                    Task.status == TaskStatus.OPEN,
                    Task.deadline.is_not(None),
                    Task.deadline >= tomorrow,
                )
                .order_by(Task.deadline)
            )
        )
    tomorrow_rows = [item for item in rows if item.deadline < day_after_tomorrow]
    week_rows = [item for item in rows if day_after_tomorrow <= item.deadline < next_week]
    later_start = max(day_after_tomorrow, next_week)
    later_rows = [item for item in rows if item.deadline >= later_start]
    sections = []
    for heading, items in (
        ("📅 Tomorrow", tomorrow_rows),
        ("📆 This week", week_rows),
        ("🗓 Later", later_rows),
    ):
        if items:
            sections.append(f"{heading}\n" + "\n".join(f"• {item.title}" for item in items))
    await message.answer("\n\n".join(sections) or "There are no upcoming tasks.")


@router.message(Command("goals"))
async def goals(message: Message) -> None:
    await ensure_user(message)
    async with session_factory() as session:
        rows = list(
            await session.scalars(
                select(Goal)
                .where(Goal.user_id == message.from_user.id, Goal.status == GoalStatus.ACTIVE)
                .order_by(Goal.created_at)
            )
        )
    await message.answer("\n".join(f"• {item.title}" for item in rows) or "No active goals.")


@router.message(Command("subscribe"))
async def subscribe(message: Message, bot: Bot) -> None:
    settings = get_settings()
    invoice_url = await bot.create_invoice_link(
        title="AI Manager subscription",
        description="30 days of paid voice allowance",
        payload=f"subscription:{message.from_user.id}",
        currency="XTR",
        prices=[LabeledPrice(label="30 days", amount=settings.stars_price)],
        subscription_period=2_592_000,
    )
    await message.answer(
        "Subscribe for 30 days:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"Subscribe for {settings.stars_price} ⭐", url=invoice_url
                    )
                ]
            ]
        ),
    )


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery) -> None:
    expected = f"subscription:{query.from_user.id}"
    await query.answer(
        ok=query.invoice_payload == expected,
        error_message="Invalid subscription request."
        if query.invoice_payload != expected
        else None,
    )


@router.message(F.successful_payment)
async def successful_payment(message: Message) -> None:
    payment = message.successful_payment
    expires_at = payment.subscription_expiration_date or (datetime.now(UTC) + timedelta(days=30))
    event_id = payment.telegram_payment_charge_id
    async with session_factory() as session, session.begin():
        if await session.scalar(
            select(PaymentEvent.id).where(PaymentEvent.telegram_event_id == event_id)
        ):
            return
        session.add(
            PaymentEvent(
                telegram_event_id=event_id,
                user_id=message.from_user.id,
                event_type="successful_payment",
                payload=payment.model_dump(mode="json"),
            )
        )
        subscription = await session.scalar(
            select(Subscription)
            .where(Subscription.user_id == message.from_user.id, Subscription.status == "active")
            .with_for_update()
        )
        if subscription:
            subscription.telegram_charge_id = event_id
            subscription.expires_at = expires_at
        else:
            session.add(
                Subscription(
                    user_id=message.from_user.id,
                    telegram_charge_id=event_id,
                    status="active",
                    expires_at=expires_at,
                )
            )
    await message.answer("Payment received. Your subscription is active.")


@router.message(F.forward_origin)
async def forwarded(message: Message, bot: Bot) -> None:
    await pin_with_fallback(bot, message)


@router.message(F.photo | F.video)
async def visual_plan(message: Message, bot: Bot) -> None:
    await pin_with_fallback(bot, message)


@router.message(F.voice)
async def voice(message: Message, bot: Bot, redis: Redis) -> None:
    settings = get_settings()
    if message.voice.duration > 30:
        await message.answer("Voice messages can be up to 30 seconds.")
        return
    user, profile = await ensure_user(message)
    reservation = None
    path: Path | None = None
    try:
        async with session_factory() as session, session.begin():
            managed_user = await session.get(User, user.id)
            reservation = await reserve_voice(
                redis, session, managed_user, profile.timezone, settings.voice_whitelist
            )
            if reservation is None:
                await message.answer("You've reached today's voice limit.")
                return

            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            filename = f"{timestamp}_{user.id}_{uuid4().hex}.ogg"
            settings.voice_directory.mkdir(parents=True, exist_ok=True)
            path = settings.voice_directory / filename
            await bot.download(message.voice, destination=path)
            job_id = uuid4()
            request = TranscriptionRequest(
                job_id=job_id,
                user_id=user.id,
                chat_id=message.chat.id,
                telegram_message_id=message.message_id,
                audio_file=filename,
                reservation_id=reservation.id,
                quota_key=reservation.key,
                local_date=reservation.local_date.isoformat(),
                timezone=profile.timezone,
                local_datetime=datetime.now(UTC).astimezone(user_zone(profile.timezone)),
                active_tasks=await get_active_tasks(user.id),
                created_at=datetime.now(UTC),
            )
            session.add(
                OutboxJob(
                    id=job_id,
                    routing_key=TRANSCRIPTION_REQUEST,
                    payload=request.model_dump(mode="json"),
                )
            )
        await message.answer("Voice received. I'll process it shortly.")
    except Exception:
        if path:
            path.unlink(missing_ok=True)
        if reservation:
            async with session_factory() as session, session.begin():
                await refund_voice(redis, session, reservation, user.id)
        raise


@router.message(F.text.startswith("/"))
async def unknown_command(message: Message) -> None:
    await message.answer("Supported commands: /tasks, /calendar, /goals, /subscribe.")


@router.message(F.text)
async def text(message: Message) -> None:
    user, profile = await ensure_user(message)
    job_id = uuid4()
    request = AIRequest(
        job_id=job_id,
        user_id=user.id,
        chat_id=message.chat.id,
        telegram_message_id=message.message_id,
        source=MessageSource.TEXT,
        text=message.text,
        timezone=profile.timezone,
        local_datetime=datetime.now(UTC).astimezone(user_zone(profile.timezone)),
        active_tasks=await get_active_tasks(user.id),
        created_at=datetime.now(UTC),
    )
    async with session_factory() as session, session.begin():
        session.add(
            OutboxJob(id=job_id, routing_key=AI_REQUEST, payload=request.model_dump(mode="json"))
        )
    await message.answer("Got it — I'll process that shortly.")


@router.message()
async def unsupported(message: Message) -> None:
    await message.answer("Please send text, a voice message, photo, video, or forwarded plan.")
