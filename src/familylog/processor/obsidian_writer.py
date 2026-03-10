import json
import re
from pathlib import Path
from datetime import datetime
import frontmatter as fm
from pydantic import ValidationError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..LLMs_calls.agent import process_session_with_agent
from ..schema.llm import SessionOutput
from ..storage.models import Session, Message
from src.familylog.integrations.google_calendar import create_calendar_event
from src.logger import logger
from .obsidian import api, general_data, utils, write_files


# ─── Утилиты обработки вывода LLM ────────────────────────────────────────────

def extract_json(raw: str) -> str:
    if "<|message|>" in raw:
        raw = raw.split("<|message|>")[-1]
    # Убираем <think>...</think> включая варианты с пробелами
    raw = re.sub(r"<\s*think\s*>.*?<\s*/\s*think\s*>", "", raw, flags=re.DOTALL)
    # Если think без закрывающего тега — ищем ПОСЛЕДНИЙ { в начале строки.
    # Берём последний, а не первый: модель может написать черновик JSON внутри
    # thinking-блока, а финальный ответ идёт в конце вывода.
    if "<think>" in raw.lower():
        matches = list(re.finditer(r"(?:^|\n)(\{)", raw))
        if matches:
            raw = raw[matches[-1].start(1):]
    # Убираем <|im_end|> и подобные артефакты
    raw = re.sub(r"<\|.*?\|>", "", raw)
    # Убираем обёртку ```json...``` — strip(chars) работает посимвольно,
    # поэтому используем re.sub для точного удаления подстрок
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def fix_obsidian_embeds(content: str) -> str:
    """Исправляет формат embed-ссылок: LLM часто генерирует неправильный формат.

    ![alt]([[path]]) → ![[path]]
    ![alt](attachments/...) → ![[attachments/...]]
    """
    content = re.sub(r'!\[([^\]]*)\]\(\[\[([^\]]+)\]\]\)', r'![[\2]]', content)
    content = re.sub(r'!\[([^\]]*)\]\((attachments/[^)]+)\)', r'![[\2]]', content)
    return content


def fix_attachment_paths(content: str, year: int, mfolder: str) -> str:
    """Вставляет year/month в пути аттачментов если LLM их не указал.

    ![[attachments/photos/photo.jpg]]      → ![[attachments/photos/2026/03-мар/photo.jpg]]
    ![[attachments/documents/report.pdf]]  → ![[attachments/documents/2026/03-мар/report.pdf]]
    Пути, уже содержащие /YYYY/ — не изменяются (negative lookahead (?!\\d{4}/).
    """
    pattern = r'(!\[\[attachments/(?:photos|documents)/)(?!\d{4}/)([^\]]+\]\])'
    replacement = rf'\g<1>{year}/{mfolder}/\g<2>'
    return re.sub(pattern, replacement, content)


# ─── Вспомогательные функции обработки сессии ────────────────────────────────

def _parse_llm_response(session_id: int, llm_output: str) -> SessionOutput | None:
    """Извлекает и валидирует JSON из вывода LLM. None → ошибка (уже залогирована)."""
    _extracted = extract_json(llm_output)
    try:
        return SessionOutput.model_validate(
            json.loads(_extracted, strict=False)
        )
    except (json.JSONDecodeError, ValidationError) as e:
        logger.error(
            f"Сессия {session_id}: не удалось распарсить JSON от LLM: {e}"
            f"\nRaw[:300]:       {llm_output[:300]}"
            f"\nExtracted[:500]: {_extracted[:500]}"
        )
        return None


def _build_tags(
    out: SessionOutput, author_name: str
) -> tuple[list[str], list[str], list[str]]:
    """Строит теги и нормализует списки людей из SessionOutput.

    Telegram-аккаунты (начинаются с @) убираются из people_mentioned
    и не добавляются в new_people — они не попадают в FAMILY_MEMORY.

    Возвращает (tags, people_mentioned, new_people).
    """
    tags = list(out.tags)  # копируем: будем аппендить person-теги, не мутируем модель
    people_mentioned = [p.lstrip("@").strip() for p in out.people_mentioned if p and p.strip()]
    new_people = [p for p in out.new_people if p and not p.startswith("@")]

    for person in people_mentioned:
        if person != author_name:
            if ptag := write_files.generate_person_tag(person):
                tags.append(ptag)
    for person in new_people:
        if ptag := write_files.generate_person_tag(person):
            tags.append(ptag)

    return tags, people_mentioned, new_people


async def _update_related_files(
    filename: str, tags: list[str], intent: str, llm_related: list[str]
) -> None:
    """Ищет, валидирует и проставляет related-ссылки в обоих направлениях."""
    try:
        tag_related = await write_files.find_related_by_tags(tags, filename, intent)
        all_related = list(dict.fromkeys(llm_related + tag_related))[:5]
        if all_related:
            all_related = await write_files.validate_related_files(all_related)

        fresh = await api.obsidian_get(filename)
        if fresh:
            updated = write_files.inject_related_to_frontmatter(fresh, all_related) if all_related else fresh
            # Гарантируем наличие поля related (даже пустого — для консистентности)
            try:
                post = fm.loads(updated)
                if "related" not in post.metadata:
                    post["related"] = []
                updated = fm.dumps(post)
            except Exception:
                pass
            await api.obsidian_create(filename, updated)

        if all_related:
            await write_files.add_backlinks(all_related, filename)
            logger.info(f"Связано с: {all_related}")
        else:
            logger.debug("Related: не найдено совпадений")
    except Exception as e:
        logger.warning(f"Ошибка поиска related: {e}")


async def _upload_session_media(
    db_session: AsyncSession,
    s: Session,
    photo_dest: str,
    doc_dest: str,
    doc_msgs: list[Message],
) -> None:
    """Загружает фото и документы сессии в vault."""
    photo_messages = await db_session.execute(
        select(Message).where(
            Message.session_id == s.id,
            Message.message_type == "photo",
            Message.photo_filename.isnot(None),
        )
    )
    for photo_msg in photo_messages.scalars().all():
        photo_path = Path("media/images") / f"{photo_msg.raw_content}.jpeg"
        if photo_path.exists():
            await api.obsidian_upload_image(photo_path, photo_msg.photo_filename, photo_dest)
        else:
            logger.warning(f"Фото не найдено: {photo_path}")

    for doc_msg in doc_msgs:
        ext = Path(doc_msg.document_filename).suffix.lstrip(".") or "bin"
        doc_path = Path("media/documents") / f"{doc_msg.raw_content}.{ext}"
        if doc_path.exists():
            await api.obsidian_upload_document(doc_path, doc_msg.document_filename, doc_dest)
        else:
            logger.warning(f"Документ не найден: {doc_path}")


# ─── Основная логика обработки ────────────────────────────────────────────────

async def _process_single_session(
    s: Session,
    base_context: dict,
    intent_cache: dict[str, str],
    db_session: AsyncSession,
) -> bool:
    """Обрабатывает одну assembled-сессию. Возвращает True при успехе."""
    intent = s.intent if s.intent != "unknown" else "note"

    # Загружаем intent-specific правила (с кешем)
    if intent not in intent_cache:
        intent_config = await general_data.load_system_file(f"intents/{intent}.md")
        intent_cache[intent] = "" if "(file not found)" in intent_config else intent_config
        logger.info(f"Интент={intent} загружен в системный кеш.")
    context = {**base_context, "intent_config": intent_cache[intent]}

    logger.info(f"Записываем сессию {s.id} (intent={intent})...")
    author_name = utils.resolve_author(s.author_id, context["family_memory"])

    # Агент итеративно собирает контекст из vault и генерирует JSON
    llm_output = process_session_with_agent(
        assembled_content=s.assembled_content,
        intent=intent,
        author_name=author_name,
        created_at=s.last_message_at or s.opened_at,
    )

    # Парсим и валидируем JSON ответ агента через Pydantic
    out = _parse_llm_response(s.id, llm_output)
    if out is None:
        s.status = "error_json"
        await db_session.commit()
        return False

    # Строим теги и нормализуем списки людей
    tags, people_mentioned, new_people = _build_tags(out, author_name)

    # Фиксируем позицию frontmatter и убираем JSON-запятые из YAML
    content = write_files.sanitize_frontmatter(
        write_files.fix_frontmatter_position(out.content)
    )

    # Python гарантирует теги в frontmatter
    content = write_files.inject_tags_to_frontmatter(content, tags)

    # Добавляем created timestamp в frontmatter
    try:
        post = fm.loads(content)
        created_ts = s.opened_at or datetime.now()
        if "created" not in post.metadata:
            post["created"] = created_ts.strftime("%Y-%m-%d %H:%M")
        content = fm.dumps(post)
    except Exception as e:
        logger.warning(f"Сессия {s.id}: не удалось добавить created в frontmatter: {e}")

    # ── Вычисляем папки для аттачментов (year/month) ──
    session_dt = s.opened_at or datetime.now()
    photo_dest = utils.attachment_folder("attachments/photos", session_dt)
    doc_dest = utils.attachment_folder("attachments/documents", session_dt)

    # ── Собираем имена документов для post-processing ──
    doc_messages_result = await db_session.execute(
        select(Message).where(
            Message.session_id == s.id,
            Message.message_type == "document",
            Message.document_filename.isnot(None),
        )
    )
    doc_msgs = doc_messages_result.scalars().all()
    doc_filenames = [m.document_filename for m in doc_msgs if m.document_filename]

    # Исправляем ссылки на документы и форматы embed
    if doc_filenames:
        content = write_files.fix_document_references(content, doc_filenames, doc_dest)
    content = fix_obsidian_embeds(content)
    content = fix_attachment_paths(content, session_dt.year, utils.month_folder(session_dt))

    # Python генерирует имя файла (session_dt уже содержит fallback на now())
    filename = utils.generate_filename(out.title, intent, session_dt)

    # Определяем action: create или append
    existing = await api.obsidian_get(filename)
    if existing is None:
        await api.obsidian_create(filename, content)
        logger.info(f"Создан файл: {filename}")

        # Google Calendar — только после того как файл уже создан
        if intent == "calendar" and out.calendar_event:
            event_link = create_calendar_event(
                title=out.title,
                date=out.calendar_event.date,
                time_start=out.calendar_event.time_start,
                duration_minutes=out.calendar_event.duration_minutes,
                description=out.calendar_event.description,
            )
            if event_link:
                fresh = await api.obsidian_get(filename)
                if fresh:
                    gcal_link = f"\n[📅 Открыть в Google Calendar]({event_link})\n"
                    await api.obsidian_create(filename, fresh + gcal_link)
                    logger.info("Для intent=calendar был обновлен md файл")
    else:
        clean_content = write_files.strip_frontmatter(content)
        await api.obsidian_append(filename, clean_content)
        # Сливаем новые теги в существующий frontmatter
        if tags:
            fresh = await api.obsidian_get(filename)
            if fresh:
                updated_content = write_files.inject_tags_to_frontmatter(fresh, tags)
                await api.obsidian_create(filename, updated_content)
        logger.info(f"Дополнен файл: {filename}")

    # Обновляем authors для дневника
    if intent == "diary":
        await write_files.update_diary_authors(filename, author_name)

    # Related: LLM-предложения + совпадение по тегам
    await _update_related_files(filename, tags, intent, out.related)

    # Загружаем медиа в vault
    await _upload_session_media(db_session, s, photo_dest, doc_dest, doc_msgs)

    # ── Обновляем системные файлы (память) ──
    await write_files.update_current_context(out.context_summary, filename=filename, tags=tags)
    await write_files.update_tags_glossary(tags)
    await write_files.update_family_memory(new_people)

    s.status = "processed"
    await db_session.commit()
    return True


async def process_assembled_sessions(session: AsyncSession) -> int:
    """Берёт assembled сессии и записывает их в Obsidian.
    Возвращает количество обработанных сессий."""

    result = await session.execute(
        select(Session).where(Session.status == "assembled")
    )
    sessions = result.scalars().all()

    if not sessions:
        return 0

    # Загружаем базовый контекст один раз, intent-specific кешируем
    base_context = await general_data.load_base_context()
    intent_cache: dict[str, str] = {}
    processed_count = 0

    for s in sessions:
        try:
            if await _process_single_session(s, base_context, intent_cache, session):
                processed_count += 1
        except Exception as e:
            logger.error(f"Ошибка сессии {s.id}: {e}")
            s.status = "error_obsidian"
            await session.commit()

    return processed_count
