from datetime import UTC, datetime
from uuid import uuid4

import pytest
from ai_manager_contracts import (
    ActiveTask,
    AIRequest,
    Classification,
    MessageSource,
    TaskAction,
    TaskDeletionCandidate,
    TranscriptionRequest,
)
from app.results import match_task_title
from pydantic import ValidationError


def test_transcription_contract_rejects_paths() -> None:
    with pytest.raises(ValidationError):
        TranscriptionRequest(
            job_id=uuid4(),
            user_id=1,
            chat_id=1,
            telegram_message_id=1,
            reservation_id=uuid4(),
            quota_key=None,
            local_date="2026-08-24",
            audio_file="../secret.ogg",
            created_at=datetime.now(UTC),
        )


def test_classification_accepts_task_deletion() -> None:
    classification = Classification(
        cleaned_text="Delete the buy milk task",
        task_deletions=[TaskDeletionCandidate(title="buy milk")],
    )

    assert classification.task_deletions[0].title == "buy milk"


def test_ai_request_and_classification_support_task_actions() -> None:
    task_id = uuid4()
    request = AIRequest(
        job_id=uuid4(),
        user_id=1,
        chat_id=1,
        telegram_message_id=1,
        source=MessageSource.TEXT,
        text="I already bought milk",
        active_tasks=[ActiveTask(id=task_id, title="Buy milk")],
        created_at=datetime.now(UTC),
    )
    classification = Classification(
        cleaned_text=request.text,
        task_actions=[TaskAction(task_id=task_id, action="complete")],
    )

    assert request.active_tasks[0].id == classification.task_actions[0].task_id


def test_task_title_matching_tolerates_inflection() -> None:
    match, _suggestions = match_task_title("bought milk", ["Buy milk", "Call the doctor"])

    assert match == 0


def test_task_title_matching_does_not_guess_between_duplicates() -> None:
    match, suggestions = match_task_title("buy milk", ["Buy milk", "buy milk"])

    assert match is None
    assert suggestions == [0, 1]


def test_classification_supports_multiple_mixed_operations() -> None:
    first_id = uuid4()
    second_id = uuid4()
    classification = Classification(
        cleaned_text="Delete the old task, complete the call, and create three new tasks",
        tasks=[{"title": title, "confidence": 0.95} for title in ("New 1", "New 2", "New 3")],
        task_actions=[
            TaskAction(task_id=first_id, matched_title="Old task", action="delete"),
            TaskAction(task_id=second_id, matched_title="Call", action="complete"),
        ],
    )

    assert len(classification.tasks) == 3
    assert [action.action for action in classification.task_actions] == ["delete", "complete"]
