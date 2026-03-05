import sys
import asyncio
from datetime import datetime
from sqlalchemy import select

from src.familylog.bot.sender import send_summary_to_telegram
from src.familylog.collector.telegram import collect_messages, close_old_open_sessions
from src.familylog.LLMs_calls.model_manager import (
    get_loaded_models, load_model, unload_model, switch_model
)
from src.familylog.processor.assembler import assemble_sessions
from src.familylog.processor.documents import process_document_messages
from src.familylog.processor.obsidian_writer import process_assembled_sessions
from src.familylog.processor.stt import process_voice_messages
from src.familylog.processor.vision import process_photo_messages
from src.familylog.processor.summary import run_summary, get_last_summary_time
from src.familylog.storage.database import init_db, AsyncSessionLocal
from src.familylog.storage.models import Message
from src.config import settings
from src.logger import logger


async def should_run_summary() -> bool:
    since = await get_last_summary_time()
    if since is None:
        return False
    days_passed = (datetime.now() - since).days
    return days_passed >= settings.SUMMARY_INTERVAL_DAYS


async def main():
    force_summary = "--summary" in sys.argv

    await init_db()

    async with AsyncSessionLocal() as session:

        # ── 1. Сбор сообщений ───────────────────────────────────────────────
        collected = await collect_messages(session)
        logger.info(f"Собрано сообщений: {collected}")

        # ── 2. STT — голосовые сообщения ────────────────────────────────────
        voice_count = await process_voice_messages(session)
        logger.info(f"Обработано голосовых: {voice_count}")

        # ── 3. Vision — фото ────────────────────────────────────────────────
        if settings.CONNECTION_TYPE == "offline":
            # Проверяем есть ли pending фото перед загрузкой модели
            pending_photos = await session.execute(
                select(Message).where(
                    Message.message_type == "photo",
                    Message.status == "pending"
                )
            )
            has_photos = pending_photos.scalars().first() is not None

            if has_photos:
                await load_model(settings.vision_model)

        photo_count = await process_photo_messages(session)
        logger.info(f"Обработано фото: {photo_count}")

        # ── 3b. Документы ──────────────────────────────────────────────────
        doc_count = await process_document_messages(session)
        logger.info(f"Обработано документов: {doc_count}")

        # ── 4. Загружаем LLM (выгружаем vision если была загружена) ─────────
        if settings.CONNECTION_TYPE == "offline":
            loaded = await get_loaded_models()

            if settings.vision_model in loaded:
                # Vision была загружена — переключаем
                await switch_model(
                    unload_id=settings.vision_model,
                    load_id=settings.llm_model,
                )
            else:
                # Vision не загружалась — просто грузим LLM
                await load_model(settings.llm_model)

        # ── 5. Закрываем открытые сессии ────────────────────────────────────
        closed = await close_old_open_sessions(session)
        logger.info(f"Закрыто сессий: {closed}")

        # ── 6. Сборка сессий ────────────────────────────────────────────────
        assembled = await assemble_sessions(session)
        logger.info(f"Собрано сессий: {assembled}")

        # ── 7. Запись в Obsidian ─────────────────────────────────────────────
        obsidian_count = await process_assembled_sessions(session)
        logger.info(f"Записано в Obsidian: {obsidian_count}")

        # ── 8. Выгружаем LLM после завершения ───────────────────────────────
        if settings.CONNECTION_TYPE == "offline":
            loaded = await get_loaded_models()
            if settings.llm_model in loaded:
                await unload_model(settings.llm_model)

        # ── 9. Отправляем суммари если нужно (или с флагом "--summary") ─────
        if force_summary or await should_run_summary():
            logger.info("Запускаем суммаризацию...")
            result = await run_summary()
            if result["summary_text"]:
                await send_summary_to_telegram(result["summary_text"])

        logger.info(f"{'*' * 50}Готово!")


if __name__ == "__main__":
    asyncio.run(main())