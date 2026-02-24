import asyncio
from src.familylog.storage.database import init_db, AsyncSessionLocal
from src.familylog.processor.stt import process_voice_messages


async def main():
    await init_db()

    async with AsyncSessionLocal() as session:
        count = await process_voice_messages(session)
        print(f"Обработано голосовых сообщений: {count}")


if __name__ == "__main__":
    asyncio.run(main())