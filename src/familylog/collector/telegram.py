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

async def get_setting(session: AsyncSession, key: str) -> str | None:
    """Читает произвольное значение из таблицы Settings по ключу."""
    result = await session.execute(
        select(Setting).where(Setting.key == key)
    )
    setting = result.scalar_one_or_none()
    return setting.value if setting else None


async def save_setting(session: AsyncSession, key: str, value: str) -> None:
    """Сохраняет произвольное значение в таблицу Settings."""
    result = await session.execute(
        select(Setting).where(Setting.key == key)
    )
    setting = result.scalar_one_or_none()

    if setting:
        setting.value = value
    else:
        session.add(Setting(key=key, value=value))

    await session.commit()


async def get_last_update_id(session: AsyncSession) -> int:
    value = await get_setting(session, "last_update_id")
    return int(value) if value else 0


async def save_last_update_id(session: AsyncSession, update_id: int) -> None:
    await save_setting(session, "last_update_id", str(update_id))


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
        select(Session).where(Session.status == "open")
    )
    open_sessions = result.scalars().all()

    for s in open_sessions:
        s.status = "ready"
        s.closed_at = datetime.now()

    if open_sessions:
        await session.commit()

    return len(open_sessions)


def is_service_message(text: str) -> bool:
    return text.strip().lower() in INTENT_MARKERS


def parse_intent(text: str) -> str:
    return INTENT_MARKERS.get(text.strip().lower(), "unknown")


async def fetch_updates(offset: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{TG_API}/getUpdates",
            params={"offset": offset + 1, "limit": 200, "timeout": 10},
        )
        data = response.json()

        if not data["ok"]:
            raise Exception(f"Telegram API error: {data}")

        return data["result"]


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
    await db.flush()
    return new_session


# ─── Основная функция ────────────────────────────────────────────────────────

def parse_forward(msg: dict) -> dict:
    """Извлекает метаданные пересланного сообщения."""
    origin = msg.get("forward_origin")
    if not origin:
        return {}
    
    if origin["type"] == "channel":
        chat = origin["chat"]
        username = chat.get("username")
        msg_id = origin.get("message_id")
        url = f"https://t.me/{username}/{msg_id}" if username and msg_id else None
        return {
            "is_forwarded": True,
            "forward_from_name": chat.get("title"),
            "forward_from_username": username,
            "forward_post_url": url,
        }
    
    elif origin["type"] == "user":
        user = origin["sender_user"]
        name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
        return {
            "is_forwarded": True,
            "forward_from_name": name,
            "forward_from_username": user.get("username"),
            "forward_post_url": None,
        }
    
    return {}

async def collect_messages(session: AsyncSession) -> int:
    """Собирает новые сообщения из Telegram и сохраняет в БД.

    Логика сессий:
    - Маркер → закрыть старую сессию, открыть новую, сохранить last_intent
    - Контент с открытой сессией → привязать к ней
    - Контент без открытой сессии → открыть сессию с last_intent пользователя
      (или "unknown" если маркеров ещё не было)
    """
    last_update_id = await get_last_update_id(session)
    updates = await fetch_updates(last_update_id)

    if not updates:
        return 0

    saved_count = 0

    for update in updates:
        update_id = update["update_id"]

        if "message" not in update:
            await save_last_update_id(session, update_id)
            continue

        msg = update["message"]
        user = msg["from"]
        author_id = user["id"]
        chat_id = msg["chat"]["id"]
        msg_timestamp = datetime.fromtimestamp(msg["date"])

        # ── Разбираем тип контента ──────────────────────────────────────────

        if "text" in msg:
            text = msg["text"]

            # Блок обработки сервисных сообщений и работы с сессиями
            if is_service_message(text):
                intent = parse_intent(text)
                print(f"DEBUG: маркер '{text}' → intent='{intent}'")

                # Закрываем предыдущую открытую сессию этого автора
                existing = await get_open_session(session, author_id)
                if existing:
                    await close_session(session, existing)
                    print(f"DEBUG: закрыта сессия id={existing.id}")

                # Открываем новую сессию
                await open_session(session, author_id, chat_id, intent, msg_timestamp)

                # Запоминаем последний intent пользователя
                await save_setting(session, f"last_intent_{author_id}", intent)
                await session.commit()

                await save_last_update_id(session, update_id)
                continue

            content_type = "text"
            raw_content = None
            text_content = text
            caption = None

        elif "voice" in msg:
            content_type = "voice"
            raw_content = msg["voice"]["file_id"] # Здесь пока только ссылка на файл
            text_content = None
            caption = None

        elif "photo" in msg:
            content_type = "photo"
            raw_content = msg["photo"][-1]["file_id"] # Здесь пока только ссылка на файл [-1] - это лучшее качество
            text_content = None
            caption = msg.get("caption") # Заголовок если передан с фото
            
            # Помечаем пересланные сообщения
            forward = msg.get("forward_origin")
            if forward and forward.get("type") == "channel":
                channel = forward["chat"]
                forward_info = f"[Переслано из @{channel.get('username', channel['title'])}]"
                caption = f"{forward_info}\n{caption}" if caption else forward_info # Если переслано то в заголовке описание поста (обычно так)

        else:
            await save_last_update_id(session, update_id)
            continue

        # ── Привязываем к сессии ────────────────────────────────────────────

        current_session = await get_open_session(session, author_id)

        if current_session is None:
            # Нет открытой сессии — берём последний известный intent
            last_intent = await get_setting(session, f"last_intent_{author_id}") or "unknown"
            print(f"DEBUG: нет открытой сессии, используем last_intent='{last_intent}'")
            current_session = await open_session(
                session, author_id, chat_id, last_intent, msg_timestamp
            )

        current_session.last_message_at = msg_timestamp

        # ── Сохраняем сообщение ─────────────────────────────────────────────
        
        forward_data = parse_forward(msg)


        db_message = Message(
            telegram_message_id=msg["message_id"],
            chat_id=chat_id,
            author_id=author_id,
            author_username=user.get("username"),
            author_name=user.get("first_name", "Unknown"),
            message_type=content_type,
            intent=current_session.intent,
            session_id=current_session.id,
            raw_content=raw_content,
            text_content=text_content,
            caption=caption,
            status="pending",
            created_at=msg_timestamp,
            original_caption=caption,  # сохраняем до vision обработки
            is_forwarded=forward_data.get("is_forwarded", False),
            forward_from_name=forward_data.get("forward_from_name"),
            forward_from_username=forward_data.get("forward_from_username"),
            forward_post_url=forward_data.get("forward_post_url"),
        )
        session.add(db_message)
        await session.commit()

        saved_count += 1
        print(f"DEBUG: сохранено {content_type} → session_id={current_session.id}, intent={current_session.intent}")

        await save_last_update_id(session, update_id)

    return saved_count