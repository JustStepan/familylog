import sys
import asyncio

from src.config import settings
from src.familylog.processor.summary import generate_summary, get_last_summary_time
from src.familylog.bot.keyboards import build_reply_keyboard
from src.logger import logger


async def main():
    dry_run = "--dry-run" in sys.argv

    logger.info("=" * 60)
    logger.info("FamilyLog Summary" + (" [DRY-RUN]" if dry_run else ""))
    logger.info("=" * 60)

    # Определяем период (та же логика что в run_summary())
    since = await get_last_summary_time()
    if since:
        logger.info(f"Последний summary: {since.strftime('%Y-%m-%d %H:%M')}")
    else:
        logger.info("Первый запуск summary — собираем всё")

    # generate_summary() — только генерация, без сохранения маркера времени
    result = await generate_summary(since)

    summary_text = result["summary_text"]
    logger.info(f"--- Summary ---\n{summary_text}\n--- end ---")

    if dry_run:
        logger.info("(dry-run: vault и Telegram не изменены)")
        return

    if not summary_text:
        logger.info("Нет текста для отправки.")
        return

    # Сохраняем файл в vault
    from src.familylog.processor.obsidian import api
    from src.familylog.processor.summary import save_last_summary_time
    from datetime import datetime

    if result["filename"] and result["content"]:
        await api.obsidian_create(result["filename"], result["content"])
        logger.info(f"Сохранён: {result['filename']}")

    await save_last_summary_time(datetime.now())

    # Отправляем в Telegram
    from aiogram import Bot
    bot = Bot(token=settings.BOT_TOKEN)
    keyboard = build_reply_keyboard()

    for chat_id in settings.FAMILY_CHAT_IDS:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=f"Сводка FamilyLog\n\n{summary_text}",
                reply_markup=keyboard,
            )
            logger.info(f"Отправлено: {chat_id}")
        except Exception as e:
            logger.error(f"Ошибка отправки {chat_id}: {e}")

    await bot.session.close()
    logger.info("Готово!")


if __name__ == "__main__":
    asyncio.run(main())