from aiogram import Bot
from src.config import settings
from src.familylog.bot.keyboards import build_reply_keyboard
from src.logger import logger


async def send_summary_to_telegram(summary_text: str) -> None:
    """Отправляет summary всем членам семьи с клавиатурой."""
    bot = Bot(token=settings.BOT_TOKEN)
    keyboard = build_reply_keyboard()

    for chat_id in settings.FAMILY_CHAT_IDS:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=f"Сводка FamilyLog\n\n{summary_text}",
                reply_markup=keyboard,
            )
            logger.info(f"Summary отправлен: {chat_id}")
        except Exception as e:
            logger.error(f"Ошибка отправки {chat_id}: {e}")

    await bot.session.close()