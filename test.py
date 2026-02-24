import asyncio
import httpx
import subprocess
from config import settings

FILE_ID = "AwACAgIAAxkBAAMKaZ2XJLLIY3rTVtC9air6xn2jgU0AAnmMAAI4S-hI2Y1DFvkkz0U6BA"

async def download():
    async with httpx.AsyncClient(timeout=30) as client:
        # Получаем путь к файлу
        r = await client.get(
            f"https://api.telegram.org/bot{settings.BOT_TOKEN}/getFile",
            params={"file_id": FILE_ID}
        )
        file_path = r.json()["result"]["file_path"]
        
        # Скачиваем .ogg
        r = await client.get(
            f"https://api.telegram.org/file/bot{settings.BOT_TOKEN}/{file_path}"
        )
        with open("test_audio.ogg", "wb") as f:
            f.write(r.content)
        print("Скачано: test_audio.ogg")

asyncio.run(download())