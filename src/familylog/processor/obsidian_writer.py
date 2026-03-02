import json
from pathlib import Path
from datetime import datetime
import pprint
import frontmatter as fm

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..LLMs_calls.calls import llm_process_session
from ..storage.models import Session, Message
from src.logger import logger
from .obsidian import api, general_data, utils, write_files


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
            # Неизвестный intent → note
            intent = s.intent if s.intent != "unknown" else "note"

            # Загружаем intent-specific правила (с кешем)
            if intent not in intent_cache:
                intent_config = await general_data.load_system_file(f"intents/{intent}.md")
                intent_cache[intent] = "" if "(file not found)" in intent_config else intent_config
                logger.info(f'Интент={intent} загружен в системный кеш.')
            context = {**base_context, "intent_config": intent_cache[intent]}

            logger.info(f"Записываем сессию {s.id} (intent={intent})...")

            # Определяем автора
            author_name = utils.resolve_author(s.author_id, context["family_memory"])

            # Передаём в LLM (last_message_at — реальное время записи, не время открытия сессии)
            llm_output = llm_process_session(
                assembled_content=s.assembled_content,
                intent=intent,
                author_name=author_name,
                created_at=s.last_message_at or s.opened_at,
                context=context,
            )

            # Парсим JSON ответ
            output_data = json.loads(extract_json(llm_output))

            title = output_data.get("title", "Без заголовка")
            content = output_data.get("content", "")
            tags = output_data.get("tags", [])
            people_mentioned = output_data.get("people_mentioned", [])
            new_people = output_data.get("new_people", [])
            context_summary = output_data.get("context_summary", "")

            # Генерируем теги из имён упомянутых людей (кроме автора)
            for person in people_mentioned:
                if person and person != author_name:
                    ptag = write_files.generate_person_tag(person)
                    if ptag:
                        tags.append(ptag)
            for person in new_people:
                if person:
                    ptag = write_files.generate_person_tag(person)
                    if ptag:
                        tags.append(ptag)

            # Python гарантирует теги в frontmatter
            content = write_files.inject_tags_to_frontmatter(content, tags)

            # Добавляем created timestamp в frontmatter
            try:
                post = fm.loads(content)
                created_ts = s.opened_at or datetime.now()
                if "created" not in post.metadata:
                    post["created"] = created_ts.strftime("%Y-%m-%d %H:%M")
                content = fm.dumps(post)
            except Exception:
                pass  # Если frontmatter не парсится — пропускаем

            # ── Собираем имена документов для post-processing ──
            doc_messages_result = await session.execute(
                select(Message).where(
                    Message.session_id == s.id,
                    Message.message_type == "document",
                    Message.document_filename.isnot(None),
                )
            )
            doc_msgs = doc_messages_result.scalars().all()
            doc_filenames = [m.document_filename for m in doc_msgs if m.document_filename]

            # Исправляем ссылки на документы (LLM может исказить имена файлов)
            if doc_filenames:
                content = write_files.fix_document_references(content, doc_filenames)

            # Исправляем формат embed-ссылок (![alt]([[path]]) → ![[path]])
            content = fix_obsidian_embeds(content)

            # Python генерирует имя файла
            filename = utils.generate_filename(title, intent, s.opened_at)

            # Определяем action: create или append
            existing = await api.obsidian_get(filename)

            if existing is None:
                await api.obsidian_create(filename, content)
                logger.info(f"Создан файл: {filename}")
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

            # ── Ищем related: LLM-предложения + совпадение по тегам ──
            try:
                # LLM может вернуть related из CURRENT_CONTEXT
                llm_related = output_data.get("related", [])

                # Поиск по совпадению тегов в vault
                tag_related = await write_files.find_related_by_tags(tags, filename, intent)

                # Объединяем оба источника, дедупликация, max 5
                all_related = list(dict.fromkeys(llm_related + tag_related))[:5]

                # Валидируем: оставляем только существующие файлы
                if all_related:
                    all_related = await write_files.validate_related_files(all_related)

                # Всегда обновляем related в frontmatter (даже если пустой — для консистентности)
                fresh = await api.obsidian_get(filename)
                if fresh:
                    updated = write_files.inject_related_to_frontmatter(fresh, all_related) if all_related else fresh
                    # Гарантируем наличие поля related (даже пустого)
                    try:
                        post = fm.loads(updated)
                        if "related" not in post.metadata:
                            post["related"] = []
                        updated = fm.dumps(post)
                    except Exception:
                        pass
                    await api.obsidian_create(filename, updated)

                if all_related:
                    # Добавляем backlink в найденные файлы
                    await write_files.add_backlinks(all_related, filename)
                    logger.info(f"Связано с: {all_related}")
                else:
                    logger.debug("Related: не найдено совпадений")
            except Exception as e:
                logger.warning(f"Ошибка поиска related: {e}")

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
                    await api.obsidian_upload_image(photo_path, photo_msg.photo_filename)
                else:
                    logger.warning(f"Фото не найдено: {photo_path}", )

            # Загружаем документы в vault
            for doc_msg in doc_msgs:
                ext = Path(doc_msg.document_filename).suffix.lstrip(".") or "bin"
                doc_path = Path("media/documents") / f"{doc_msg.raw_content}.{ext}"
                if doc_path.exists():
                    await api.obsidian_upload_document(doc_path, doc_msg.document_filename)
                else:
                    logger.warning(f"Документ не найден: {doc_path}")

            # ── Обновляем системные файлы (память) ──
            await write_files.update_current_context(context_summary, filename=filename, tags=tags)
            await write_files.update_tags_glossary(tags)
            await write_files.update_family_memory(new_people)

            # Обновляем статус сессии
            s.status = "processed"
            await session.commit()

            processed_count += 1

        except Exception as e:
            logger.error(f"Ошибка сессии {s.id}: {e}")
            s.status = "error_obsidian"
            await session.commit()

    return processed_count


def fix_obsidian_embeds(content: str) -> str:
    """Исправляет формат embed-ссылок: LLM часто генерирует неправильный формат.

    ![alt]([[path]]) → ![[path]]
    ![alt](attachments/...) → ![[attachments/...]]
    """
    import re
    # ![alt]([[path]]) → ![[path]]
    content = re.sub(r'!\[([^\]]*)\]\(\[\[([^\]]+)\]\]\)', r'![[\2]]', content)
    # ![alt](attachments/...) → ![[attachments/...]]
    content = re.sub(r'!\[([^\]]*)\]\((attachments/[^)]+)\)', r'![[\2]]', content)
    return content


def extract_json(raw: str) -> str:
    """Извлекает JSON из ответа reasoning модели (qwen3.5, deepseek и пр.)."""
    import re
    # Убираем служебный префикс reasoning моделей
    if "<|message|>" in raw:
        raw = raw.split("<|message|>")[-1]
    # Убираем <think>...</think> блоки (qwen3.5 reasoning chain)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    # Если <think> без закрывающего тега — отрезаем всё до первого {
    if "<think>" in raw:
        idx = raw.find("{")
        if idx >= 0:
            raw = raw[idx:]
    # Убираем markdown code fences если есть
    raw = raw.strip().strip("```json").strip("```").strip()
    return raw