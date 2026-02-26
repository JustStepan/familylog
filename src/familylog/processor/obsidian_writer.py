import json
from pathlib import Path
from datetime import datetime, timedelta
import frontmatter as fm

import httpx
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..LLMs_calls.calls import llm_process_session
from ..storage.models import Session, Message
from src.config import settings

# ─── Obsidian API ────────────────────────────────────────────────────────────

async def obsidian_get(path: str) -> str | None:
    """Читает файл из vault. Возвращает содержимое или None если не существует."""
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


async def obsidian_upload_image(photo_path: Path, filename: str) -> None:
    """Загружает изображение в vault/attachments/."""
    async with httpx.AsyncClient(verify=False, timeout=30) as client:
        with open(photo_path, "rb") as f:
            r = await client.put(
                f"{settings.OBSIDIAN_API_URL}/vault/attachments/{filename}",
                headers={
                    "Authorization": f"Bearer {settings.OBSIDIAN_API_KEY}",
                    "Content-Type": "image/jpeg",
                },
                content=f.read(),
            )
            r.raise_for_status()
    print(f"  Загружено фото: {filename}")

# ─── Загрузка системных файлов ───────────────────────────────────────────────

async def load_system_file(filename: str) -> str:
    """Загружает системный md файл из _system/ папки vault."""
    content = await obsidian_get(f"_system/{filename}")
    return content or f"# {filename}\n(file not found)"


def parse_current_context(content: str) -> str:
    """Парсит CURRENT_CONTEXT.md и возвращает только записи новее CONTEXT_MEMORY_DAYS."""
    cutoff = datetime.now() - timedelta(days=settings.CONTEXT_MEMORY_DAYS)
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


# ─── Генерация имён файлов ────────────────────────────────────────────────

RUSSIAN_MONTHS = [
    "янв", "фев", "мар", "апр", "май", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
]

INTENT_FOLDERS = {
    "note": "notes",
    "diary": "diary",
    "calendar": "calendar",
    "reminder": "reminders",
}


def generate_filename(title: str, intent: str, created_at: datetime) -> str:
    """Генерирует путь файла в Obsidian vault.

    Формат: notes/26-фев-26(22:38)_slug.md
    Дневник: diary/26-фев-26(22:38)_дневник.md
    Календарь: calendar/2026-02.md
    Напоминания: reminders/reminders.md
    """
    folder = INTENT_FOLDERS.get(intent, "notes")

    if intent == "calendar":
        return f"{folder}/{created_at.strftime('%Y-%m')}.md"

    if intent == "reminder":
        return f"{folder}/reminders.md"

    day = f"{created_at.day:02d}"
    month = RUSSIAN_MONTHS[created_at.month - 1]
    year = f"{created_at.year % 100:02d}"
    time_str = f"{created_at.hour:02d}:{created_at.minute:02d}"
    date_part = f"{day}-{month}-{year}({time_str})"

    if intent == "diary":
        return f"{folder}/{date_part}_дневник.md"

    # note и любой fallback
    slug = slugify(title, max_length=50, separator="_")
    if not slug:
        slug = "zametka"
    return f"{folder}/{date_part}_{slug}.md"


# ─── Обновление системных файлов ──────────────────────────────────────────

async def update_current_context(context_summary: str) -> None:
    """Добавляет краткое описание записи в CURRENT_CONTEXT.md."""
    if not context_summary:
        return

    path = "_system/CURRENT_CONTEXT.md"
    content = await obsidian_get(path)
    today_header = f"## {datetime.now().strftime('%Y-%m-%d')}"

    if content is None:
        content = f"# Current Context\n\n{today_header}\n- {context_summary}\n"
        await obsidian_create(path, content)
        return

    if today_header in content:
        # Сегодня — всегда последняя секция, дописываем в конец
        content = content.rstrip() + f"\n- {context_summary}\n"
    else:
        content = content.rstrip() + f"\n\n{today_header}\n- {context_summary}\n"

    await obsidian_create(path, content)
    print(f"  Обновлён CURRENT_CONTEXT: {context_summary[:60]}...")


async def update_tags_glossary(tags: list[str]) -> None:
    """Добавляет новые теги в TAGS_GLOSSARY.md в секцию 'Автодобавленные'."""
    if not tags:
        return

    path = "_system/TAGS_GLOSSARY.md"
    content = await obsidian_get(path)
    if content is None:
        return

    # Собираем существующие теги
    existing_tags = set()
    for line in content.split("\n"):
        for word in line.strip().split():
            if word.startswith("#") and not word.startswith("##"):
                existing_tags.add(word.rstrip("—:,."))

    new_tags = [t for t in tags if t not in existing_tags]
    if not new_tags:
        return

    auto_section = "## Автодобавленные"
    new_lines = "\n".join(f"- {tag}" for tag in new_tags)

    if auto_section in content:
        content = content.rstrip() + "\n" + new_lines + "\n"
    else:
        content = content.rstrip() + f"\n\n{auto_section}\n{new_lines}\n"

    await obsidian_create(path, content)
    print(f"  Новые теги в глоссарии: {new_tags}")


async def update_family_memory(new_people: list[str]) -> None:
    """Добавляет новых людей в FAMILY_MEMORY.md."""
    if not new_people:
        return

    path = "_system/FAMILY_MEMORY.md"
    content = await obsidian_get(path)
    if content is None:
        return

    people_to_add = [p for p in new_people if p not in content]
    if not people_to_add:
        return

    new_entries = "\n".join(
        f"### {person}\n- Упомянут(а) в заметках\n" for person in people_to_add
    )

    # Ищем секцию друзей (может быть на русском или английском)
    friends_markers = ["## Friends and acquaintances", "## Друзья и знакомые"]
    has_friends = any(m in content for m in friends_markers)

    if has_friends:
        content = content.rstrip() + "\n\n" + new_entries + "\n"
    else:
        content = content.rstrip() + "\n\n## Друзья и знакомые\n\n" + new_entries + "\n"

    await obsidian_create(path, content)
    print(f"  Новые люди в FAMILY_MEMORY: {people_to_add}")


# ─── Запись в Obsidian ───────────────────────────────────────────────────────

async def update_diary_authors(path: str, new_author: str) -> None:
    content = await obsidian_get(path)
    if not content:
        return
    post = fm.loads(content)
    authors = post.get("authors", [])
    if new_author not in authors:
        authors.append(new_author)
        post["authors"] = authors
        post["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        await obsidian_create(path, fm.dumps(post))


def strip_frontmatter(content: str) -> str:
    content = content.strip()
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            content = parts[2].strip()
    # Убираем дублирующийся заголовок h1
    lines = content.split("\n")
    lines = [l for l in lines if not l.startswith("# ")]
    return "\n".join(lines).strip()


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
            # Неизвестный intent → note
            intent = s.intent if s.intent != "unknown" else "note"

            print(f"Записываем сессию {s.id} (intent={intent})...")

            # Определяем автора
            author_name = resolve_author(s.author_id, context["family_memory"])

            # Передаём в LLM
            llm_output = llm_process_session(
                assembled_content=s.assembled_content,
                intent=intent,
                author_name=author_name,
                created_at=s.opened_at,
                context=context,
            )

            # Парсим JSON ответ (новая схема: title вместо filename)
            output_data = json.loads(extract_json(llm_output))

            title = output_data.get("title", "Без заголовка")
            content = output_data.get("content", "")
            tags = output_data.get("tags", [])
            new_people = output_data.get("new_people", [])
            context_summary = output_data.get("context_summary", "")

            # Python генерирует имя файла
            filename = generate_filename(title, intent, s.opened_at)

            # Определяем action: create или append
            existing = await obsidian_get(filename)

            if existing is None:
                await obsidian_create(filename, content)
                print(f"  Создан файл: {filename}")
            else:
                clean_content = strip_frontmatter(content)
                await obsidian_append(filename, clean_content)
                print(f"  Дополнен файл: {filename}")

            # Обновляем authors для дневника
            if intent == "diary":
                await update_diary_authors(filename, author_name)

            # Загружаем фото в vault
            photo_messages = await session.execute(
                select(Message).where(
                    Message.session_id == s.id,
                    Message.message_type == "photo",
                    Message.photo_filename.isnot(None),
                )
            )
            for photo_msg in photo_messages.scalars().all():
                photo_path = Path("media/images") / f"{photo_msg.raw_content}.jpeg"
                if photo_path.exists():
                    await obsidian_upload_image(photo_path, photo_msg.photo_filename)
                else:
                    print(f"  Файл не найден: {photo_path}")

            # ── Обновляем системные файлы (память) ──
            await update_current_context(context_summary)
            await update_tags_glossary(tags)
            await update_family_memory(new_people)

            # Обновляем статус сессии
            s.status = "processed"
            await session.commit()

            processed_count += 1

        except Exception as e:
            print(f"  Ошибка сессии {s.id}: {e}")
            s.status = "error_obsidian"
            await session.commit()

    return processed_count


def extract_json(raw: str) -> str:
    """Извлекает JSON из ответа reasoning модели."""
    # Убираем служебный префикс reasoning моделей
    if "<|message|>" in raw:
        raw = raw.split("<|message|>")[-1]
    # Убираем markdown code fences если есть
    raw = raw.strip().strip("```json").strip("```").strip()
    return raw