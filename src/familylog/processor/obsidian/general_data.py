from datetime import datetime, timedelta

from src.config import settings
from src.constants import RUSSIAN_MONTHS
from src.logger import logger
from .api import obsidian_get


async def load_system_file(filename: str) -> str:
    """Загружает системный md файл из _system/ папки vault."""
    content = await obsidian_get(f"_system/{filename}")
    return content or f"# {filename}\n(file not found)"

# ─── Работа с контекстом ─────────────────────────────────────────────────────
def context_month_path(year: int, month: int) -> str:
    """Путь к месячному файлу контекста: _system/context/2026/03-мар.md"""
    mfolder = f"{month:02d}-{RUSSIAN_MONTHS[month - 1]}"
    return f"_system/context/{year}/{mfolder}.md"


def _iter_months_back(from_date: datetime, days: int):
    """Генерирует (year, month) от from_date назад на days дней (без повторов)."""
    cutoff = from_date - timedelta(days=days)
    seen = set()
    current = from_date
    while current >= cutoff:
        ym = (current.year, current.month)
        if ym not in seen:
            seen.add(ym)
            yield ym
        # Перейти на последний день предыдущего месяца
        current = current.replace(day=1) - timedelta(days=1)


def parse_context_before(content: str, before: datetime) -> str:
    """Берёт из контент-файла только записи СТАРШЕ before — предыдущий контекст."""
    lines = content.split("\n")
    include = False
    result = []
    for line in lines:
        if line.startswith("## "):
            date_str = line.replace("## ", "").strip()
            try:
                section_date = datetime.strptime(date_str, "%Y-%m-%d")
                include = section_date < before
            except ValueError:
                include = False
        if include:
            result.append(line)
    return "\n".join(result) if result else ""


def parse_current_context(content: str) -> str:
    """Парсит контент и возвращает только записи новее CONTEXT_MEMORY_DAYS."""
    cutoff = datetime.now() - timedelta(days=settings.CONTEXT_MEMORY_DAYS)
    lines = content.split("\n")
    include = False
    result = []
    for line in lines:
        if line.startswith("## "):
            date_str = line.replace("## ", "").strip()
            try:
                current_section_date = datetime.strptime(date_str, "%Y-%m-%d")
                include = current_section_date >= cutoff
            except ValueError as e:
                logger.debug(f"В context невалидная дата: {date_str}. Ошибка: {e}")
                include = False
        if include:
            result.append(line)
    return "\n".join(result) if result else "(no recent context)"


async def load_context_for_period(
    reference_date: datetime | None = None,
) -> str:
    """Загружает контекст из месячных файлов за последние CONTEXT_MEMORY_DAYS дней.
    Читает только нужные файлы: текущий месяц + предыдущие в пределах окна.
    Если файл месяца не существует — пропускает без ошибки.
    """
    if reference_date is None:
        reference_date = datetime.now()

    parts = []
    for year, month in _iter_months_back(reference_date, settings.CONTEXT_MEMORY_DAYS):
        path = context_month_path(year, month)
        content = await obsidian_get(path)
        if content:
            parts.append(content)

    if not parts:
        return "(no recent context)"

    combined = "\n\n".join(parts)
    return parse_current_context(combined)


async def load_context_before(before: datetime) -> str:
    """Загружает контекст из месяцев ДО before_date (для pre-period контекста в summary).

    Смотрит на 3 предыдущих месяца от before и возвращает записи старше before.
    """
    parts = []
    # Начинаем с предыдущего месяца относительно before
    cursor = before.replace(day=1) - timedelta(days=1)
    for _ in range(3):
        path = context_month_path(cursor.year, cursor.month)
        content = await obsidian_get(path)
        if content:
            filtered = parse_context_before(content, before)
            if filtered:
                parts.append(filtered)
        cursor = cursor.replace(day=1) - timedelta(days=1)

    return "\n\n".join(parts) if parts else ""
