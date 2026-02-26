from typing import Optional

from ..processor.obsidian_writer import CONTEXT_MEMORY_DAYS
from .client import get_client


def llm_process_photo(base64_str: str, caption: Optional[str]) -> str:
    client = get_client()
    caption_prompt = ''
    if caption:
        caption_prompt = f"Заголовок фотографии --> '{caption}' - учитывай это при составлении описания"

    try:
        response = client.chat.completions.create(
            model='qwen/qwen3-vl-8b', # qwen3.5-35b-a3b qwen/qwen3-vl-8b glm-4.6v-flash
            messages=[
                {
                    "role": "system",
                    "content": f"""
Ты возвращаешь данные ТОЛЬКО в JSON формате без markdown.
Формат ответа:
{{"caption": "Заголовок изображения", "description": "Описание изображения"}}
Не добавляй никакого текста до или после JSON.
Если пользователь предоставил не пустой caption_prompt, то выходной 'caption' 
должен быть результатом обогащения первоначального заголовка (caption) описанием фотографии.
Правила для поля caption:
- Если caption пустой → создай заголовок на основе описания (3-5 слов)
- Если caption есть но не соответствует содержимому → замени на точный
- Если caption точно описывает изображение → можешь уточнить, но не меняй кардинально
"""
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Представь описание фотографии. caption_prompt: {caption_prompt}"},
                        
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_str}"
                            }
                        }
                    ]
                }
            ],
            temperature=0.1,
            max_tokens=300,
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

    system_prompt = f"""
You are a family memory assistant writing structured Obsidian notes.

Current datetime: {now_str}
Author: {author_name}

## Agent Configuration
{context['agent_config']}

## Family Memory
{context['family_memory']}

## Tags Glossary
{context['tags_glossary']}

## Current Context (last {CONTEXT_MEMORY_DAYS} days)
{context['current_context']}

Return ONLY valid JSON as specified in Agent Configuration. No markdown fences, no explanation.
"""

    response = client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Intent: {intent}\n\nContent:\n{assembled_content}"},
        ],
        temperature=0.1,
        max_tokens=2000,
    )

    return response.choices[0].message.content
