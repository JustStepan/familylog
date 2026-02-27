from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# sqlite3 -header -csv familylog.db "SELECT * FROM messages;" > _local_CSV/messages.csv
# sqlite3 -header -csv familylog.db "SELECT * FROM sessions;" > _local_CSV/sessions.csv
class Base(DeclarativeBase):
    pass


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column()
    author_id: Mapped[int] = mapped_column()
    intent: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="open")
    # open    — сессия активна, принимает сообщения
    # ready   — закрыта, ждёт обработки LLM
    # processed — записана в Obsidian

    assembled_content: Mapped[Optional[str]] = mapped_column()
    # Итоговый текст после сборки всех кусков:
    # [Текст]: ...
    # [Аудио]: ...
    # [Фото]: Заголовок: ... Описание: ...

    opened_at: Mapped[datetime] = mapped_column()
    closed_at: Mapped[Optional[datetime]] = mapped_column()
    last_message_at: Mapped[datetime] = mapped_column()
    # last_message_at обновляется при каждом новом сообщении
    # collector проверяет: если now() - last_message_at > 2ч → закрыть сессию

    messages: Mapped[list["Message"]] = relationship(back_populates="session")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_message_id: Mapped[int] = mapped_column(unique=True)
    chat_id: Mapped[int] = mapped_column()
    author_id: Mapped[int] = mapped_column()
    author_username: Mapped[Optional[str]] = mapped_column(String(50))
    author_name: Mapped[str] = mapped_column(String(50))
    message_type: Mapped[str] = mapped_column(String(10))
    # text / voice / photo / document

    intent: Mapped[Optional[str]] = mapped_column(String(50))
    # note / diary / calendar / reminder / unknown

    session_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sessions.id"))
    # NULL пока сессия не закрыта и не собрана

    raw_content: Mapped[Optional[str]] = mapped_column()
    # file_id для voice и photo

    caption: Mapped[Optional[str]] = mapped_column()
    photo_filename: Mapped[Optional[str]] = mapped_column()
    # подпись к фото если пользователь её добавил

    document_filename: Mapped[Optional[str]] = mapped_column(String(255))
    # оригинальное имя файла из Telegram (e.g., "report.pdf")
    document_mime_type: Mapped[Optional[str]] = mapped_column(String(100))
    # MIME тип из Telegram (e.g., "application/pdf", "text/x-python")

    # блок для пересланных сообщений
    original_caption: Mapped[Optional[str]] = mapped_column()
    is_forwarded: Mapped[bool] = mapped_column(default=False)
    forward_from_name: Mapped[Optional[str]] = mapped_column(String(100))
    forward_from_username: Mapped[Optional[str]] = mapped_column(String(100))
    forward_post_url: Mapped[Optional[str]] = mapped_column(String(200))

    text_content: Mapped[Optional[str]] = mapped_column()
    # для text — оригинальный текст
    # для voice — результат STT
    # для photo — "Заголовок: X. Описание: Y" после vision обработки

    status: Mapped[str] = mapped_column(String(50), default="pending")
    # pending      — только что получено
    # transcribed  — voice расшифрован (text_content заполнен)
    # described    — photo описано (text_content заполнен)
    # assembled    — вошло в session.assembled_content
    # error_stt    — ошибка при транскрипции
    # error_vision — ошибка при описании фото

    created_at: Mapped[datetime] = mapped_column()
    processed_at: Mapped[Optional[datetime]] = mapped_column()

    session: Mapped[Optional["Session"]] = relationship(back_populates="messages")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[Optional[str]] = mapped_column()