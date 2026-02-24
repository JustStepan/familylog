import asyncio
from src.familylog.storage.database import init_db

async def main():
    await init_db()
    print("БД инициализирована успешно")

if __name__ == "__main__":
    asyncio.run(main())