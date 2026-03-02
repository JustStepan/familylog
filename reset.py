import asyncio

from sqlalchemy import delete, select

from src.familylog.storage.database import AsyncSessionLocal
from src.familylog.storage.models import Message, Session, Setting


async def main(numb_old: str, numb_new: str):
    async with AsyncSessionLocal() as session:
        # Очищаем таблицы но сохраняем last_update_id
        await session.execute(delete(Message))
        await session.execute(delete(Session))

        # Change last_id_in_settings
        query = await session.execute(select(Setting).where(Setting.value == numb_old))
        last_id = query.scalar_one_or_none()
        last_id.value = numb_new
        await session.commit()
        print(f"БД очищена, last_update_id изменен с {numb_old} на {numb_new}")

if __name__ == "__main__":
    asyncio.run(main('644948417', '644948413'))