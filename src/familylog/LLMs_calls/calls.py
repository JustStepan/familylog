from typing import Optional


from .client import get_client


def llm_process_photo(base64_str: str, caption: Optional[str]) -> str:
    client = get_client()
    caption_prompt = ''
    if caption:
        caption_prompt = f"Заголовок фотографии --> '{caption}' - учитывай это при составлении описания"

    try:
        response = client.chat.completions.create(
            model='qwen/qwen3-vl-8b',
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
                        {"type": "text", "text": f"Представь краткое, но точное описание фотографии. caption_prompt: {caption_prompt}"},
                        
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