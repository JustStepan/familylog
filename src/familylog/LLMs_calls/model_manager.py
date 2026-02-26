import asyncio
import httpx
from src.config import settings

# LM Studio API endpoint для управления моделями
# settings.LM_STUDIO_URL уже содержит /v1 — убираем его для models endpoint
LM_STUDIO_BASE = settings.LM_STUDIO_URL.rstrip("/v1").rstrip("/")
LM_STUDIO_MODELS_URL = f"{LM_STUDIO_BASE}/v1/models"


async def get_loaded_models() -> list[str]:
    """Возвращает список загруженных моделей."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(LM_STUDIO_MODELS_URL)
        r.raise_for_status()
        data = r.json()
        return [m["id"] for m in data.get("data", [])]


async def load_model(model_id: str, wait_seconds: int = 30) -> None:
    """Загружает модель в LM Studio и ждёт готовности."""
    print(f"  Загружаем модель: {model_id}...")

    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            LM_STUDIO_MODELS_URL,
            json={"model": model_id},
        )

    # Ждём пока модель загрузится
    for _ in range(wait_seconds):
        await asyncio.sleep(1)
        loaded = await get_loaded_models()
        if model_id in loaded:
            print(f"  Модель загружена: {model_id}")
            return

    raise TimeoutError(f"Модель {model_id} не загрузилась за {wait_seconds} секунд")


async def unload_model(model_id: str) -> None:
    """Выгружает модель из памяти."""
    print(f"  Выгружаем модель: {model_id}...")

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.delete(f"{LM_STUDIO_MODELS_URL}/{model_id}")
        if r.status_code not in (200, 404):
            r.raise_for_status()

    print(f"  Модель выгружена: {model_id}")


async def switch_model(unload_id: str, load_id: str) -> None:
    """Выгружает одну модель и загружает другую."""
    await unload_model(unload_id)
    await asyncio.sleep(3)  # пауза чтобы память освободилась
    await load_model(load_id)


async def ensure_model_loaded(model_id: str) -> None:
    """Загружает модель если она ещё не загружена."""
    loaded = await get_loaded_models()
    if model_id not in loaded:
        await load_model(model_id)