import httpx
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..storage.models import Message, Setting, Session
from src.config import settings

INTENT_MARKERS = {
    "📝 заметка": "note",
    "📔 дневник": "diary",
    "📅 календарь": "calendar",
    "⏰ напоминание": "reminder",
}

TG_API = f"https://api.telegram.org/bot{settings.BOT_TOKEN}"


# ─── Вспомогательные функции ────────────────────────────────────────────────

async def get_last_update_id(session: AsyncSession) -> int:
    result = await session.execute(
        select(Setting).where(Setting.key == "last_update_id")
    )
    setting = result.scalar_one_or_none()
    return int(setting.value) if setting else 0


async def save_last_update_id(session: AsyncSession, update_id: int) -> None:
    result = await session.execute(
        select(Setting).where(Setting.key == "last_update_id")
    )
    setting = result.scalar_one_or_none()

    if setting:
        setting.value = str(update_id)
    else:
        session.add(Setting(key="last_update_id", value=str(update_id)))

    await session.commit()


async def get_open_session(session: AsyncSession, author_id: int) -> Session | None:
    result = await session.execute(
        select(Session).where(
            Session.author_id == author_id,
            Session.status == "open"
        )
    )
    return result.scalar_one_or_none()


async def close_session(session: AsyncSession, db_session: Session) -> None:
    db_session.status = "ready"
    db_session.closed_at = datetime.now()
    await session.commit()


async def close_all_open_sessions(session: AsyncSession) -> int:
    result = await session.execute(
        select(Session).where(
            Session.status == "open"
        )
    )
    open_sessions = result.scalars().all()

    for s in open_sessions:
        s.status = "ready"
        s.closed_at = datetime.now()

    if open_sessions:
        await session.commit()

    return len(open_sessions)

# async def close_expired_sessions(session: AsyncSession) -> int:
#     from datetime import timedelta
#     cutoff = datetime.now() - timedelta(hours=2)

#     result = await session.execute(
#         select(Session).where(
#             Session.status == "open",
#             Session.last_message_at < cutoff
#         )
#     )
#     expired = result.scalars().all()

#     for s in expired:
#         s.status = "ready"
#         s.closed_at = datetime.now()

#     if expired:
#         await session.commit()

#     return len(expired)


def is_service_message(text: str) -> bool:
    return text.strip().lower() in INTENT_MARKERS


def parse_intent(text: str) -> str:
    return INTENT_MARKERS.get(text.strip().lower(), "unknown")


async def fetch_updates(offset: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{TG_API}/getUpdates",
            params={"offset": offset + 1, "limit": 100, "timeout": 10},
        )
        data = response.json()

        if not data["ok"]:
            raise Exception(f"Telegram API error: {data}")

        return data["result"]


# ─── Создание сессии ────────────────────────────────────────────────────────

async def open_session(
    db: AsyncSession,
    author_id: int,
    chat_id: int,
    intent: str,
    msg_timestamp: datetime,
) -> Session:
    """Создаёт новую открытую сессию и возвращает её с заполненным id.
    
    flush() отправляет INSERT в БД в рамках текущей транзакции,
    что даёт нам session.id — но не делает COMMIT.
    Это важно: если последующий код упадёт, транзакция откатится.
    """
    new_session = Session(
        chat_id=chat_id,
        author_id=author_id,
        intent=intent,
        status="open",
        opened_at=msg_timestamp,
        last_message_at=msg_timestamp,
    )
    db.add(new_session)

    # flush → INSERT выполнен → id присвоен → транзакция ещё открыта
    await db.flush()

    return new_session


# ─── Основная функция ────────────────────────────────────────────────────────

async def collect_messages(session: AsyncSession) -> int:
    """Собирает новые сообщения из Telegram и сохраняет в БД.

    Логика сессий:
    - Маркер ("📝 заметка") → закрыть старую сессию, открыть новую
    - Контент без маркера  → привязать к открытой сессии (или создать с intent="unknown")

    Возвращает количество сохранённых сообщений (не считая маркеры).
    """

    last_update_id = await get_last_update_id(session)
    updates = await fetch_updates(last_update_id)

    if not updates:
        return 0

    saved_count = 0

    for update in updates:
        update_id = update["update_id"]

        # Нас интересуют только message-события
        if "message" not in update:
            await save_last_update_id(session, update_id)
            continue

        msg = update["message"]
        user = msg["from"]
        author_id = user["id"]
        chat_id = msg["chat"]["id"]

        # Время сообщения берём из Telegram (Unix timestamp → datetime)
        msg_timestamp = datetime.fromtimestamp(msg["date"])

        # ── Разбираем тип контента ──────────────────────────────────────────

        if "text" in msg:
            text = msg["text"]

            # Маркер интента — не контент, а управляющее сообщение
            if is_service_message(text):
                intent = parse_intent(text)
                print(f"DEBUG: маркер '{text}' → intent='{intent}'")

                # Закрываем предыдущую открытую сессию этого пользователя
                existing = await get_open_session(session, author_id)
                if existing:
                    await close_session(session, existing)
                    print(f"DEBUG: закрыта сессия id={existing.id}")

                # Открываем новую сессию с нужным интентом
                await open_session(session, author_id, chat_id, intent, msg_timestamp)
                await session.commit()

                await save_last_update_id(session, update_id)
                continue  # маркер не сохраняем как Message

            # Обычный текст — это контент
            content_type = "text"
            raw_content = None
            text_content = text
            caption = None

        elif "voice" in msg:
            content_type = "voice"
            raw_content = msg["voice"]["file_id"]  # скачаем позже в stt.py
            text_content = None
            caption = None

        elif "photo" in msg:
            content_type = "photo"
            raw_content = msg["photo"][-1]["file_id"]  # максимальное качество
            text_content = None
            caption = msg.get("caption")  # подпись к фото (опционально)

        else:
            # Неподдерживаемый тип — пропускаем
            await save_last_update_id(session, update_id)
            continue

        # ── Привязываем к сессии ────────────────────────────────────────────

        current_session = await get_open_session(session, author_id)

        if current_session is None:
            # Контент пришёл без маркера — создаём сессию с unknown intent
            print(f"DEBUG: нет открытой сессии для author_id={author_id}, создаём unknown")
            current_session = await open_session(
                session, author_id, chat_id, "unknown", msg_timestamp
            )

        # Обновляем время последнего сообщения в сессии
        # (используется для таймаута 2ч)
        current_session.last_message_at = msg_timestamp

        # ── Сохраняем сообщение ─────────────────────────────────────────────

        db_message = Message(
            telegram_message_id=msg["message_id"],
            chat_id=chat_id,
            author_id=author_id,
            author_username=user.get("username"),
            author_name=user.get("first_name", "Unknown"),
            message_type=content_type,
            intent=current_session.intent,  # наследуем от сессии
            session_id=current_session.id,
            raw_content=raw_content,
            text_content=text_content,
            caption=caption,
            status="pending",
            created_at=msg_timestamp,
        )
        session.add(db_message)
        await session.commit()

        saved_count += 1
        print(f"DEBUG: сохранено {content_type} → session_id={current_session.id}, intent={current_session.intent}")

        await save_last_update_id(session, update_id)

    return saved_count