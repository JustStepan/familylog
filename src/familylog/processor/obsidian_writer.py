import json
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..LLMs_calls.calls import llm_process_session
from ..storage.models import Session
from src.config import settings

# Сколько дней истории загружать из CURRENT_CONTEXT.md
CONTEXT_MEMORY_DAYS: int = 90


# ─── Obsidian API ────────────────────────────────────────────────────────────

async def obsidian_get(path: str) -> str | None:
    """Читает файл из vault. Возвращает содержимое или None если не существует."""
    async with httpx.AsyncClient() as client:
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
    async with httpx.AsyncClient() as client:
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


# ─── Загрузка системных файлов ───────────────────────────────────────────────

async def load_system_file(filename: str) -> str:
    """Загружает системный md файл из _system/ папки vault."""
    content = await obsidian_get(f"_system/{filename}")
    return content or f"# {filename}\n(file not found)"


def parse_current_context(content: str) -> str:
    """Парсит CURRENT_CONTEXT.md и возвращает только записи новее CONTEXT_MEMORY_DAYS."""
    cutoff = datetime.now() - timedelta(days=CONTEXT_MEMORY_DAYS)
    lines = content.split("\n")

    result = []
    current_section_date = None
    current_section_lines = []
    include_section = False

    for line in lines:
        # Ищем заголовки вида ## YYYY-MM-DD
        if line.startswith("## "):
            # Сохраняем предыдущую секцию если она попала в окно
            if include_section and current_section_lines:
                result.extend(current_section_lines)

            # Парсим дату новой секции
            date_str = line.replace("## ", "").strip()
            try:
                current_section_date = datetime.strptime(date_str, "%Y-%m-%d")
                include_section = current_section_date >= cutoff
            except ValueError:
                include_section = False

            current_section_lines = [line]

        elif current_section_date is not None:
            current_section_lines.append(line)

    # Не забываем последнюю секцию
    if include_section and current_section_lines:
        result.extend(current_section_lines)

    return "\n".join(result) if result else "(no recent context)"


async def load_context() -> dict[str, str]:
    """Загружает все системные файлы для передачи в LLM."""
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


# ─── Определение автора ──────────────────────────────────────────────────────

def resolve_author(author_id: int, family_memory: str) -> str:
    """Ищет имя автора в FAMILY_MEMORY по Telegram ID."""
    for line in family_memory.split("\n"):
        if str(author_id) in line:
            # Ищём имя в строках выше — заголовок ### Имя
            pass

    # Простой парсинг: ищем блок с нужным telegram_id
    blocks = family_memory.split("### ")
    for block in blocks:
        if str(author_id) in block:
            name = block.split("\n")[0].strip()
            if name:
                return name

    return f"user_{author_id}"


# ─── Запись в Obsidian ───────────────────────────────────────────────────────

async def write_to_obsidian(llm_output: dict) -> None:
    """Записывает результат LLM в vault согласно action."""
    filename = llm_output["filename"]
    content = llm_output["content"]
    action = llm_output.get("action", "create")

    if action == "create":
        await obsidian_create(filename, content)
        print(f"  Создан файл: {filename}")

    elif action == "append":
        await obsidian_append(filename, content)
        print(f"  Дополнен файл: {filename}")


# ─── Основная функция ────────────────────────────────────────────────────────

async def process_assembled_sessions(session: AsyncSession) -> int:
    """Берёт assembled сессии и записывает их в Obsidian.
    Возвращает количество обработанных сессий."""

    result = await session.execute(
        select(Session).where(Session.status == "assembled")
    )
    sessions = result.scalars().all()

    if not sessions:
        return 0

    # Загружаем системные файлы один раз для всех сессий
    context = await load_context()

    processed_count = 0

    for s in sessions:
        try:
            print(f"Записываем сессию {s.id} (intent={s.intent})...")

            # Определяем автора
            author_name = resolve_author(s.author_id, context["family_memory"])

            # Передаём в LLM
            llm_output = llm_process_session(
                assembled_content=s.assembled_content,
                intent=s.intent,
                author_name=author_name,
                created_at=s.opened_at,
                context=context,
            )

            # Парсим JSON ответ
            output_data = json.loads(llm_output)

            # Записываем в Obsidian
            await write_to_obsidian(output_data)

            # Обновляем статус сессии
            s.status = "processed"
            await session.commit()

            processed_count += 1

        except Exception as e:
            print(f"  Ошибка сессии {s.id}: {e}")
            s.status = "error_obsidian"
            await session.commit()

    return processed_count
