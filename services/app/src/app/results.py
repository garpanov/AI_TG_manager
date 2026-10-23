import json
import re
from datetime import UTC, datetime
from difflib import SequenceMatcher
from unicodedata import normalize

import aio_pika
import structlog
from ai_manager_contracts import AIResult, AnalysisResult, MessageSource, TranscriptionFailed
from aiogram import Bot
from redis.asyncio import Redis
from sqlalchemy import func, select

from .config import get_settings
from .db import session_factory
from .models import (
    AnalysisReport,
    Goal,
    ProcessedMessage,
    Task,
    TaskStatus,
    VoiceUsageEvent,
)
from .rabbit import AI_RESULT, ANALYSIS_RESULT, TRANSCRIPTION_FAILED, open_channel

log = structlog.get_logger()
CONSUMER = "app-ai-results-v1"
FAILURE_CONSUMER = "app-transcription-failures-v1"
ANALYSIS_CONSUMER = "app-analysis-results-v1"


def normalize_task_title(value: str) -> str:
    value = normalize("NFKC", value).casefold().replace("\u0451", "\u0435")
    return " ".join(re.findall(r"[\w]+", value, flags=re.UNICODE))


def match_task_title(query: str, titles: list[str]) -> tuple[int | None, list[int]]:
    normalized_query = normalize_task_title(query)
    normalized_titles = [normalize_task_title(title) for title in titles]
    exact = [index for index, title in enumerate(normalized_titles) if title == normalized_query]
    if len(exact) == 1:
        return exact[0], exact
    if len(exact) > 1 or not normalized_query:
        return None, exact

    query_tokens = set(normalized_query.split())
    scored: list[tuple[float, int]] = []
    for index, title in enumerate(normalized_titles):
        title_tokens = set(title.split())
        sequence_score = SequenceMatcher(None, normalized_query, title).ratio()
        token_score = len(query_tokens & title_tokens) / max(len(query_tokens | title_tokens), 1)
        containment_score = 1.0 if normalized_query in title or title in normalized_query else 0.0
        scored.append((max(sequence_score, token_score, containment_score), index))
    scored.sort(reverse=True)
    suggestions = [index for score, index in scored[:3] if score >= 0.4]
    best_score, best_index = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    if best_score >= 0.62 and best_score - second_score >= 0.12:
        return best_index, suggestions
    return None, suggestions


async def handle_result(message: aio_pika.IncomingMessage, bot: Bot) -> None:
    async with message.process(requeue=True):
        result = AIResult.model_validate(json.loads(message.body))
        deleted_titles: list[str] = []
        completed_titles: list[str] = []
        missing_titles: list[str] = []
        ambiguous_titles: list[str] = []
        ambiguous_matches: list[list[str]] = []
        conflicting_titles: list[str] = []
        async with session_factory() as session, session.begin():
            if await session.get(ProcessedMessage, (CONSUMER, result.job_id)):
                return
            for candidate in result.classification.tasks:
                session.add(
                    Task(
                        user_id=result.user_id,
                        title=candidate.title,
                        notes=candidate.notes,
                        deadline=candidate.deadline,
                        priority=candidate.priority,
                        source=result.source.value,
                        extraction_confidence=candidate.confidence,
                        needs_review=bool(candidate.review_fields),
                    )
                )
            for candidate in result.classification.goals:
                session.add(
                    Goal(
                        user_id=result.user_id,
                        title=candidate.title,
                        description=candidate.description,
                        deadline=candidate.deadline,
                        priority=candidate.priority,
                    )
                )
            for candidate in result.classification.task_deletions:
                normalized_title = candidate.title.strip().casefold()
                matches = list(
                    await session.scalars(
                        select(Task)
                        .where(
                            Task.user_id == result.user_id,
                            Task.status == TaskStatus.OPEN,
                            func.lower(func.trim(Task.title)) == normalized_title,
                        )
                        .with_for_update()
                    )
                )
                if len(matches) == 1:
                    matches[0].status = TaskStatus.CANCELLED
                    deleted_titles.append(matches[0].title)
                elif matches:
                    ambiguous_titles.append(candidate.title)
                else:
                    missing_titles.append(candidate.title)
            acted_on: dict[object, str] = {}
            active_tasks = list(
                await session.scalars(
                    select(Task)
                    .where(Task.user_id == result.user_id, Task.status == TaskStatus.OPEN)
                    .order_by(Task.created_at)
                    .with_for_update()
                )
            )
            for action in result.classification.task_actions:
                task = next(
                    (candidate for candidate in active_tasks if candidate.id == action.task_id),
                    None,
                )
                has_suggestions = False
                if task is None and action.matched_title:
                    match_index, suggestions = match_task_title(
                        action.matched_title, [candidate.title for candidate in active_tasks]
                    )
                    if match_index is not None:
                        task = active_tasks[match_index]
                    elif suggestions:
                        has_suggestions = True
                        ambiguous_matches.append(
                            [active_tasks[index].title for index in suggestions]
                        )
                if task is None:
                    if not has_suggestions:
                        missing_titles.append(action.matched_title or "requested task")
                elif task.id in acted_on:
                    if acted_on[task.id] != action.action:
                        task.status = TaskStatus.OPEN
                        if task.title in deleted_titles:
                            deleted_titles.remove(task.title)
                        if task.title in completed_titles:
                            completed_titles.remove(task.title)
                        conflicting_titles.append(task.title)
                elif action.action == "delete":
                    task.status = TaskStatus.CANCELLED
                    deleted_titles.append(task.title)
                    acted_on[task.id] = action.action
                else:
                    task.status = TaskStatus.DONE
                    completed_titles.append(task.title)
                    acted_on[task.id] = action.action
            session.add(ProcessedMessage(consumer=CONSUMER, message_id=result.job_id))

        classification = result.classification
        saved = len(classification.tasks) + len(classification.goals)
        review_fields = sorted(
            {
                field
                for item in [*classification.tasks, *classification.goals]
                for field in item.review_fields
            }
        )
        reply_parts: list[str] = []
        if classification.tasks:
            reply_parts.append(
                "Tasks created:\n" + "\n".join(f"• {item.title}" for item in classification.tasks)
            )
        if classification.goals:
            reply_parts.append(
                "Goals created:\n" + "\n".join(f"• {item.title}" for item in classification.goals)
            )
        if saved and review_fields:
            reply_parts.append(f"Please review these fields: {', '.join(review_fields)}.")
        if deleted_titles:
            reply_parts.append("Deleted:\n" + "\n".join(f"• {title}" for title in deleted_titles))
        if completed_titles:
            reply_parts.append(
                "Completed:\n" + "\n".join(f"• {title}" for title in completed_titles)
            )
        if missing_titles:
            reply_parts.append("Not found:\n" + "\n".join(f"• {title}" for title in missing_titles))
        if ambiguous_titles:
            reply_parts.append(
                "Several identical matches were found; nothing was changed:\n"
                + "\n".join(f"• {title}" for title in ambiguous_titles)
            )
        for suggestions in ambiguous_matches:
            reply_parts.append(
                "Which task did you mean?\n" + "\n".join(f"• {title}" for title in suggestions),
            )
        if conflicting_titles:
            reply_parts.append(
                "Conflicting actions were requested; nothing was changed:\n"
                + "\n".join(f"• {title}" for title in conflicting_titles)
            )
        if reply_parts:
            await bot.send_message(result.chat_id, "\n\n".join(reply_parts))
        if classification.contains_plan:
            if result.source == MessageSource.VOICE:
                transcript = await bot.send_message(result.chat_id, classification.cleaned_text)
                await bot.pin_chat_message(
                    result.chat_id, transcript.message_id, disable_notification=True
                )
            else:
                try:
                    await bot.pin_chat_message(
                        result.chat_id, result.telegram_message_id, disable_notification=True
                    )
                except Exception:
                    copied = await bot.copy_message(
                        result.chat_id, result.chat_id, result.telegram_message_id
                    )
                    await bot.pin_chat_message(
                        result.chat_id, copied.message_id, disable_notification=True
                    )
        handled = (
            saved
            or deleted_titles
            or completed_titles
            or missing_titles
            or ambiguous_titles
            or ambiguous_matches
            or conflicting_titles
        )
        if classification.unsupported and not handled and not classification.contains_plan:
            await bot.send_message(
                result.chat_id,
                classification.clarification or "Could you phrase that as a task, goal, or plan?",
            )


async def handle_failure(message: aio_pika.IncomingMessage, bot: Bot, redis: Redis) -> None:
    async with message.process(requeue=True):
        failure = TranscriptionFailed.model_validate_json(message.body)
        async with session_factory() as session, session.begin():
            if await session.get(ProcessedMessage, (FAILURE_CONSUMER, failure.job_id)):
                return
            if failure.quota_key:
                script = """
                if redis.call('SETNX', KEYS[2], '1') == 1 then
                    redis.call('EXPIRE', KEYS[2], 172800)
                    local count = tonumber(redis.call('GET', KEYS[1]) or '0')
                    if count > 0 then redis.call('DECR', KEYS[1]) end
                    return 1
                end
                return 0
                """
                await redis.eval(
                    script, 2, failure.quota_key, f"voice-refund:{failure.reservation_id}"
                )
            usage = await session.scalar(
                select(VoiceUsageEvent)
                .where(VoiceUsageEvent.reservation_id == failure.reservation_id)
                .with_for_update()
            )
            if usage:
                usage.outcome = "refunded"
            session.add(ProcessedMessage(consumer=FAILURE_CONSUMER, message_id=failure.job_id))
        await bot.send_message(
            failure.chat_id,
            "I couldn't transcribe that voice message. Your voice quota was refunded.",
        )


async def handle_analysis(message: aio_pika.IncomingMessage, bot: Bot) -> None:
    async with message.process(requeue=True):
        result = AnalysisResult.model_validate_json(message.body)
        async with session_factory() as session, session.begin():
            if await session.get(ProcessedMessage, (ANALYSIS_CONSUMER, result.job_id)):
                return
            report = AnalysisReport(
                user_id=result.user_id,
                kind=result.kind.value,
                period_key=result.period_key,
                content=result.content,
            )
            session.add(report)
            session.add(ProcessedMessage(consumer=ANALYSIS_CONSUMER, message_id=result.job_id))
            await session.flush()
        await bot.send_message(result.chat_id, result.content)
        async with session_factory() as session, session.begin():
            stored = await session.scalar(
                select(AnalysisReport).where(
                    AnalysisReport.user_id == result.user_id,
                    AnalysisReport.kind == result.kind.value,
                    AnalysisReport.period_key == result.period_key,
                )
            )
            stored.delivered_at = datetime.now(UTC)


async def consume_results(bot: Bot, redis: Redis) -> None:
    settings = get_settings()
    async for connection, channel, exchange in open_channel(settings.rabbitmq_url):
        queue = await channel.declare_queue("app.ai-results.v1", durable=True)
        await queue.bind(exchange, AI_RESULT)
        failure_queue = await channel.declare_queue("app.transcription-failures.v1", durable=True)
        await failure_queue.bind(exchange, TRANSCRIPTION_FAILED)
        analysis_queue = await channel.declare_queue("app.analysis-results.v1", durable=True)
        await analysis_queue.bind(exchange, ANALYSIS_RESULT)
        try:
            await queue.consume(lambda message: handle_result(message, bot))
            await failure_queue.consume(lambda message: handle_failure(message, bot, redis))
            await analysis_queue.consume(lambda message: handle_analysis(message, bot))
            await __import__("asyncio").Future()
        finally:
            await connection.close()
