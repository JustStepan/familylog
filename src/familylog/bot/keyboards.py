import asyncio
from aiogram import Bot
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from src.config import settings
from src.constants import KEYBOARD_BUTTONS
from src.logger import logger


def build_reply_keyboard() -> ReplyKeyboardMarkup:
    """Строит клавиатуру из констант. Используется в sender.py и main()."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=btn) for btn in row] for row in KEYBOARD_BUTTONS],
        resize_keyboard=True,
        is_persistent=True,
    )


async def main():
    """Ручная отправка клавиатуры всем членам семьи."""
    bot = Bot(token=settings.BOT_TOKEN)
    keyboard = build_reply_keyboard()

    for chat_id in settings.FAMILY_CHAT_IDS:
        await bot.send_message(
            chat_id=chat_id,
            text="FamilyLog готов! Выбери тип записи:",
            reply_markup=keyboard,
        )
        logger.info(f"Клавиатура отправлена: {chat_id}")

    await bot.session.close()
    logger.info("Клавиатура бота запущена вручную")


if __name__ == "__main__":
    asyncio.run(main())