import asyncio

from sqlalchemy import delete

from src.familylog.storage.database import AsyncSessionLocal
from src.familylog.storage.models import Message, Session


async def main():
    async with AsyncSessionLocal() as session:
        # Очищаем таблицы но сохраняем last_update_id
        await session.execute(delete(Message))
        await session.execute(delete(Session))
        await session.commit()
        print("БД очищена, last_update_id сохранён")

if __name__ == "__main__":
    asyncio.run(main())