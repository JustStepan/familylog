from typing import Optional

from src.config import settings
from .client import get_client


def llm_process_photo(base64_str: str, caption: Optional[str]) -> str:
    client = get_client()
    caption_prompt = ''
    if caption and caption.strip():
        caption_prompt = f"Заголовок фотографии --> '{caption}' - учитывай это при составлении описания"

    try:
        response = client.chat.completions.create(
            model=settings.vision_model,
            messages=[
                {
                    "role": "system",
                    "content": f"""
Ты возвращаешь данные ТОЛЬКО в JSON формате без markdown.
Формат ответа:
{{"caption": "Заголовок изображения", "description": "Описание изображения"}}
Не добавляй никакого текста до или после JSON. Отвечай на русском.
{caption_prompt}
Если пользователь не предоставил никакой заголовок, то выходной 'caption' 
должен быть составлен из описания фотографии (description).
Правила для поля caption:
- Если caption пустой → создай заголовок на основе описания (3-5 слов)
- Если caption есть но не соответствует содержимому → замени на точный
- Если caption точно описывает изображение → можешь уточнить, но не меняй кардинально
"""
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Представь точное описание представленной фотографии."},
                        
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_str}"
                            }
                        }
                    ]
                }
            ],
            temperature=0.2,
            # max_tokens=500,
        )
        return response.choices[0].message.content

    except Exception as e:
        return f"Ошибка API: {e}"


def llm_process_session(
    assembled_content: str,
    intent: str,
    author_name: str,
    created_at,
    context: dict,
) -> str:
    """Обрабатывает assembled_content и возвращает JSON для записи в Obsidian."""
    client = get_client()

    now_str = created_at.strftime("%Y-%m-%d %H:%M") if created_at else "unknown"

    # Intent-specific правила (если есть)
    intent_section = ""
    if context.get("intent_config"):
        intent_section = f"""
## Правила для интента: {intent}
{context['intent_config']}
"""

    system_prompt = f"""{context['agent_config']}
{intent_section}
---
Дата и время: {now_str}
Автор: {author_name}

## Память о семье
{context['family_memory']}

## Глоссарий тегов
{context['tags_glossary']}

## Текущий контекст (последние {settings.CONTEXT_MEMORY_DAYS} дней)
{context['current_context']}
"""

    response = client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Интент: {intent}\n\nСодержание:\n{assembled_content}"},
        ],
        temperature=0.1,
        # max_tokens=3000,
    )

    return response.choices[0].message.content


def llm_generate_summary(
    vault_content: str,
    since: "datetime | None" = None,
) -> str:
    """Генерирует периодический summary по записям из vault."""
    from datetime import datetime as _dt

    client = get_client()
    period = f"с {since.strftime('%d.%m.%Y')}" if since else "за всё время"
    now_str = _dt.now().strftime("%Y-%m-%d %H:%M")

    system_prompt = f"""Ты — семейный ассистент. Тебе переданы записи из семейного Obsidian vault {period}.

Создай структурированный summary. Отвечай ТОЛЬКО валидным JSON:

{{
  "summary_text": "Краткий текст для Telegram без markdown",
  "content": "Полный markdown файл для Obsidian (с frontmatter)"
}}

## Правила для summary_text (Telegram)
- Описание основных событий и связей между ними. Нужен чистый текст без markdown
- Главные события, выполненные задания, планы все это нужно связать по возможности
- Дружелюбный тон, как семейный помощник
- Не выдумывай ничего. Только та информация которая была передана для анализа.

## Правила для content (Obsidian файл)
- Frontmatter строго в таком формате:
---
tags:
  - summary
created: {now_str}
period_start: YYYY-MM-DD
period_end: YYYY-MM-DD
---
- Секции:
  ### Заметки — краткий обзор тем заметок
  ### Дневник — основные события из дневника
  ### Календарь — предстоящие и прошедшие события
  ### Задания — выполненные и невыполненные задания
  ### Статистика — количество записей по категориям
- Если какой-то секции нет (нет записей) — пропусти её
- Не придумывай то, чего нет в данных

## Структура входных данных
Тебе передаются две части:
1. **Записи за период** (notes, diary, calendar, tasks) — их нужно суммаризировать
2. **Контекст до этого периода** (секция "Контекст до этого периода") — только для понимания предыстории и связей, НЕ включать в summary

## Правила использования контекста
- Контекст помогает понять кто такие упомянутые люди и что происходило раньше
- НЕ пересказывай события из контекста в summary_text или content
- Используй контекст только чтобы правильно атрибутировать авторов и понять связи
- Если событие упомянуто и в контексте и в записях периода — описывай только по записям периода

Дата: {now_str}
"""

    response = client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": vault_content},
        ],
        temperature=0.1,
        # max_tokens=5000,
    )

    response = client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": vault_content},
        ],
        temperature=0.2,
        extra_body={
            "chat_template_kwargs": {"enable_thinking": False},
        },
        # max_tokens=5000,
    )

    return response.choices[0].message.content
