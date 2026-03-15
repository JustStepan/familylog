import re
from datetime import datetime
import frontmatter as fm

from src.logger import logger
from src.constants import NOISE_TAGS, RUSSIAN_MONTHS
from .api import obsidian_get, obsidian_create
from . import general_data
from src.config import settings


async def update_current_context(
    context_summary: str, filename: str = "", tags: list[str] | None = None
) -> None:
    """Добавляет краткое описание записи в месячный context-файл.

    Путь: _system/context/{year}/{MM-месяц}.md
    Формат строки: - [filename] (#тег1, #тег2)\nSummary...
    """
    if not context_summary:
        return

    now = datetime.now()
    month_name = f"{now.month:02d}-{RUSSIAN_MONTHS[now.month - 1]}"
    path = f"_system/context/{now.year}/{month_name}.md"

    # Нормализуем теги: убираем лишний # если он уже есть (LLM возвращает "#тег")
    unique_tags = list(dict.fromkeys(t.lstrip('#') for t in tags if t))
    tags_str = f" ( {', '.join('#' + t for t in unique_tags)})" if unique_tags else ""
    entry = f"[{filename}]{tags_str}\n{context_summary}" if filename else context_summary

    content = await obsidian_get(path)
    today_header = f"## {now.strftime('%Y-%m-%d')}"

    if content is None:
        content = f"# Context {now.strftime('%B %Y')}\n\n{today_header}\n- {entry}\n"
        await obsidian_create(path, content)
    elif today_header in content:
        content = content.rstrip() + f"\n- {entry}\n"
        await obsidian_create(path, content)
    else:
        content = content.rstrip() + f"\n\n{today_header}\n- {entry}\n"
        await obsidian_create(path, content)

    logger.info(f"Обновлён context ({path}): {entry[:80]}...")


async def update_tags_glossary(tags: list[str]) -> None:
    """Добавляет новые теги в TAGS_GLOSSARY.md в секцию 'Автодобавленные'."""
    if not tags:
        return

    path = "_system/TAGS_GLOSSARY.md"
    content = await obsidian_get(path)
    if content is None:
        return

    # Собираем существующие теги (нормализуем — убираем #)
    existing_tags = set()
    for line in content.split("\n"):
        for word in line.strip().split():
            if word.startswith("#") and not word.startswith("##"):
                existing_tags.add(_normalize_tag(word.rstrip("—:,.")))

    # Нормализуем входные теги и фильтруем уже существующие
    new_tags = []
    for t in tags:
        normalized = _normalize_tag(t)
        if normalized and normalized not in existing_tags:
            new_tags.append(normalized)
            existing_tags.add(normalized)  # предотвращаем дубли внутри пачки

    if not new_tags:
        return

    auto_section = "## Автодобавленные"
    new_lines = "\n".join(f"- #{tag}" for tag in new_tags)

    if auto_section in content:
        content = content.rstrip() + "\n" + new_lines + "\n"
    else:
        content = content.rstrip() + f"\n\n{auto_section}\n{new_lines}\n"

    await obsidian_create(path, content)
    logger.info(f"Новые теги в глоссарии: {new_tags}")


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
    logger.info(f"Новые люди в FAMILY_MEMORY: {people_to_add}")


def fix_frontmatter_position(content: str) -> str:
    """Перемещает frontmatter в начало, если LLM поместил его в конец.

    LLM иногда генерирует контент в порядке: сначала тело, потом frontmatter,
    иногда с мусором после закрывающего --- (например calendar_event).

    В Obsidian это рендерится некорректно:
        --- → горизонтальная линия (HR)
        author: Степан → H2 (Setext-заголовок из-за --- снизу)

    Алгоритм: ищем все пары --- в тексте. Берём последнюю пару,
    внутри которой есть YAML-ключи (tags/created/author).
    Всё что после закрывающего --- — добавляем в конец тела.
    """
    content = content.strip()
    # Позиции всех --- стоящих на отдельной строке
    markers = [m.start() for m in re.finditer(r'(?:^|\n)---(?:\n|$)', content)]
    if len(markers) < 2 or content.startswith("---"):
        if len(markers) < 2:
            logger.warning('В ответе LLM только один "---" или вовсе отсутствует! Проверить формирование frontmatter')
        return content

    logger.warning('Сработало внутреннее исправление fix_frontmatter_position')

    # Ищем последнюю пару маркеров, где между ними есть YAML-ключи
    for i in range(len(markers) - 1, 0, -1):
        start = markers[i - 1]
        end = markers[i]
        # Вырезаем текст между --- и ---
        inner_start = start + (0 if content[start] == '-' else 1)  # учитываем \n перед ---
        yaml_text = content[inner_start + 4 : end].strip()  # +4 пропускаем "---\n"
        if not re.search(r'^(tags|created|author)\s*:', yaml_text, re.MULTILINE):
            continue

        body_before = content[:inner_start].strip()
        leftover = content[end + 4:].strip()  # +4 пропускаем "---\n" или "---"
        body = "\n\n".join(filter(None, [body_before, leftover]))
        return f"---\n{yaml_text}\n---\n{body}"

    return content


def sanitize_frontmatter(content: str) -> str:
    """Убирает JSON-стиль запятые из YAML frontmatter.
        date: "2026-03-11",   →   date: "2026-03-11"
        time_start: null,     →   time_start: null
    """
    if not content.startswith("---"):
        return content
    parts = content.split("---", 2)
    yaml_block = re.sub(r",(\s*\n)", r"\1", parts[1])
    return f"---{yaml_block}---{parts[2]}"


# ─── Запись в Obsidian ───────────────────────────────────────────────────────

async def update_diary_authors(path: str, new_author: str) -> None:
    """Обновляет authors и updated в frontmatter дневника."""
    content = await obsidian_get(path)
    if not content:
        return
    post = fm.loads(content)
    authors = post.get("authors", [])
    if new_author not in authors:
        authors.append(new_author)
        post["authors"] = authors
    # Всегда обновляем timestamp при любом append
    post["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    await obsidian_create(path, fm.dumps(post))


def _normalize_tag(tag: str) -> str:
    """Приводит тег к единому формату без # для YAML frontmatter."""
    return tag.lstrip("#").strip()


def generate_person_tag(name: str) -> str:
    """Генерирует тег из имени человека.

    'Василий Иванович Полеостровский' → '#В_И_Полеостровский'
    'Пётр Иванович' → '#Пётр_Иванович'
    'Степан' → '#Степан'
    """
    parts = name.strip().split()
    if len(parts) >= 3:
        return f"#{parts[0][0]}_{parts[1][0]}_{parts[2]}"
    elif len(parts) == 2:
        return f"#{parts[0]}_{parts[1]}"
    elif parts:
        return f"#{parts[0]}"
    return ""

def inject_tags_to_frontmatter(content: str, extra_tags: list[str]) -> str:
    """Вставляет теги в frontmatter через python-frontmatter.
    Нормализует теги: убирает # (в YAML frontmatter Obsidian теги без #),
    отбрасывает пустые.
    """
    if not extra_tags:
        logger.warning("extra_tags пустой — out.tags не содержит тегов от модели")
        return content
    try:
        post = fm.loads(content)  # Объект fm - Словарь, с ключами, из yaml.
        yaml_t = post.get("tags", []) or []
        # Нормализуем: убираем # из обоих списков, фильтруем None/пустые
        all_tags = [_normalize_tag(t) for t in yaml_t if t] + \
                   [_normalize_tag(t) for t in extra_tags if t]
        # Дедупликация с сохранением порядка, отбрасываем пустые
        merged = list(dict.fromkeys(t for t in all_tags if t))
        post["tags"] = merged
        return fm.dumps(post)
    except Exception as e:
        logger.error(f"Ошибка вставки тегов в frontmatter: {e}")
        return content


async def find_related_by_tags(tags: list[str], current_filename: str) -> list[str]:
    """Ищет заметки с совпадающими тегами через месячные context-файлы.
    Читает уже готовый индекс контекста
    (записи вида: - [filepath] (#тег1, #тег2)\nSummary...).
    Возвращает до 5 наиболее связанных файлов.
    """
    if not tags:
        logger.debug("Нет тегов для поиска related")
        return []

    tags_set = set(_normalize_tag(t) for t in tags if t) - NOISE_TAGS
    if not tags_set:
        return []

    context_text = await general_data.load_context_for_period()
    candidates: list[tuple[str, int]] = []

    # Парсим строки вида: - [filepath] (#тег1, #тег2)
    entry_re = re.compile(r"^- \[([^\]]+\.md)\]\s*(?:\(([^)]*)\))?", re.MULTILINE)
    for m in entry_re.finditer(context_text):
        filepath = m.group(1)
        if filepath == current_filename:
            continue
        tags_str = m.group(2) or ""
        file_tags = set(
            _normalize_tag(t) for t in tags_str.split(",") if t.strip()
        ) - NOISE_TAGS
        overlap = len(tags_set & file_tags)
        if overlap >= settings.RELATED_NOTES_MIN_TAG_OVERLAP:
            logger.debug(f"Связанные заметки: {filepath} совпадение тегов - {overlap}")
            candidates.append((filepath, overlap))

    logger.debug(f"Итого связанных заметок из контекста: {len(candidates)} кандидатов")
    candidates.sort(key=lambda x: x[1], reverse=True)
    return [c[0] for c in candidates[:5]]


def _to_wikilink(path: str) -> str:
    """Конвертирует путь файла в формат wiki-link Obsidian: [[path/without/.md]]."""
    if path.startswith("[["):
        return path  # Уже wiki-link
    clean = path.removesuffix(".md")
    return f"[[{clean}]]"


def _from_wikilink(link: str) -> str:
    """Извлекает путь файла из wiki-link формата."""
    if isinstance(link, str) and link.startswith("[[") and link.endswith("]]"):
        return link[2:-2]
    return str(link)


def inject_related_to_frontmatter(content: str, related: list[str]) -> str:
    """Вставляет related в frontmatter как [[wiki-links]] для Obsidian графа."""
    if not related:
        return content
    try:
        post = fm.loads(content)
        existing = post.get("related", []) or []
        # Конвертируем всё в wiki-link формат
        all_links = [_to_wikilink(r) for r in existing if r] + \
                    [_to_wikilink(r) for r in related if r]
        # Дедупликация по нормализованному пути
        seen = set()
        merged = []
        for link in all_links:
            key = _from_wikilink(link)
            if key not in seen:
                seen.add(key)
                merged.append(link)
        post["related"] = merged
        return fm.dumps(post)
    except Exception:
        return content


async def validate_related_files(related: list[str]) -> list[str]:
    """Проверяет что файлы из related существуют в vault. Отбрасывает несуществующие."""
    valid = []
    for filepath in related:
        if not filepath or not filepath.endswith(".md"):
            continue
        content = await obsidian_get(filepath)
        if content is not None:
            valid.append(filepath)
    return valid


async def add_backlinks(related_files: list[str], current_filename: str) -> None:
    """Добавляет обратную ссылку (backlink) как [[wiki-link]] в related файлы."""
    current_link = _to_wikilink(current_filename)
    current_normalized = _from_wikilink(current_link)

    for filepath in related_files:
        file_content = await obsidian_get(filepath)
        if not file_content:
            continue
        try:
            post = fm.loads(file_content)
            existing = post.get("related", []) or []
            # Проверяем оба формата: plain path и wiki-link
            existing_normalized = {_from_wikilink(e) for e in existing}
            if current_normalized not in existing_normalized:
                existing.append(current_link)
                post["related"] = existing
                await obsidian_create(filepath, fm.dumps(post))
        except Exception:
            continue


def fix_document_references(
    content: str, doc_filenames: list[str], dest_folder: str = "attachments/documents"
) -> str:
    """Исправляет ссылки на документы в контенте — гарантирует точное имя файла.
    LLM может исказить имя файла (заменить пробелы на _ и т.д.).
    dest_folder — папка назначения документов, например "attachments/documents/2026/03-мар".
    """
    if not doc_filenames:
        return content

    for fn in doc_filenames:
        # Вариант с подчёркиваниями вместо пробелов (частая ошибка LLM)
        mangled = fn.replace(" ", "_").replace(",", "")
        # Вариант без запятых
        no_comma = fn.replace(",", "")

        # Если LLM использовал искажённое имя — заменяем на правильное
        if mangled != fn and mangled in content:
            content = content.replace(mangled, fn)
            print('Сработал mangled')
        if no_comma != fn and no_comma in content:
            content = content.replace(no_comma, fn)
            print('Сработал no_comma')

        # Если ссылка на документ вообще отсутствует — добавляем в конец.
        # Используем regex чтобы найти basename независимо от пути (year/month могут быть разными).
        if not re.search(r'!\[\[.*?' + re.escape(fn) + r'.*?\]\]', content):
            content = content.rstrip() + f"\n\n![[{dest_folder}/{fn}]]\n"
            logger.warning(f"Вручную добавлена ссылка на документ: {fn}")

    return content


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

