import base64
from typing import Optional
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..storage.models import Message
from ..storage.telegram_files import download_file
from openai import OpenAI



client = OpenAI(
    base_url="http://localhost:1234/v1",
    api_key="dummy-key",
)


MEDIA_DIR = Path("media/images")


def llm_process_photo(base64_str: str, capture: Optional[str]) -> str:
    capture_prompt = ''
    if capture:
        capture_prompt = f'Заголовок фотографии {capture} - учитывай это при составлении описания'

    try:
        response = client.chat.completions.create(
            model='zai-org/glm-4.6v-flash',
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Представь краткое, но точное описание фотографии. {capture_prompt}"},
                        
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_str}"
                            }
                        }
                    ]
                }
            ],
            temperature=0.1,
            max_tokens=300,
        )
        return response.choices[0].message.content

    except Exception as e:
        return f"Ошибка API: {e}"

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
        photo_capture = msg.caption or None

        try:
            print(f"Обрабатываем фото сообщение {msg.id}...")

            # Скачиваем файл
            photo_path = await download_file(msg.raw_content, MEDIA_DIR, "jpeg")

            # получаем описание
            base64_str = image_to_base64(photo_path)
            description = llm_process_photo(base64_str, photo_capture)

            print(f"  Описание: {description[:50]}...")

            # Обновляем запись в БД
            msg.text_content = description
            msg.status = "described"
            await session.commit()

            processed_count += 1

        except Exception as e:
            print(f"  Ошибка: {e}")
            msg.status = "error_stt"
            await session.commit()

        # finally:
            # Удаляем временные файлы в любом случае
            # if photo_path:
            #     cleanup(photo_path)

    return processed_count