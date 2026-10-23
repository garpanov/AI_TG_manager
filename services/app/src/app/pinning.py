import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

log = structlog.get_logger()


async def pin_with_fallback(bot: Bot, message: Message) -> bool:
    try:
        await bot.pin_chat_message(message.chat.id, message.message_id, disable_notification=True)
        return True
    except TelegramAPIError:
        log.warning("pin_original_failed", chat_id=message.chat.id, message_id=message.message_id)
    try:
        copied = await bot.copy_message(message.chat.id, message.chat.id, message.message_id)
        await bot.pin_chat_message(message.chat.id, copied.message_id, disable_notification=True)
        return True
    except TelegramAPIError:
        log.exception("pin_copy_failed", chat_id=message.chat.id, message_id=message.message_id)
        await message.answer("I couldn't pin that message. Please pin it manually.")
        return False
