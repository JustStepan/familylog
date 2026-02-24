import asyncio
from src.familylog.storage.database import init_db, AsyncSessionLocal
from src.familylog.collector.telegram import collect_messages


async def main():
    await init_db()
    
    async with AsyncSessionLocal() as session:
        count = await collect_messages(session)
        print(f"Собрано новых сообщений: {count}")


if __name__ == "__main__":
    asyncio.run(main())