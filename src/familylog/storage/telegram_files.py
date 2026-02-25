from pathlib import Path

import httpx

from src.config import settings


async def download_file(file_id: str, dest_dir: Path, extension: str) -> Path:
    """Скачивает файлы с Telegram по file_id.
    Возвращает путь к сохранённому файлу."""
    dest_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=30) as client:
        # Шаг 1: получаем путь к файлу на серверах Telegram
        r = await client.get(
            f"https://api.telegram.org/bot{settings.BOT_TOKEN}/getFile",
            params={"file_id": file_id}
        )
        r.raise_for_status()
        telegram_path = r.json()["result"]["file_path"]

        # Шаг 2: скачиваем сам файл
        r = await client.get(
            f"https://api.telegram.org/file/bot{settings.BOT_TOKEN}/{telegram_path}"
        )
        r.raise_for_status()
        print(r)

    file_path = dest_dir / f"{file_id}.{extension}"
    file_path.write_bytes(r.content)
    return file_path