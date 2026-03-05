from datetime import datetime, timedelta
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.config import settings
from src.logger import logger

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def get_credentials() -> Credentials:
    """Загружает и при необходимости обновляет токен."""
    creds = Credentials.from_authorized_user_file(settings.GOOGLE_TOKEN_FILE, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Сохраняем обновлённый токен
        with open(settings.GOOGLE_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


def create_calendar_event(
    title: str,
    date: str,                        # "2026-03-10"
    time_start: Optional[str],        # "15:00" или None → весь день
    duration_minutes: Optional[int],  # 60 или None
    description: Optional[str] = None,
) -> str | None:
    """Создаёт событие в Google Calendar. Возвращает ссылку на событие или None."""
    try:
        creds = get_credentials()
        service = build("calendar", "v3", credentials=creds)

        if time_start:
            # Событие с конкретным временем
            start_dt = datetime.strptime(f"{date} {time_start}", "%Y-%m-%d %H:%M")
            duration = duration_minutes or 60
            end_dt = start_dt + timedelta(minutes=duration)

            event = {
                "summary": title,
                "description": description or "",
                "start": {
                    "dateTime": start_dt.isoformat(),
                    "timeZone": "Europe/Moscow",
                },
                "end": {
                    "dateTime": end_dt.isoformat(),
                    "timeZone": "Europe/Moscow",
                },
            }
        else:
            # Событие на весь день
            event = {
                "summary": title,
                "description": description or "",
                "start": {"date": date},
                "end": {"date": date},
            }

        result = service.events().insert(
            calendarId=settings.GOOGLE_CALENDAR_ID,
            body=event,
        ).execute()

        link = result.get("htmlLink")
        logger.info(f"Событие создано в Google Calendar: {title} → {link}")
        return link

    except HttpError as e:
        logger.error(f"Google Calendar API error: {e}")
        return None
    except Exception as e:
        logger.error(f"Ошибка создания события: {e}")
        return None