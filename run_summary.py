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
from src.logger import logger


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

    logger.info("=" * 60)
    logger.info("FamilyLog Summary")
    logger.info("=" * 60)

    result = await run_summary()

    summary_text = result["summary_text"]
    logger.info(f"--- Summary ---\n{summary_text}\n--- end ---")

    if dry_run:
        logger.info("(dry-run: Telegram отправка пропущена)")
        return

    if not summary_text:
        logger.info("Нет текста для отправки.")
        return

    bot = Bot(token=settings.BOT_TOKEN)

    for chat_id in settings.FAMILY_CHAT_IDS:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=f"Сводка FamilyLog\n\n{summary_text}",
                reply_markup=KEYBOARD,
            )
            logger.info(f"Отправлено: {chat_id}")
        except Exception as e:
            logger.error(f"Ошибка отправки {chat_id}: {e}")

    await bot.session.close()
    logger.info("Готово!")


if __name__ == "__main__":
    asyncio.run(main())
