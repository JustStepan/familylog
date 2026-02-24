import asyncio
from src.familylog.storage.database import init_db, AsyncSessionLocal
from src.familylog.collector.telegram import collect_messages


async def main():
    await init_db()
    
    # async with AsyncSessionLocal() as session:
    #     import httpx
    #     from src.config import settings
    #     async with httpx.AsyncClient(timeout=30.0) as client:
    #         r = await client.get(
    #             f"https://api.telegram.org/bot{settings.BOT_TOKEN}/getUpdates",
    #             params={"offset": 0, "limit": 5}
    #         )
    #         print(r.json())

async def main():
    await init_db()
    
    async with AsyncSessionLocal() as session:
        count = await collect_messages(session)
        print(f"Собрано новых сообщений: {count}")


if __name__ == "__main__":
    asyncio.run(main())