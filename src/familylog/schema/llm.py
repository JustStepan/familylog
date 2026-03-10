from pydantic import BaseModel, Field, field_validator


class PhotoOutput(BaseModel):
    caption: str = Field(..., description='Заголовок обрабатываемого изображения')
    description: str = Field(..., description='Описание обрабатываемого изображения')


class CalendarEvent(BaseModel):
    date: str = Field(..., description="Дата события в формате YYYY-MM-DD")
    time_start: str | None = Field(None, description="Время начала HH:MM или null")
    duration_minutes: int = Field(60, description="Продолжительность события в минутах")
    description: str = Field("", description="Краткое описание для Google Calendar")


class SessionOutput(BaseModel):
    title: str = Field("Без заголовка", description="Краткий заголовок 3-7 слов")
    content: str = Field(..., description="Полный markdown с YAML frontmatter")
    tags: list[str] = Field(default_factory=list, description="Теги с #")
    related: list[str] = Field(default_factory=list, description="Связанные файлы")
    people_mentioned: list[str] = Field(default_factory=list, description="Упомянутые люди")
    new_people: list[str] = Field(default_factory=list, description="Новые люди не из памяти")
    context_summary: str = Field("", description="2-4 предложения о сути записи")
    calendar_event: CalendarEvent | None = Field(None, description="Только для intent=calendar")

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, v: object) -> list[str]:
        """Нормализует теги: добавляет # если нет, заменяет пробелы на _, убирает пустые."""
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, list):
            return []
        result = []
        for tag in v:
            if not isinstance(tag, str):
                continue
            tag = tag.strip().replace(" ", "_")
            if not tag:
                continue
            if not tag.startswith("#"):
                tag = "#" + tag
            result.append(tag)
        return result


class SummaryOutput(BaseModel):
    summary_text: str = Field(..., description="Текст сводки для Telegram")
    content: str = Field(..., description="Полный markdown summary с frontmatter")