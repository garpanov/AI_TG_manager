# AI Manager application

The app image exposes two processes:

```bash
uv run alembic upgrade head
uv run ai-manager-bot
uv run ai-manager-scheduler
```

Configuration uses `APP_`-prefixed environment variables. Required: `APP_BOT_TOKEN`.
Common settings are `APP_DATABASE_URL`, `APP_REDIS_URL`, `APP_RABBITMQ_URL`,
`APP_STARS_PRICE`, and comma-separated `APP_VOICE_WHITELIST`.

RabbitMQ contracts are versioned routing keys:

- `transcription.request.v1`: durable request containing a shared-volume basename.
- `transcription.failed.v1`: durable failure/refund notification.
- `ai.request.v1` / `ai.result.v1`: durable classification pipeline.
- `analysis.request.v1`: durable outbox jobs for scheduled reports.
- `analysis.result.v1`: durable report results consumed, stored, then delivered.

The AI result must match `app.domain.Classification`. Analysis results contain
`user_id`, `chat_id`, `kind`, `period_key`, and `content`.

The `voice-files` volume is mounted only into the bot and transcription worker.
The worker deletes audio only after the downstream RabbitMQ publication is
confirmed. Audio is never embedded in a broker message.
