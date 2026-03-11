from pathlib import Path
from datetime import datetime

import httpx

from src.config import settings
from src.logger import logger
from src.constants import MIME_MAP


def _validate_vault_path(path: str) -> None:
    """Проверяет что путь не выходит за пределы vault (защита от path traversal).
    Raises ValueError если путь содержит '..'. На будущее для онлайн.
    """
    if ".." in path.split("/"):
        raise ValueError(f"Недопустимый путь к файлу vault: '{path}'")


async def obsidian_get(path: str) -> str | None:
    """Читает файл из vault. Возвращает содержимое или None если не существует."""
    _validate_vault_path(path)
    async with httpx.AsyncClient(verify=False) as client:
        r = await client.get(
            f"{settings.OBSIDIAN_API_URL}/vault/{path}",
            headers={"Authorization": f"Bearer {settings.OBSIDIAN_API_KEY}"},
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.text


async def obsidian_create(path: str, content: str) -> None:
    """Создаёт или полностью заменяет файл в vault."""
    _validate_vault_path(path)
    async with httpx.AsyncClient(verify=False) as client:
        r = await client.put(
            f"{settings.OBSIDIAN_API_URL}/vault/{path}",
            headers={
                "Authorization": f"Bearer {settings.OBSIDIAN_API_KEY}",
                "Content-Type": "text/markdown",
            },
            content=content.encode("utf-8"),
        )
        r.raise_for_status()


async def obsidian_append(path: str, content: str) -> None:
    """Добавляет контент в конец существующего файла."""
    existing = await obsidian_get(path)
    if existing is None:
        await obsidian_create(path, content)
    else:
        await obsidian_create(path, existing + "\n" + content)


async def ensure_folder_exists(dest_folder: str) -> bool:
    async with httpx.AsyncClient(verify=False, timeout=30) as client:
        r = await client.get(
            f"{settings.OBSIDIAN_API_URL}/vault/{dest_folder}",
            headers={
                "Authorization": f"Bearer {settings.OBSIDIAN_API_KEY}"
            },
        )
        if r.status_code == 404:
            logger.info(f'Папка {dest_folder} не создана. Создаем.')
            await obsidian_create(
                f"{dest_folder}/info.md",
                f'Папка {dest_folder} была создана {datetime.now()}'
            )

async def obsidian_upload_image(photo_path: Path, filename: str, dest_folder: str) -> None:
    """Загружает изображение в vault/{dest_folder}/{filename}.

    dest_folder — папка назначения, например "attachments/photos/2026/03-мар".
    """
    await ensure_folder_exists(dest_folder)
    async with httpx.AsyncClient(verify=False, timeout=30) as client:
        with open(photo_path, "rb") as f:
            r = await client.put(
                f"{settings.OBSIDIAN_API_URL}/vault/{dest_folder}/{filename}",
                headers={
                    "Authorization": f"Bearer {settings.OBSIDIAN_API_KEY}",
                    "Content-Type": "image/jpeg",
                },
                content=f.read(),
            )
            r.raise_for_status()
    logger.info(f"Загружено фото: {dest_folder}/{filename}")


async def obsidian_upload_document(doc_path: Path, filename: str, dest_folder: str) -> None:
    """Загружает документ в vault/{dest_folder}/{filename}.

    dest_folder — папка назначения, например "attachments/documents/2026/03-мар".
    """
    await ensure_folder_exists(dest_folder)
    suffix = Path(filename).suffix.lower()
    content_type = MIME_MAP.get(suffix, "application/octet-stream")

    async with httpx.AsyncClient(verify=False, timeout=30) as client:
        with open(doc_path, "rb") as f:
            r = await client.put(
                f"{settings.OBSIDIAN_API_URL}/vault/{dest_folder}/{filename}",
                headers={
                    "Authorization": f"Bearer {settings.OBSIDIAN_API_KEY}",
                    "Content-Type": content_type,
                },
                content=f.read(),
            )
            r.raise_for_status()
    logger.info(f"Загружен документ: {dest_folder}/{filename}")


async def obsidian_list_files(folder: str) -> list[str]:
    """Возвращает список md-файлов в папке vault (полные пути от корня vault).

    Obsidian Local REST API возвращает имена файлов без префикса папки,
    поэтому мы добавляем folder/ к каждому пути.
    """
    async with httpx.AsyncClient(verify=False) as client:
        r = await client.get(
            f"{settings.OBSIDIAN_API_URL}/vault/{folder}/",
            headers={"Authorization": f"Bearer {settings.OBSIDIAN_API_KEY}"},
        )
        if r.status_code == 404:
            return []
        r.raise_for_status()
        data = r.json()
        files = data.get("files", [])
        result = []
        for item in files:
            path = item if isinstance(item, str) else item.get("path", "")
            if path.endswith(".md"):
                # API возвращает имена без папки — добавляем prefix
                if not path.startswith(f"{folder}/"):
                    path = f"{folder}/{path}"
                result.append(path)
        return result


async def obsidian_list_files_recursive(folder: str) -> list[str]:
    """Рекурсивно обходит папку и возвращает все .md файлы.

    Поддерживает вложенную структуру {folder}/{year}/{month}/*.md,
    а также обратную совместимость с плоскими файлами прямо в папке.
    Элементы без расширения считаются подпапками.
    """
    async with httpx.AsyncClient(verify=False) as client:
        r = await client.get(
            f"{settings.OBSIDIAN_API_URL}/vault/{folder}/",
            headers={"Authorization": f"Bearer {settings.OBSIDIAN_API_KEY}"},
        )
        if r.status_code == 404:
            return []
        r.raise_for_status()
        data = r.json()
        items = data.get("files", [])

    result = []
    for item in items:
        name = item if isinstance(item, str) else item.get("path", "")
        name = name.rstrip("/")
        if not name:
            continue
        basename = name.split("/")[-1]
        if "." in basename:
            # Файл — берём только .md
            if name.endswith(".md"):
                full = f"{folder}/{name}" if not name.startswith(f"{folder}/") else name
                result.append(full)
        else:
            # Нет расширения → подпапка, рекурсируем
            subdir = f"{folder}/{name}"
            result.extend(await obsidian_list_files_recursive(subdir))

    return result