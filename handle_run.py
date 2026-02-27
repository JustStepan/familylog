"""Ручной двухфазный пайплайн FamilyLog.

Фаза 1 (автоматическая):
  - Сбор сообщений из Telegram
  - STT транскрипция
  - Vision описание фото
  - Обработка документов
  - Закрытие сессий + сборка assembled_content

  >>> Пауза — пользователь вручную загружает тяжёлую модель в LM Studio <<<

Фаза 2 (после подтверждения):
  - Передача assembled_content в LLM
  - Запись в Obsidian

Использование:
  uv run handle_run.py
"""

import asyncio

from src.familylog.collector.telegram import collect_messages, close_all_open_sessions
from src.familylog.processor.assembler import assemble_sessions
from src.familylog.processor.obsidian_writer import process_assembled_sessions
from src.familylog.storage.database import init_db, AsyncSessionLocal
from src.familylog.processor.stt import process_voice_messages
from src.familylog.processor.vision import process_photo_messages
from src.familylog.processor.documents import process_document_messages
from src.config import settings


async def phase1(session):
    """Фаза 1: сбор и подготовка данных (не требует тяжёлой LLM)."""
    print("=" * 60)
    print("ФАЗА 1: Сбор и подготовка данных")
    print("=" * 60)

    # ── 1. Сбор сообщений ───────────────────────────────────────────
    collected = await collect_messages(session)
    print(f"{'*' * 50}\nСобрано сообщений: {collected}")

    # ── 2. STT — голосовые сообщения ────────────────────────────────
    voice_count = await process_voice_messages(session)
    print(f"{'*' * 50}\nОбработано голосовых: {voice_count}")

    # ── 3. Vision — фото ────────────────────────────────────────────
    if settings.CONNECTION_TYPE == "offline":
        from src.familylog.LLMs_calls.model_manager import load_model, unload_model

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

    # ── 3b. Документы ───────────────────────────────────────────────
    doc_count = await process_document_messages(session)
    print(f"{'*' * 50}\nОбработано документов: {doc_count}")

    # ── 4. Выгружаем vision модель ──────────────────────────────────
    if settings.CONNECTION_TYPE == "offline":
        from src.familylog.LLMs_calls.model_manager import get_loaded_models, unload_model
        loaded = await get_loaded_models()
        if settings.vision_model in loaded:
            await unload_model(settings.vision_model)
            print(f"  Выгружена vision модель: {settings.vision_model}")

    # ── 5. Закрываем открытые сессии ────────────────────────────────
    closed = await close_all_open_sessions(session)
    print(f"{'*' * 50}\nЗакрыто сессий: {closed}")

    # ── 6. Сборка сессий ────────────────────────────────────────────
    assembled = await assemble_sessions(session)
    print(f"{'*' * 50}\nСобрано сессий: {assembled}")

    return assembled


async def phase2(session):
    """Фаза 2: обработка LLM и запись в Obsidian (требует загруженную модель)."""
    print("\n" + "=" * 60)
    print("ФАЗА 2: Обработка LLM → Obsidian")
    print("=" * 60)

    # ── 7. Запись в Obsidian ────────────────────────────────────────
    obsidian_count = await process_assembled_sessions(session)
    print(f"{'*' * 50}\nЗаписано в Obsidian: {obsidian_count}")

    return obsidian_count


async def main():
    await init_db()

    async with AsyncSessionLocal() as session:

        # ── ФАЗА 1: Сбор данных ────────────────────────────────────
        assembled = await phase1(session)

        if assembled == 0:
            print("\nНет сессий для обработки. Завершаем.")
            return

        # ── ПАУЗА: Ожидание загрузки модели ────────────────────────
        print("\n" + "=" * 60)
        print(f"  Собрано {assembled} сессий для обработки.")
        print(f"  Текущая LLM модель: {settings.llm_model}")
        print()
        print("  Сейчас:")
        print("  1. Загрузите нужную модель в LM Studio")
        print("  2. Убедитесь что модель указана в config:")
        print(f"     LLM_MODEL_OFFLINE = {settings.LLM_MODEL_OFFLINE}")
        print("  3. Нажмите Enter для продолжения")
        print("=" * 60)

        input("\n>>> Нажмите Enter когда модель загружена... ")

        # ── ФАЗА 2: LLM обработка ──────────────────────────────────
        obsidian_count = await phase2(session)

        print(f"\n{'*' * 50}\nГотово! Записано {obsidian_count} заметок.")


if __name__ == "__main__":
    asyncio.run(main())
