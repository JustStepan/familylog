import httpx
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.logger import logger
from ..storage.models import Message, Setting, Session
from src.config import settings


INTENT_MARKERS = {
    "📝 заметка": "note",
    "📔 дневник": "diary",
    "📅 календарь": "calendar",
    "✅ задание": "task",
}

TG_API = f"https://api.telegram.org/bot{settings.BOT_TOKEN}"


# ─── Вспомогательные функции ────────────────────────────────────────────────

async def get_setting(session: AsyncSession, key: str) -> str | None:
    """Читает значение из таблицы Settings по ключу."""
    result = await session.execute(
        select(Setting).where(Setting.key == key)
    )
    setting = result.scalar_one_or_none()
    return setting.value if setting else None


async def save_setting(session: AsyncSession, key: str, value: str) -> None:
    """Сохраняет значение в таблицу Settings."""
    result = await session.execute(
        select(Setting).where(Setting.key == key)
    )
    setting = result.scalar_one_or_none()

    if setting:
        setting.value = value
        logger.info(f'Таблица settings обновлена параметры: {setting.key} = {setting.value}')
    else:
        session.add(Setting(key=key, value=value))
        logger.info(f'В таблице settings создана новая запись: {key} = {value}')


async def get_last_update_id(session: AsyncSession) -> int:
    """Получаем id последнего сообщения в чате
    Нужно для передачи в телегу для извлечения только новых сообщений"""
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


async def close_old_open_sessions(session: AsyncSession) -> int:
    """Закрывает сессии, в которых последнее сообщение старше SESSION_TIMEOUT_MINUTES."""
    cutoff = datetime.now() - timedelta(minutes=settings.SESSION_TIMEOUT_MINUTES)

    result = await session.execute(
        select(Session).where(
            Session.status == "open",
            Session.last_message_at < cutoff,
        )
    )
    open_sessions = result.scalars().all()

    for s in open_sessions:
        s.status = "ready"
        s.closed_at = datetime.now()

    if open_sessions:
        await session.commit()
    logger.info(f'Закрыто {len(open_sessions)} сессий старше {settings.SESSION_TIMEOUT_MINUTES} минут')
    return len(open_sessions)


def is_service_message(text: str) -> bool:
    return text.strip().lower() in INTENT_MARKERS


def parse_intent(text: str) -> str:
    return INTENT_MARKERS.get(text.strip().lower(), "unknown") # по идее unknown быть не может никогда поскольку маркеры проверяются здесь is_service_message() и условие проверки точно такое же.


async def fetch_updates(offset: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{TG_API}/getUpdates",
            params={"offset": offset + 1, "limit": 200, "timeout": 5},
        )
        logger.info(f'Пробуем достать данные из телеграма параметры offset = {offset} - это значение id последнего сообщения в чате.')
        data = response.json()

        if not data["ok"]:
            raise Exception(f"Telegram API error: {data}")
        logger.info(f'Данные от телеграма получены. Всего сообщений: {len(data)}')
        logger.debug(f'Данные от телеграма получены. = \n {(data)}\n')
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
    logger.debug(f'Новая сессия пользователя {author_id} создана с intent {intent}.')

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
        logger.debug(f'Получены пересланные сообщения из ЧАТА: {chat}, ПОЛЬЗОВАТЕЛЬ: {username}, ЗАГОЛОВОК: {chat.get("title")}')
        return {
            "is_forwarded": True,
            "forward_from_name": chat.get("title"),
            "forward_from_username": username,
            "forward_post_url": url,
        }
    
    elif origin["type"] == "user":
        user = origin["sender_user"]
        name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
        logger.debug(f'Получены пересланные сообщения от ПОЛЬЗОВАТЕЛЯ: {user}, ЗАГОЛОВОК: {origin.get("title")}')
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
    logger.info(f'id последнего добавленного сообщения в таблице settings = {last_update_id}')
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
                logger.debug(f"Маркер '{text}' → intent='{intent}'")

                # Закрываем предыдущую открытую сессию этого автора
                existing = await get_open_session(session, author_id)
                if existing:
                    await close_session(session, existing)
                    logger.info(f'Закрыта сессия {existing.id} автора {user} с intent {existing.intent}')

                # Открываем новую сессию
                await open_session(session, author_id, chat_id, intent, msg_timestamp)

                # Запоминаем последний intent пользователя
                await save_setting(session, f"last_intent_{author_id}", intent)
                await save_last_update_id(session, update_id)
                await session.commit()
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
                logger.debug(f'Получили пересланное фото "{forward_info}"')
                caption = f"{forward_info}\n{caption}" if caption else forward_info # Если переслано то в заголовке описание поста (обычно так)

        elif "document" in msg:
            doc = msg["document"]
            mime = doc.get("mime_type", "")

            # Аудиофайлы (mp3, ogg, wav и пр.) → через STT, не как документы
            if mime.startswith("audio/"):
                content_type = "voice"
                raw_content = doc["file_id"]
                text_content = None
                caption = None
                logger.debug(f"Аудио-документ ({mime}) → Передаем как голосовое на распознование текста")
            else:
                content_type = "document"
                raw_content = doc["file_id"]
                text_content = None
                caption = msg.get("caption")

                # Помечаем пересланные документы
                forward = msg.get("forward_origin")
                if forward and forward.get("type") == "channel":
                    channel = forward["chat"]
                    forward_info = f"[Переслано из @{channel.get('username', channel['title'])}]"
                    logger.debug(f'Получили пересланный документ "{forward_info}"')
                    caption = f"{forward_info}\n{caption}" if caption else forward_info

        else:
            await save_last_update_id(session, update_id)
            continue

        # ── Привязываем к сессии ────────────────────────────────────────────

        current_session = await get_open_session(session, author_id)

        if current_session is None:
            # Нет открытой сессии — берём последний известный intent
            last_intent = await get_setting(session, f"last_intent_{author_id}") or "unknown"
            logger.debug(f"Нет открытой сессии, используем last_intent='{last_intent}'")
            current_session = await open_session(
                session, author_id, chat_id, last_intent, msg_timestamp
            )

        current_session.last_message_at = msg_timestamp

        # ── Сохраняем сообщение ─────────────────────────────────────────────
        
        forward_data = parse_forward(msg)


        # Для документов сохраняем метаданные файла
        doc_filename = None
        doc_mime_type = None
        if content_type == "document":
            doc_info = msg["document"]
            doc_filename = doc_info.get("file_name", "unknown_file")
            doc_mime_type = doc_info.get("mime_type", "application/octet-stream")
            logger.info(f"Получен документ: '{doc_filename}', тип: {doc_mime_type}")

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
            is_forwarded=forward_data.get("is_forwarded", False), # или словарь с данными или None
            forward_from_name=forward_data.get("forward_from_name"),
            forward_from_username=forward_data.get("forward_from_username"),
            forward_post_url=forward_data.get("forward_post_url"),
            document_filename=doc_filename,
            document_mime_type=doc_mime_type,
        )
        session.add(db_message)
        await session.commit()

        saved_count += 1
        logger.debug(f"Сохранено {content_type} → session_id={current_session.id}, intent={current_session.intent}")

        await save_last_update_id(session, update_id)

    return saved_count