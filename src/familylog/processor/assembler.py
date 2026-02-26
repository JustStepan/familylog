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
            fallback = f"[Ошибка обработки, message_id={msg.id}]: текст недоступен"
            text = msg.text_content or fallback

            if msg.message_type == "text":
                parts.append(f"[Текст]: {text}")
            elif msg.message_type == "voice":
                parts.append(f"[Аудио]: {text}")
            elif msg.message_type == "photo":
                parts.append(f"[Фото]: {text}")

            msg.status = "assembled" 

        # 5. Обновить сессию
        s.assembled_content = "\n".join(parts)
        s.status = "assembled"
        processed_count += 1

    await session.commit()
    return processed_count
