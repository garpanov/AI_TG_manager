from datetime import UTC, datetime

from app.handlers import local_day_bounds, start_of_next_week, user_zone


def test_local_day_bounds_use_user_timezone() -> None:
    now = datetime(2026, 8, 25, 22, 30, tzinfo=UTC)

    today, tomorrow, day_after_tomorrow = local_day_bounds("Europe/Warsaw", now)

    assert today == datetime(2026, 8, 25, 22, 0, tzinfo=UTC)
    assert tomorrow == datetime(2026, 8, 26, 22, 0, tzinfo=UTC)
    assert day_after_tomorrow == datetime(2026, 8, 27, 22, 0, tzinfo=UTC)


def test_next_week_starts_on_user_local_monday() -> None:
    now = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)

    assert start_of_next_week("Europe/Warsaw", now) == datetime(2026, 8, 30, 22, 0, tzinfo=UTC)


def test_unknown_timezone_falls_back_to_utc() -> None:
    assert user_zone("Not/A-Timezone").key == "UTC"
