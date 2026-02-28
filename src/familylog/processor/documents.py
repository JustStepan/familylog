import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..storage.models import Message
from ..storage.telegram_files import download_file

logger = logging.getLogger(__name__)

MEDIA_DIR = Path("media/documents")


async def process_document_messages(session: AsyncSession) -> int:
    """Скачивает документы из Telegram и формирует text_content из метаданных.

    Не извлекает содержимое файлов — только сохраняет и создаёт описание
    на основе имени файла, MIME-типа и caption.
    """
    result = await session.execute(
        select(Message).where(
            Message.message_type == "document",
            Message.status == "pending",
        )
    )
    messages = result.scalars().all()

    if not messages:
        return 0

    processed_count = 0

    for msg in messages:
        try:
            original_name = msg.document_filename or "unknown_file"
            extension = Path(original_name).suffix.lstrip(".") or "bin"

            logger.info("Обрабатываем документ %d: %s...", msg.id, original_name)

            # Скачиваем файл из Telegram
            file_path = await download_file(msg.raw_content, MEDIA_DIR, extension)

            # Формируем описание из метаданных (без чтения содержимого)
            desc_parts = [f"Файл: {original_name}"]
            if msg.document_mime_type:
                desc_parts.append(f"Тип: {msg.document_mime_type}")
            if msg.caption:
                desc_parts.append(f"Подпись: {msg.caption}")

            msg.text_content = ". ".join(desc_parts)
            msg.status = "described"
            await session.commit()

            processed_count += 1
            logger.info("Скачан: %s", file_path)

        except Exception as e:
            logger.error("Ошибка документа %d: %s", msg.id, e)
            msg.status = "error_doc"
            await session.commit()

    return processed_count
