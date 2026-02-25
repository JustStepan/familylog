import base64
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..schema.llm import PhotoOutput

from ..LLMs_calls.calls import llm_process_photo
from ..storage.models import Message
from ..storage.telegram_files import download_file


MEDIA_DIR = Path("media/images")


def image_to_base64(filepath: Path) -> str:
    with open(filepath, 'rb') as f:
        base64_bytes = base64.b64encode(f.read())
        base64_string = base64_bytes.decode('ascii')
        return base64_string
    

async def process_photo_messages(session: AsyncSession) -> int:
    """Функция извлечение фото из базы данных."""

    # Берём все pending фото сообщения
    result = await session.execute(
        select(Message).where(
            Message.message_type == "photo",
            Message.status == "pending"
        )
    )
    messages = result.scalars().all()

    if not messages:
        return 0

    processed_count = 0

    for msg in messages:
        photo_path = None
        photo_caption = msg.caption or None

        try:
            print(f"Обрабатываем фото сообщение {msg.id}...")

            # Скачиваем файл
            photo_path = await download_file(msg.raw_content, MEDIA_DIR, "jpeg")

            # получаем описание
            base64_str = image_to_base64(photo_path)
            description = llm_process_photo(base64_str, photo_caption)

            # Обновляем запись в БД
            output = PhotoOutput.model_validate_json(description)
            msg.caption = output.caption  # обновляем заголовок
            msg.text_content = f"Заголовок: {output.caption}. Описание: {output.description}"
            print(f"  Описание LLM: {msg.text_content[:100]}...")
            msg.status = "described"
            await session.commit()

            processed_count += 1

        except Exception as e:
            print(f"  Ошибка: {e}")
            msg.status = "error_stt"
            await session.commit()

    return processed_count