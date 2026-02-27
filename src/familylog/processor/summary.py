"""Генерация периодического summary по всем записям в vault.

Собирает заметки из notes/, diary/, calendar/, tasks/ за период
с момента последнего summary, отправляет в LLM для суммаризации,
сохраняет результат в vault/summaries/.
"""

import json
from datetime import datetime

import frontmatter as fm

from ..LLMs_calls.calls import llm_generate_summary
from .obsidian_writer import (
    obsidian_get,
    obsidian_create,
    obsidian_list_files,
    extract_json,
)

SUMMARY_MARKER_PATH = "_system/LAST_SUMMARY.md"
SUMMARY_FOLDERS = ("notes", "diary", "calendar", "tasks")


async def get_last_summary_time() -> datetime | None:
    """Читает время последнего summary из vault."""
    content = await obsidian_get(SUMMARY_MARKER_PATH)
    if not content:
        return None
    for line in content.split("\n"):
        if line.startswith("last_run:"):
            date_str = line.split(":", 1)[1].strip()
            try:
                return datetime.strptime(date_str, "%Y-%m-%d %H:%M")
            except ValueError:
                return None
    return None


async def save_last_summary_time(dt: datetime) -> None:
    """Сохраняет время последнего summary."""
    content = f"# Last Summary\n\nlast_run: {dt.strftime('%Y-%m-%d %H:%M')}\n"
    await obsidian_create(SUMMARY_MARKER_PATH, content)


async def collect_vault_content(since: datetime | None) -> dict[str, list[dict]]:
    """Собирает файлы из vault, созданные/обновлённые после since.

    Возвращает: {"notes": [{"path": ..., "title": ..., "content": ...}], ...}
    """
    result: dict[str, list[dict]] = {}

    for folder in SUMMARY_FOLDERS:
        files = await obsidian_list_files(folder)
        entries = []

        for filepath in files:
            raw = await obsidian_get(filepath)
            if not raw:
                continue

            # Проверяем дату через frontmatter
            try:
                post = fm.loads(raw)
                created_str = post.get("created", "")
                updated_str = post.get("updated", "")

                # Берём самую свежую дату
                file_date = None
                for ds in (updated_str, created_str):
                    if ds:
                        try:
                            file_date = datetime.strptime(str(ds), "%Y-%m-%d %H:%M")
                            break
                        except ValueError:
                            try:
                                file_date = datetime.strptime(str(ds), "%Y-%m-%d")
                            except ValueError:
                                continue

                # Если since задан — фильтруем по дате
                if since and file_date and file_date < since:
                    continue

                title = post.get("title", "") or filepath
                tags = post.get("tags", []) or []
            except Exception:
                title = filepath
                tags = []

            entries.append({
                "path": filepath,
                "title": str(title),
                "tags": tags,
                "content": raw,
            })

        if entries:
            result[folder] = entries

    return result


def format_content_for_llm(vault_data: dict[str, list[dict]], since: datetime | None) -> str:
    """Форматирует собранные данные для передачи в LLM."""
    period = f"с {since.strftime('%d.%m.%Y')}" if since else "за всё время"

    parts = [f"# Данные для summary ({period})\n"]

    folder_names = {
        "notes": "Заметки",
        "diary": "Дневник",
        "calendar": "Календарь",
        "tasks": "Задания",
    }

    for folder, entries in vault_data.items():
        section_name = folder_names.get(folder, folder)
        parts.append(f"\n## {section_name} ({len(entries)} записей)\n")

        for entry in entries:
            parts.append(f"### {entry['title']}")
            # Для summary достаточно содержания без frontmatter
            content = entry["content"]
            if content.startswith("---"):
                split = content.split("---", 2)
                if len(split) >= 3:
                    content = split[2].strip()
            # Ограничиваем длину одной записи
            if len(content) > 2000:
                content = content[:2000] + "\n...(обрезано)"
            parts.append(content)
            parts.append("")

    return "\n".join(parts)


async def generate_summary(since: datetime | None) -> dict:
    """Генерирует summary за период.

    Возвращает: {"summary_text": str, "filename": str, "content": str}
    """
    # Собираем контент из vault
    vault_data = await collect_vault_content(since)

    if not vault_data:
        return {
            "summary_text": "За указанный период новых записей не найдено.",
            "filename": None,
            "content": None,
        }

    # Считаем статистику
    total_entries = sum(len(v) for v in vault_data.values())
    period_str = f"с {since.strftime('%d.%m.%Y')}" if since else "за всё время"

    print(f"  Собрано {total_entries} записей {period_str}")
    for folder, entries in vault_data.items():
        print(f"    {folder}: {len(entries)}")

    # Форматируем для LLM
    llm_input = format_content_for_llm(vault_data, since)

    # Генерируем summary через LLM
    llm_output = llm_generate_summary(llm_input, since)
    output_data = json.loads(extract_json(llm_output))

    summary_text = output_data.get("summary_text", "")
    summary_content = output_data.get("content", "")

    # Генерируем имя файла
    now = datetime.now()
    filename = f"summaries/{now.strftime('%Y-%m-%d')}_summary.md"

    return {
        "summary_text": summary_text,
        "filename": filename,
        "content": summary_content,
    }


async def run_summary() -> dict:
    """Полный цикл: определить период → собрать → суммировать → сохранить.

    Возвращает dict с summary_text для отправки в Telegram.
    """
    now = datetime.now()

    # Определяем период
    since = await get_last_summary_time()
    if since:
        print(f"Последний summary: {since.strftime('%Y-%m-%d %H:%M')}")
    else:
        print("Первый запуск summary — собираем всё")

    # Генерируем summary
    result = await generate_summary(since)

    # Сохраняем в vault
    if result["filename"] and result["content"]:
        await obsidian_create(result["filename"], result["content"])
        print(f"  Сохранён: {result['filename']}")

    # Обновляем время последнего запуска
    await save_last_summary_time(now)

    return result
