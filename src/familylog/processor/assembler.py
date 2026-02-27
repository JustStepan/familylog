from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..storage.models import Session, Message


async def assemble_sessions(session: AsyncSession) -> int:
    result = await session.execute(
        select(Session).where(Session.status == "ready")
    )

    sessions = result.scalars().all()
    print(f"DEBUG assembler: найдено сессий ready = {len(sessions)}")

    processed_count = 0
    for s in sessions:

        messages_result = await session.execute(
            select(Message)
            .where(Message.session_id == s.id)
            .order_by(Message.created_at)
        )

        messages = messages_result.scalars().all()

        if not messages:
            s.status = "empty"
            continue

        parts = []
        for msg in messages:
            forward_header = format_forward_header(msg)
            fallback = f"[Ошибка обработки, message_id={msg.id}]"
            text = msg.text_content or fallback

            if msg.message_type == "text":
                content = f"{forward_header}\n[Текст]: {text}" if forward_header else f"[Текст]: {text}"
                parts.append(content)
            elif msg.message_type == "voice":
                content = f"{forward_header}\n[Аудио]: {text}" if forward_header else f"[Аудио]: {text}"
                parts.append(content)
            elif msg.message_type == "photo":
                fn = f" filename={msg.photo_filename}" if msg.photo_filename else ""
                original = f"\n[Оригинальный текст]: {msg.original_caption}" if msg.original_caption else ""
                content = f"{forward_header}\n[Фото{fn}]: {text}{original}" if forward_header else f"[Фото{fn}]: {text}{original}"
                parts.append(content)

            elif msg.message_type == "document":
                fn = f" filename={msg.document_filename}" if msg.document_filename else ""
                content = f"{forward_header}\n[Документ{fn}]: {text}" if forward_header else f"[Документ{fn}]: {text}"
                parts.append(content)

            msg.status = "assembled"

        # 5. Обновить сессию
        s.assembled_content = "\n".join(parts)
        s.status = "assembled"
        processed_count += 1

    await session.commit()
    return processed_count


def format_forward_header(msg) -> str:
    """Формирует заголовок пересланного сообщения."""
    if not msg.is_forwarded:
        return ""
    parts = ["[Переслано"]
    if msg.forward_from_username:
        parts.append(f"из @{msg.forward_from_username}")
    elif msg.forward_from_name:
        parts.append(f"от {msg.forward_from_name}")
    if msg.forward_post_url:
        parts.append(f"| {msg.forward_post_url}")
    parts.append("]")
    return " ".join(parts)