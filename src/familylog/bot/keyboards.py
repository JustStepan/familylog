import asyncio
from aiogram import Bot
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from src.config import settings


async def main():
    bot = Bot(token=settings.BOT_TOKEN)

    # Reply keyboard — всегда видна внизу экрана
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
        resize_keyboard=True,  # компактный размер
        is_persistent=True,  # не скрывается после нажатия
    )

    for chat_id in settings.FAMILY_CHAT_IDS:
        await bot.send_message(
            chat_id=chat_id,
            text="FamilyBot готов! Выбери тип записи:",
            reply_markup=keyboard,
        )
        print(f"Клавиатура отправлена: {chat_id}")

    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
