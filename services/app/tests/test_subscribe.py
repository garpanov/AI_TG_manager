from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.handlers import subscribe


@pytest.mark.asyncio
async def test_subscribe_creates_recurring_stars_invoice_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.handlers.get_settings",
        lambda: SimpleNamespace(stars_price=500),
    )
    bot = SimpleNamespace(create_invoice_link=AsyncMock(return_value="https://t.me/$invoice"))
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )

    await subscribe(message, bot)

    bot.create_invoice_link.assert_awaited_once()
    invoice = bot.create_invoice_link.await_args.kwargs
    assert invoice["payload"] == "subscription:123"
    assert invoice["currency"] == "XTR"
    assert invoice["prices"][0].amount == 500
    assert invoice["subscription_period"] == 2_592_000

    message.answer.assert_awaited_once()
    reply_markup = message.answer.await_args.kwargs["reply_markup"]
    assert reply_markup.inline_keyboard[0][0].url == "https://t.me/$invoice"
