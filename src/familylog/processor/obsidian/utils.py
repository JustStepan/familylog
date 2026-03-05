import re
from datetime import datetime, timedelta
from slugify import slugify

from src.constants import INTENT_FOLDERS, RUSSIAN_MONTHS


def resolve_author(author_id: int, family_memory: str) -> str:
    pattern = rf'\b{author_id}\b'
    blocks = family_memory.split("### ")
    for block in blocks:
        if re.search(pattern, block):
            name = block.split("\n")[0].strip()
            if name:
                return name
    return f"user_{author_id}"


def get_monday_of_week(dt: datetime) -> datetime:
    """Возвращает понедельник недели, содержащей dt."""
    return dt - timedelta(days=dt.weekday())


def generate_filename(title: str, intent: str, created_at: datetime) -> str:
    """Генерирует путь файла в Obsidian vault.

    Формат:
      notes/Slug_title_27-фев-26.md      (slug с заглавной, время в frontmatter)
      diary/27-фев-26_дневник.md          (один файл на день, append)
      calendar/Slug_27-фев-26.md          (отдельный файл на событие)
      tasks/неделя_24-фев-26.md           (один файл на неделю, дата = понедельник)
    """
    folder = INTENT_FOLDERS.get(intent, "notes")

    # Календарь: отдельный файл на каждое событие (как notes)
    if intent == "calendar":
        slug = slugify(title, max_length=50, separator="_")
        slug_display = (slug[0].upper() + slug[1:]) if slug else "Sobytie"
        day = f"{created_at.day:02d}"
        month = RUSSIAN_MONTHS[created_at.month - 1]
        year = f"{created_at.year % 100:02d}"
        return f"{folder}/{slug_display}_{day}-{month}-{year}.md"

    # Задания: один файл на неделю (дата = понедельник)
    if intent == "task":
        monday = get_monday_of_week(created_at)
        day = f"{monday.day:02d}"
        month = RUSSIAN_MONTHS[monday.month - 1]
        year = f"{monday.year % 100:02d}"
        return f"{folder}/неделя_{day}-{month}-{year}.md"

    day = f"{created_at.day:02d}"
    month = RUSSIAN_MONTHS[created_at.month - 1]
    year = f"{created_at.year % 100:02d}"
    date_part = f"{day}-{month}-{year}"

    if intent == "diary":
        # Дневник: без времени — один файл на день, append по дате
        return f"{folder}/{date_part}_дневник.md"

    # note и любой fallback — slug первым, дата после, время в frontmatter
    slug = slugify(title, max_length=50, separator="_")
    if not slug:
        slug = "zametka"
    # Первая буква slug с заглавной для читаемости
    slug_display = slug[0].upper() + slug[1:] if slug else "Zametka"
    return f"{folder}/{slug_display}_{date_part}.md"