from datetime import datetime, timedelta

from src.config import settings
from src.logger import logger
from . import api


async def load_system_file(filename: str) -> str:
    """Загружает системный md файл из _system/ папки vault."""
    content = await api.obsidian_get(f"_system/{filename}")
    return content or f"# {filename}\n(file not found)"


def parse_current_context(content: str) -> str:
    """Парсит CURRENT_CONTEXT.md и возвращает только записи новее CONTEXT_MEMORY_DAYS."""
    cutoff = datetime.now() - timedelta(days=settings.CONTEXT_MEMORY_DAYS)
    lines = content.split("\n")
    include = False
    result = []
    for line in lines:
        if line.startswith("## "):
            date_str = line.replace("## ", "").strip()
            try:
                current_section_date = datetime.strptime(date_str, "%Y-%m-%d")
                include = current_section_date >= cutoff  # ← внутри try
            except ValueError as e:
                logger.debug(f'В CURRENT_CONTEXT невалидная дата: {date_str}. Ошибка: {e}')
                include = False  # ← явно сбрасываем
        if include:
            result.append(line)
    return "\n".join(result) if result else "(no recent context)"


async def load_base_context() -> dict[str, str]:
    """Загружает общие системные файлы (без intent-specific)."""
    agent_config = await load_system_file("AGENT_CONFIG.md")
    family_memory = await load_system_file("FAMILY_MEMORY.md")
    tags_glossary = await load_system_file("TAGS_GLOSSARY.md")
    current_context_raw = await load_system_file("CURRENT_CONTEXT.md")
    current_context = parse_current_context(current_context_raw)

    return {
        "agent_config": agent_config,
        "family_memory": family_memory,
        "tags_glossary": tags_glossary,
        "current_context": current_context,
    }
