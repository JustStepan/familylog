"""Генерация summary + отправка в Telegram с клавиатурой.

Использование:
  uv run run_summary.py           — summary + клавиатура
  uv run run_summary.py --dry-run — только summary, без отправки

Скрипт:
1. Определяет период с последнего summary
2. Собирает все записи из vault за этот период
3. Генерирует summary через LLM
4. Сохраняет summary в vault/summaries/
5. Отправляет summary текст в Telegram всем членам семьи
6. Устанавливает reply keyboard с категориями
"""

import sys
import asyncio

from aiogram import Bot
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from src.config import settings
from src.familylog.processor.summary import run_summary

# Список chat_id пользователей
FAMILY_CHAT_IDS = [
    987692540,   # Степан
    6293359903,  # Диана
]

KEYBOARD = ReplyKeyboardMarkup(
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


async def main():
    dry_run = "--dry-run" in sys.argv

    print("=" * 60)
    print("FamilyLog Summary")
    print("=" * 60)

    # Генерируем summary
    result = await run_summary()

    summary_text = result["summary_text"]
    print(f"\n--- Summary ---\n{summary_text}\n--- end ---\n")

    if dry_run:
        print("(dry-run: Telegram отправка пропущена)")
        return

    if not summary_text:
        print("Нет текста для отправки.")
        return

    # Отправляем в Telegram
    bot = Bot(token=settings.BOT_TOKEN)

    for chat_id in FAMILY_CHAT_IDS:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=f"📊 Сводка FamilyLog\n\n{summary_text}",
                reply_markup=KEYBOARD,
            )
            print(f"Отправлено: {chat_id}")
        except Exception as e:
            print(f"Ошибка отправки {chat_id}: {e}")

    await bot.session.close()
    print("\nГотово!")


if __name__ == "__main__":
    asyncio.run(main())
