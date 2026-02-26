import asyncio
import httpx
from src.config import settings

LM_STUDIO_BASE = settings.LM_STUDIO_BASE_URL.rstrip("/")
LM_STUDIO_MODELS_LIST = f"{LM_STUDIO_BASE}/api/v1/models"
LM_STUDIO_LOAD_URL    = f"{LM_STUDIO_BASE}/api/v1/models/load"
LM_STUDIO_UNLOAD_URL  = f"{LM_STUDIO_BASE}/api/v1/models/unload"


async def get_loaded_models() -> list[str]:
    """Возвращает список загруженных моделей."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(LM_STUDIO_MODELS_LIST)
        r.raise_for_status()
        data = r.json()
        loaded = []
        for m in data.get("models", []):
            for instance in m.get("loaded_instances", []):
                loaded.append(instance["id"])
        return loaded


async def load_model(model_id: str, wait_seconds: int = 60) -> None:
    """Загружает модель в LM Studio и ждёт готовности."""
    print(f"  Загружаем модель: {model_id}...")

    async with httpx.AsyncClient(timeout=120) as client:
        await client.post(LM_STUDIO_LOAD_URL, json={"model": model_id})

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
        r = await client.post(
            LM_STUDIO_UNLOAD_URL,
            json={"instance_id": model_id},
        )
        if r.status_code not in (200, 404):
            r.raise_for_status()

    print(f"  Модель выгружена: {model_id}")


async def switch_model(unload_id: str, load_id: str) -> None:
    """Выгружает одну модель и загружает другую."""
    await unload_model(unload_id)
    await asyncio.sleep(3)
    await load_model(load_id)


async def ensure_model_loaded(model_id: str) -> None:
    """Загружает модель если она ещё не загружена."""
    loaded = await get_loaded_models()
    if model_id not in loaded:
        await load_model(model_id)