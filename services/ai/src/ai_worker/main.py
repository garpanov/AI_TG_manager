import asyncio
import json
from datetime import UTC, datetime

import aio_pika
from ai_manager_contracts import (
    AIRequest,
    AIResult,
    AnalysisRequest,
    AnalysisResult,
    Classification,
)
from aio_pika import DeliveryMode, ExchangeType, Message
from google import genai
from google.genai import types

from .config import get_settings

EXCHANGE = "ai-manager"
REQUEST_KEY = "ai.request.v1"
RESULT_KEY = "ai.result.v1"
ANALYSIS_REQUEST_KEY = "analysis.request.v1"
ANALYSIS_RESULT_KEY = "analysis.result.v1"
SYSTEM_PROMPT = """
You classify messages for a private Telegram task manager. Return only the requested
schema. Extract zero or more tasks and goals. A plan is reference material the user
wants pinned; never turn its prose into stored plan data. A single message may contain
any number and mixture of create-task, create-goal, delete-task, complete-task, and
plan operations. Extract every operation independently; never stop after the first.
Task actions may reference only the supplied active tasks; newly requested tasks belong
in tasks and must not also appear in task_actions. You receive the user's active tasks
with stable IDs. When the user explicitly
asks to delete/remove/cancel an existing task, emit a task_action with its ID and
action=delete. When the user says an existing task is done/completed, emit a task_action
with its ID and action=complete. Always copy the selected active task's exact title to
matched_title. Match natural wording, inflections, minor transcription errors, and
paraphrases against the supplied titles. If the action is clear but you cannot choose a
unique task, still emit the action with task_id=null and put the user's description of
the target in matched_title. Never invent an ID and never emit the same item as a new
task. task_deletions is legacy: always leave it empty. Unsupported conversation should
set unsupported=true and provide one concise
clarifying question. Use null for uncertain optional values, list their field names
in review_fields, and never invent a deadline. Resolve relative dates such as today
and tomorrow from the supplied local datetime and IANA timezone. Return deadlines as
timezone-aware ISO 8601 datetimes. cleaned_text should be a concise, faithful
transcript suitable for pinning when source is voice.
Emit at most one task_action per active task. If the user gives contradictory actions
for the same task, omit that action and ask a clarification.
""".strip()


async def classify(client, request: AIRequest) -> Classification:
    settings = get_settings()
    active_tasks = [task.model_dump(mode="json") for task in request.active_tasks]
    response = await client.models.generate_content(
        model=settings.gemini_model,
        contents=(
            f"Source: {request.source.value}\n"
            f"User timezone: {request.timezone or 'unknown'}\n"
            f"User local datetime: "
            f"{request.local_datetime.isoformat() if request.local_datetime else 'unknown'}\n"
            f"Active tasks:\n"
            f"{json.dumps(active_tasks, ensure_ascii=False)}\n"
            f"Message:\n{request.text}"
        ),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_json_schema=Classification.model_json_schema(),
            temperature=0.1,
        ),
    )
    if response.parsed is None:
        raise ValueError("Gemini returned no structured classification")
    return Classification.model_validate(response.parsed)


async def handle(message: aio_pika.IncomingMessage, exchange, client) -> None:
    async with message.process(requeue=True):
        request = AIRequest.model_validate_json(message.body)
        classification = await classify(client, request)
        result = AIResult(
            job_id=request.job_id,
            user_id=request.user_id,
            chat_id=request.chat_id,
            telegram_message_id=request.telegram_message_id,
            source=request.source,
            classification=classification,
            created_at=datetime.now(UTC),
        )
        outgoing = Message(
            json.dumps(result.model_dump(mode="json"), separators=(",", ":")).encode(),
            content_type="application/json",
            delivery_mode=DeliveryMode.PERSISTENT,
            message_id=str(request.job_id),
        )
        await exchange.publish(outgoing, routing_key=RESULT_KEY, mandatory=True)


async def handle_analysis(message: aio_pika.IncomingMessage, exchange, client) -> None:
    async with message.process(requeue=True):
        request = AnalysisRequest.model_validate_json(message.body)
        settings = get_settings()
        response = await client.models.generate_content(
            model=settings.gemini_model,
            contents=json.dumps(request.context, ensure_ascii=False),
            config=types.GenerateContentConfig(
                system_instruction=(
                    f"Write a concise, practical {request.kind.value} productivity analysis. "
                    "Use only supplied data, mention patterns and give at most three next actions."
                ),
                temperature=0.2,
            ),
        )
        if not response.text:
            raise ValueError("Gemini returned an empty analysis")
        result = AnalysisResult(
            job_id=request.job_id,
            user_id=request.user_id,
            chat_id=request.chat_id,
            kind=request.kind,
            period_key=request.period_key,
            content=response.text,
            created_at=datetime.now(UTC),
        )
        await exchange.publish(
            Message(
                json.dumps(result.model_dump(mode="json"), separators=(",", ":")).encode(),
                content_type="application/json",
                delivery_mode=DeliveryMode.PERSISTENT,
                message_id=str(request.job_id),
            ),
            routing_key=ANALYSIS_RESULT_KEY,
            mandatory=True,
        )


async def main() -> None:
    settings = get_settings()
    client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())
    connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    async with connection, client.aio as async_client:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=4)
        exchange = await channel.declare_exchange(EXCHANGE, ExchangeType.TOPIC, durable=True)
        queue = await channel.declare_queue("ai.classification.v1", durable=True)
        await queue.bind(exchange, REQUEST_KEY)
        analysis_queue = await channel.declare_queue("ai.analysis.v1", durable=True)
        await analysis_queue.bind(exchange, ANALYSIS_REQUEST_KEY)
        await queue.consume(lambda message: handle(message, exchange, async_client))
        await analysis_queue.consume(
            lambda message: handle_analysis(message, exchange, async_client)
        )
        await asyncio.Future()


def run() -> None:
    asyncio.run(main())
