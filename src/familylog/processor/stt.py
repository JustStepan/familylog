import asyncio
import subprocess
from pathlib import Path

import httpx
import onnx_asr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from ..storage.models import Message

# Папка для временных файлов — удаляем после обработки
MEDIA_DIR = Path("media/voice")

# Модель загружается один раз при импорте модуля
# Это важно — загрузка занимает несколько секунд
_model = None


def get_model():
    """Ленивая загрузка модели — только при первом вызове."""
    global _model
    if _model is None:
        _model = onnx_asr.load_model(
            "nemo-conformer-tdt",
            settings.MODEL_PATH,
            quantization="int8"
        )
    return _model


async def download_voice(file_id: str) -> Path:
    """Скачивает голосовой файл с Telegram по file_id.
    Возвращает путь к сохранённому .ogg файлу."""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=30) as client:
        # Шаг 1: получаем путь к файлу на серверах Telegram
        r = await client.get(
            f"https://api.telegram.org/bot{settings.BOT_TOKEN}/getFile",
            params={"file_id": file_id}
        )
        r.raise_for_status()
        file_path = r.json()["result"]["file_path"]

        # Шаг 2: скачиваем сам файл
        r = await client.get(
            f"https://api.telegram.org/file/bot{settings.BOT_TOKEN}/{file_path}"
        )
        r.raise_for_status()

    ogg_path = MEDIA_DIR / f"{file_id}.ogg"
    ogg_path.write_bytes(r.content)
    return ogg_path


def convert_to_wav(ogg_path: Path) -> Path:
    """Конвертирует .ogg в .wav через ffmpeg.
    Parakeet требует: 16kHz, моно, PCM."""
    wav_path = ogg_path.with_suffix(".wav")

    result = subprocess.run(
        [
            "ffmpeg", "-y",          # -y перезаписать если существует
            "-i", str(ogg_path),
            "-ar", "16000",          # частота дискретизации 16kHz
            "-ac", "1",              # моно канал
            str(wav_path)
        ],
        capture_output=True,         # не выводить в терминал
    )

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {result.stderr.decode()}")

    return wav_path


def transcribe(wav_path: Path) -> str:
    """Запускает STT модель и возвращает текст."""
    model = get_model()
    # recognize() — синхронный вызов, возвращает строку
    return model.recognize(str(wav_path))


def cleanup(ogg_path: Path, wav_path: Path) -> None:
    """Удаляет временные файлы после обработки."""
    ogg_path.unlink(missing_ok=True)
    wav_path.unlink(missing_ok=True)


async def process_voice_messages(session: AsyncSession) -> int:
    """Основная функция обработки голосовых сообщений.
    Возвращает количество обработанных сообщений."""

    # Берём все pending голосовые сообщения
    result = await session.execute(
        select(Message).where(
            Message.message_type == "voice",
            Message.status == "pending"
        )
    )
    messages = result.scalars().all()

    if not messages:
        return 0

    processed_count = 0

    for msg in messages:
        ogg_path = None
        wav_path = None

        try:
            print(f"Обрабатываем сообщение {msg.id}...")

            # Скачиваем файл
            ogg_path = await download_voice(msg.raw_content)

            # Конвертируем
            wav_path = convert_to_wav(ogg_path)

            # Транскрибируем
            text = transcribe(wav_path)
            print(f"  Транскрипция: {text[:50]}...")

            # Обновляем запись в БД
            msg.text_content = text
            msg.status = "transcribed"
            await session.commit()

            processed_count += 1

        except Exception as e:
            print(f"  Ошибка: {e}")
            msg.status = "error_stt"
            await session.commit()

        finally:
            # Удаляем временные файлы в любом случае
            if ogg_path:
                cleanup(ogg_path, wav_path or ogg_path.with_suffix(".wav"))

    return processed_count