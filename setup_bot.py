import asyncio
from aiogram import Bot
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from config import settings

# Список chat_id пользователей которым отправить клавиатуру
# Добавь сюда ID всех членов семьи
FAMILY_CHAT_IDS = [
    987692540,  # Stefan — твой ID из БД
    # добавь остальных
]

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
                KeyboardButton(text="⏰ напоминание"),
            ],
        ],
        resize_keyboard=True,   # компактный размер
        is_persistent=True,        # не скрывается после нажатия
    )
    
    for chat_id in FAMILY_CHAT_IDS:
        await bot.send_message(
            chat_id=chat_id,
            text="FamilyLog готов! Выбери тип записи:",
            reply_markup=keyboard,
        )
        print(f"Клавиатура отправлена: {chat_id}")
    
    await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())