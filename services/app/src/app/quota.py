from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Subscription, User, VoiceUsageEvent

RESERVE_SCRIPT = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
if current >= tonumber(ARGV[1]) then return 0 end
redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], ARGV[2])
return 1
"""


@dataclass(frozen=True)
class Reservation:
    id: UUID
    key: str | None
    local_date: date


async def reserve_voice(
    redis: Redis,
    session: AsyncSession,
    user: User,
    timezone: str,
    whitelist: frozenset[int],
) -> Reservation | None:
    now = datetime.now(UTC)
    local_now = now.astimezone(ZoneInfo(timezone))
    reservation_id = uuid4()
    if user.id in whitelist:
        reservation = Reservation(reservation_id, None, local_now.date())
    else:
        paid = await session.scalar(
            select(Subscription.id).where(
                Subscription.user_id == user.id,
                Subscription.status == "active",
                Subscription.expires_at > now,
            )
        )
        limit = (
            20
            if paid
            else (
                5
                if user.registered_at.astimezone(ZoneInfo(timezone)).date() == local_now.date()
                else 3
            )
        )
        key = f"voice-quota:{user.id}:{local_now.date().isoformat()}"
        seconds_to_expiry = (
            int((local_now.replace(hour=23, minute=59, second=59) - local_now).total_seconds())
            + 3601
        )
        accepted = await redis.eval(RESERVE_SCRIPT, 1, key, limit, seconds_to_expiry)
        if not accepted:
            return None
        reservation = Reservation(reservation_id, key, local_now.date())
    session.add(
        VoiceUsageEvent(
            reservation_id=reservation.id,
            user_id=user.id,
            local_date=reservation.local_date,
            outcome="reserved",
        )
    )
    return reservation


async def refund_voice(
    redis: Redis, session: AsyncSession, reservation: Reservation, user_id: int
) -> None:
    if reservation.key:
        await redis.decr(reservation.key)
    session.add(
        VoiceUsageEvent(
            reservation_id=uuid4(),
            user_id=user_id,
            local_date=reservation.local_date,
            outcome=f"refunded:{reservation.id}",
        )
    )
