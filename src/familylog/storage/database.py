from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from .models import Base
from ..config import settings


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=True  # убрать в продакшене
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False
)


async def init_db() -> None:
    """Создаёт все таблицы при старте приложения."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    """Dependency для получения сессии с автоматическим закрытием."""
    async with AsyncSessionLocal() as session:
        yield session