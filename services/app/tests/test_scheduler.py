from datetime import datetime
from zoneinfo import ZoneInfo

from ai_manager_contracts import AnalysisKind
from app.scheduler import due_analysis


def test_weekly_analysis_is_due_monday_at_eight() -> None:
    timezone = ZoneInfo("Europe/Warsaw")
    local = datetime(2026, 8, 24, 8, 0, tzinfo=timezone)
    registered = datetime(2026, 1, 1, 12, 0, tzinfo=timezone)

    assert (AnalysisKind.WEEKLY, "2026-W34") in due_analysis(local, registered)


def test_analysis_is_not_due_outside_delivery_hour() -> None:
    timezone = ZoneInfo("Europe/Warsaw")
    local = datetime(2026, 8, 24, 9, 0, tzinfo=timezone)

    assert due_analysis(local, local) == []
