import asyncio
from src.familylog.storage.database import init_db, AsyncSessionLocal
from src.familylog.processor.stt import process_voice_messages
from src.familylog.processor.vision import process_photo_messages


async def main():
    await init_db()

    async with AsyncSessionLocal() as session:
        voice_count = await process_voice_messages(session)
        print(f"Обработано голосовых сообщений: {voice_count}")

        photo_count = await process_photo_messages(session)
        print(f"Обработано голосовых сообщений: {photo_count}")


if __name__ == "__main__":
    asyncio.run(main())