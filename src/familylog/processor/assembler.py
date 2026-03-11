from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..storage.models import Session, Message
from src.logger import logger


@logger.catch
async def assemble_sessions(session: AsyncSession) -> int:
    result = await session.execute(
        select(Session).where(Session.status == "ready")
    )

    sessions = result.scalars().all()
    logger.info(f"Найдено сессий ready = {len(sessions)}")

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
            error_msg = f"[Ошибка обработки, message_id={msg.id}]"
            text = msg.text_content or error_msg

            if msg.message_type == "text":
                parts.append(_fmt_line(forward_header, "Текст", text))
            elif msg.message_type == "voice":
                parts.append(_fmt_line(forward_header, "Аудио", text))
            elif msg.message_type == "photo":
                fn = f" filename={msg.photo_filename}" if msg.photo_filename else ""
                extra = f"\n[Оригинальный текст]: {msg.original_caption}" if msg.original_caption else ""
                parts.append(_fmt_line(forward_header, f"Фото{fn}", text + extra))
            elif msg.message_type == "document":
                fn = f" filename={msg.document_filename}" if msg.document_filename else ""
                parts.append(_fmt_line(forward_header, f"Документ{fn}", text))

            msg.status = "assembled"

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


def _fmt_line(header: str, label: str, text: str) -> str:
    """Формирует строку сообщения с опциональным заголовком пересланного."""
    prefix = f"{header}\n" if header else ""
    return f"{prefix}[{label}]: {text}"