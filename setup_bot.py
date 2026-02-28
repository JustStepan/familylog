import asyncio
import logging

from aiogram import Bot
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from src.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main():
    bot = Bot(token=settings.BOT_TOKEN)

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📝 заметка"),
                KeyboardButton(text="📔 дневник"),
            ],
            [
                KeyboardButton(text="📅 календарь"),
                KeyboardButton(text="✅ задание"),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )

    for chat_id in settings.FAMILY_CHAT_IDS:
        await bot.send_message(
            chat_id=chat_id,
            text="FamilyLog готов! Выбери тип записи:",
            reply_markup=keyboard,
        )
        logger.info("Клавиатура отправлена: %d", chat_id)

    await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
