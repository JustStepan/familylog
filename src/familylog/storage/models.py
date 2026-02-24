from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from datetime import datetime
from typing import Optional



class Base(DeclarativeBase):
    pass

class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_message_id: Mapped[int] = mapped_column(unique=True)
    chat_id: Mapped[int] = mapped_column()
    author_id: Mapped[int] = mapped_column()
    author_username: Mapped[Optional[str]] = mapped_column(String(50))
    author_name: Mapped[str] = mapped_column(String(50))
    message_type: Mapped[str] = mapped_column(String(10))
    intent: Mapped[Optional[str]] = mapped_column(String(50))
    raw_content: Mapped[Optional[str]] = mapped_column()
    status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    processed_at: Mapped[Optional[datetime]] = mapped_column()


class Setting(Base):
    __tablename__ = "settings"
    
    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[Optional[str]] = mapped_column()