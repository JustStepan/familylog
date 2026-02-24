import httpx
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..storage.models import Message, Setting
from ..config import settings

# Служебные маркеры — intent определяется по тексту сообщения
INTENT_MARKERS = {
    "📝 заметка": "note",
    "📔 дневник": "diary", 
    "📅 календарь": "calendar",
    "⏰ напоминание": "reminder",
}

# Базовый URL Telegram Bot API
TG_API = f"https://api.telegram.org/bot{settings.BOT_TOKEN}"


async def get_last_update_id(session: AsyncSession) -> int:
    """Читает из БД последний обработанный update_id.
    Если первый запуск — возвращает 0."""
    result = await session.execute(
        select(Setting).where(Setting.key == "last_update_id")
    )
    setting = result.scalar_one_or_none()
    return int(setting.value) if setting else 0


async def save_last_update_id(session: AsyncSession, update_id: int) -> None:
    """Сохраняет последний обработанный update_id в БД."""
    result = await session.execute(
        select(Setting).where(Setting.key == "last_update_id")
    )
    setting = result.scalar_one_or_none()
    
    if setting:
        setting.value = str(update_id)
    else:
        # Первый запуск — создаём запись
        session.add(Setting(key="last_update_id", value=str(update_id)))
    
    await session.commit()


def is_service_message(text: str) -> bool:
    """Проверяет является ли текст служебным маркером."""
    # strip() убирает пробелы по краям на случай "!note " с пробелом
    return text.strip().lower() in INTENT_MARKERS


def parse_intent(text: str) -> str:
    """Извлекает intent из служебного сообщения."""
    return INTENT_MARKERS.get(text.strip().lower(), "unknown")


async def fetch_updates(offset: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=30.0) as client:  # таймаут httpx
        response = await client.get(
            f"{TG_API}/getUpdates",
            params={
                "offset": offset + 1,
                "limit": 100,
                "timeout": 10,  # long polling таймаут для Telegram
            }
        )
        data = response.json()
        
        if not data["ok"]:
            raise Exception(f"Telegram API error: {data}")
        
        return data["result"]


async def collect_messages(session: AsyncSession) -> int:
    """Основная функция сбора сообщений.
    Возвращает количество сохранённых сообщений."""
    
    last_update_id = await get_last_update_id(session)
    updates = await fetch_updates(last_update_id)
    
    if not updates:
        return 0
    
    saved_count = 0
    current_intent = "unknown"
    expecting_content = False  # ждём ли содержательное сообщение
    
    for update in updates:
        # update_id — уникальный номер каждого события от Telegram
        update_id = update["update_id"]
        
        # Нас интересуют только сообщения, не другие события
        if "message" not in update:
            await save_last_update_id(session, update_id)
            continue
        
        msg = update["message"]
        
        if "text" in msg:
            text = msg["text"]

            # Если НЕ ждём содержательное И это маркер — запомнить intent
            if not expecting_content and is_service_message(text):
                current_intent = parse_intent(text)
                expecting_content = True
                print(f"DEBUG: маркер '{text}' → intent='{current_intent}'")
                await save_last_update_id(session, update_id)
                continue

            # Если это маркер но expecting_content=True — предыдущий маркер
            # был без содержательного. Обновляем intent на новый маркер.
            if expecting_content and is_service_message(text):
                current_intent = parse_intent(text)
                print(f"DEBUG: повторный маркер '{text}' → intent='{current_intent}'")
                await save_last_update_id(session, update_id)
                continue

            # Это содержательное сообщение
            content_type = "text"
            raw_content = text
            print(f"DEBUG: содержательное '{text}' → intent='{current_intent}'")
            
        elif "voice" in msg:
            content_type = "voice"
            # file_id — временный ID файла на серверах Telegram
            # скачаем позже в processor
            raw_content = msg["voice"]["file_id"]
            
        elif "photo" in msg:
            content_type = "photo"
            # photo — список размеров, берём последний (максимальное качество)
            raw_content = msg["photo"][-1]["file_id"]
            
        else:
            # Неподдерживаемый тип — пропускаем
            await save_last_update_id(session, update_id)
            continue
        
        # Извлекаем данные об авторе
        user = msg["from"]
        
        # Сохраняем сообщение в БД
        db_message = Message(
            telegram_message_id=msg["message_id"],
            chat_id=msg["chat"]["id"],
            author_id=user["id"],
            author_username=user.get("username"),  # может отсутствовать
            author_name=user.get("first_name", "Unknown"),
            message_type=content_type,
            intent=current_intent,
            raw_content=raw_content,
            status="pending",
            created_at=datetime.fromtimestamp(msg["date"]),
            # используем время Telegram, не текущее время машины
        )
        session.add(db_message)
        await session.commit()
        
        saved_count += 1
        current_intent = "unknown"
        expecting_content = False  # сбросили — снова ждём маркер
        await save_last_update_id(session, update_id)
    
    return saved_count