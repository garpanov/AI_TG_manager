# AGENTS.md

## Project

This repository contains a Telegram-first AI task manager. The MVP manages tasks, goals, an internal calendar, voice capture, scheduled AI analysis, and Telegram Stars subscriptions.

Treat this file as the source of truth for product invariants. Keep implementation details in code and focused documentation rather than expanding this file unnecessarily.

## Stack and Architecture

- Python managed with `uv`.
- aiogram for the Telegram bot.
- PostgreSQL with Alembic and stable SQLAlchemy 2.0 async APIs.
- Redis for quotas, short-lived FSM state, distributed locks, and deduplication.
- RabbitMQ for asynchronous work.
- Gemini behind an internal AI service.
- `whisper.cpp` with the small model behind an internal transcription service.
- All database timestamps are UTC. User-facing dates, quotas, and schedules use the user's IANA timezone.

The deployment topology has six components:

1. Bot/API application, including a separately runnable scheduler process from the same application image.
2. PostgreSQL.
3. Redis.
4. RabbitMQ.
5. Transcription service.
6. AI service, including RabbitMQ consumers.

Do not introduce additional independently deployed services without an explicit architectural decision.

## Domain Model

The persistent model includes:

- Users and user profiles.
- Tasks with title, notes, optional deadline, priority, status, source, extraction confidence, `needs_review`, and audit timestamps.
- Goals with title, description, optional deadline, priority, status, and audit timestamps.
- AI analysis reports: initial, day-3, weekly, monthly, and yearly.
- Subscriptions and immutable payment events.
- Voice usage events.
- A durable job outbox for reliable RabbitMQ publication.

Do not create mutable tables for these projections:

- The calendar is derived from task deadlines.
- Incomplete tasks are filtered from task statuses.
- “All tasks” is the tasks table/query, not a second table.

There is no plans table or `/plans` command. Plans are Telegram pinned messages only. Never persist plan text, plan media, plan transcripts, or a plan/pin index in PostgreSQL.

## Telegram Message Routing

Route incoming messages in this order:

1. Handle supported slash commands locally without Gemini.
2. Pin any forwarded message immediately, regardless of type or caption. Do not send it to AI or transcription and do not download its media.
3. Pin original photos and videos immediately. Do not process their captions with AI and do not download their media.
4. Validate voice duration and quota, transcribe accepted voice messages, then classify the transcript with Gemini.
5. Classify original, non-command text with Gemini.
6. Reply concisely to unsupported media without processing or pinning it.

Gemini classification results are task, goal, plan, unsupported, or a mixture:

- Save tasks and goals automatically without confirmation.
- For uncertain fields, omit the uncertain value, set `needs_review`, and tell the user what needs review.
- For a text plan, pin the original user message without storing it.
- For a voice plan, send a cleaned transcript and pin the bot's transcript message. Do not persist the transcript.
- For mixed actionable and plan content, save the tasks/goals and pin the source message.
- For unsupported conversational text, ask for a concise clarification and persist nothing.

Pin silently. If pinning the original message fails, copy it into the same chat and pin the copy. If both attempts fail, leave the original untouched, log the failure without content, and inform the user.

The MVP operates in private Telegram chats. Do not silently broaden behavior to groups or channels.

## Commands and Onboarding

Supported unlimited, non-AI commands:

- `/tasks`
- `/calendar`
- `/goals`

Onboarding collects:

1. IANA timezone.
2. Available planning time.
3. Age.
4. Occupation.
5. Main goals/tasks with optional deadlines.
6. Tomorrow's tasks.

Trigger the initial task-only analysis after initial task entry is complete. Later analyses may use the profile, goals, tasks, completion history, and rescheduling patterns. Pinned plans are never analysis input.

## Analysis Schedule

- Initial: after onboarding task entry; tasks only.
- Day 3: three days after registration at 08:00 user-local time.
- Weekly: analyze the week after Sunday closes and deliver Monday at 08:00 user-local time.
- Monthly: first day of each month at 08:00 user-local time.
- Yearly: January 1 at 08:00 user-local time.

Store a report before delivering its Telegram summary. Scheduling, generation, and delivery must be idempotent and safe across retries and daylight-saving transitions.

## Voice Quotas

- Maximum duration is 30 seconds. Reject longer messages before download and do not consume quota.
- Registration day free quota: 5 accepted voice messages.
- Subsequent free quota: 3 per user-local calendar day.
- Paid quota: 20 per user-local calendar day.
- Telegram user IDs configured in the environment whitelist have unlimited usage.

Reserve quota atomically in Redis and record the outcome in PostgreSQL. Refund reservations for infrastructure or transcription failures. Count successfully transcribed requests even if classification later yields unsupported content.

Delete downloaded audio after processing. Do not retain raw audio by default.

## Payments

- Use recurring Telegram Stars invoices with the Telegram-supported 30-day subscription period.
- Configure the whole-Star price through validated environment settings; the business target is USD 10/month, but checkout is denominated in Stars.
- Activate paid access only after a verified successful-payment update.
- Preserve access until the recorded expiration time after cancellation.
- Handle purchases, renewals, cancellations, expirations, refunds, and duplicate Telegram updates idempotently.
- Prevent concurrent duplicate active subscriptions at both application and database levels.

## Messaging and Reliability

Use versioned RabbitMQ contracts for at least:
