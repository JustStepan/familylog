import re
from datetime import datetime, timedelta
from slugify import slugify

from src.constants import INTENT_FOLDERS, RUSSIAN_MONTHS


def month_folder(dt: datetime) -> str:
    """Возвращает имя папки месяца: '03-мар', '12-дек' и т.д."""
    return f"{dt.month:02d}-{RUSSIAN_MONTHS[dt.month - 1]}"


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

    Структура: {folder}/{year}/{MM-месяц}/{filename}

    Примеры:
      notes/2026/03-мар/Slug_title_10-мар-26.md
      diary/2026/03-мар/10-мар-26_дневник.md
      calendar/2026/03-мар/Slug_10-мар-26.md
      tasks/2026/03-мар/неделя_10-мар-26.md
    """
    folder = INTENT_FOLDERS.get(intent, "notes")

    # Задания: один файл на неделю — папка и дата по понедельнику
    if intent == "task":
        monday = get_monday_of_week(created_at)
        prefix = f"{folder}/{monday.year}/{month_folder(monday)}"
        day = f"{monday.day:02d}"
        month = RUSSIAN_MONTHS[monday.month - 1]
        year = f"{monday.year % 100:02d}"
        return f"{prefix}/неделя_{day}-{month}-{year}.md"

    prefix = f"{folder}/{created_at.year}/{month_folder(created_at)}"
    day = f"{created_at.day:02d}"
    month = RUSSIAN_MONTHS[created_at.month - 1]
    year = f"{created_at.year % 100:02d}"
    date_part = f"{day}-{month}-{year}"

    # Календарь: отдельный файл на каждое событие
    if intent == "calendar":
        slug = slugify(title, max_length=50, separator="_")
        slug_display = (slug[0].upper() + slug[1:]) if slug else "Sobytie"
        return f"{prefix}/{slug_display}_{date_part}.md"

    # Дневник: один файл на день, append
    if intent == "diary":
        return f"{prefix}/{date_part}_дневник.md"

    # note и любой fallback
    slug = slugify(title, max_length=50, separator="_")
    if not slug:
        slug = "zametka"
    slug_display = slug[0].upper() + slug[1:] if slug else "Zametka"
    return f"{prefix}/{slug_display}_{date_part}.md"