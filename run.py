import asyncio

from src.familylog.collector.telegram import close_all_open_sessions, collect_messages
from src.familylog.processor.assembler import assemble_sessions
from src.familylog.storage.database import init_db, AsyncSessionLocal
from src.familylog.processor.stt import process_voice_messages
from src.familylog.processor.vision import process_photo_messages


async def main():
    await init_db()
    async with AsyncSessionLocal() as session:
        collected = await collect_messages(session)      # 1. собрать новые
        print(f"Собрано сообщений: {collected}")

        voice_count = await process_voice_messages(session)   # 2. обработать
        print(f"Голосовых: {voice_count}")

        photo_count = await process_photo_messages(session)
        print(f"Фото: {photo_count}")

        closed = await close_all_open_sessions(session)  # 3. закрыть все open
        print(f"Закрыто сессий: {closed}")

        assembled = await assemble_sessions(session)     # 4. собрать
        print(f"Собрано сессий: {assembled}")


if __name__ == "__main__":
    asyncio.run(main())