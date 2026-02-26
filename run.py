import asyncio

from src.familylog.collector.telegram import collect_messages, close_all_open_sessions
from src.familylog.processor.assembler import assemble_sessions
from src.familylog.processor.obsidian_writer import process_assembled_sessions
from src.familylog.storage.database import init_db, AsyncSessionLocal
from src.familylog.processor.stt import process_voice_messages
from src.familylog.processor.vision import process_photo_messages
from src.config import settings


async def main():
    await init_db()

    async with AsyncSessionLocal() as session:

        # ── 1. Сбор сообщений ───────────────────────────────────────────────
        collected = await collect_messages(session)
        print(f"{'*' * 50}\nСобрано сообщений: {collected}")

        # ── 2. STT — голосовые сообщения ────────────────────────────────────
        voice_count = await process_voice_messages(session)
        print(f"{'*' * 50}\nОбработано голосовых: {voice_count}")

        # ── 3. Vision — фото ────────────────────────────────────────────────
        if settings.CONNECTION_TYPE == "offline":
            from src.familylog.LLMs_calls.model_manager import (
                get_loaded_models, load_model, unload_model, switch_model
            )

            # Проверяем есть ли pending фото перед загрузкой модели
            from sqlalchemy import select
            from src.familylog.storage.models import Message
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
        print(f"{'*' * 50}\nОбработано фото: {photo_count}")

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
        closed = await close_all_open_sessions(session)
        print(f"{'*' * 50}\nЗакрыто сессий: {closed}")

        # ── 6. Сборка сессий ────────────────────────────────────────────────
        assembled = await assemble_sessions(session)
        print(f"{'*' * 50}\nСобрано сессий: {assembled}")

        # ── 7. Запись в Obsidian ─────────────────────────────────────────────
        obsidian_count = await process_assembled_sessions(session)
        print(f"{'*' * 50}\nЗаписано в Obsidian: {obsidian_count}")

        # ── 8. Выгружаем LLM после завершения ───────────────────────────────
        if settings.CONNECTION_TYPE == "offline":
            loaded = await get_loaded_models()
            if settings.llm_model in loaded:
                await unload_model(settings.llm_model)

        print(f"{'*' * 50}\nГотово!")


if __name__ == "__main__":
    asyncio.run(main())