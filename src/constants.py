MIME_MAP = {
    ".pdf": "application/pdf",
    ".epub": "application/epub+zip",
    ".py": "text/x-python",
    ".txt": "text/plain",
    ".json": "application/json",
    ".csv": "text/csv",
    ".md": "text/markdown",
    ".html": "text/html",
    ".fb2":  "application/x-fictionbook+xml",
    ".rar":  "application/vnd.rar",
    ".7z":   "application/x-7z-compressed",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xml": "application/xml",
    ".zip": "application/zip",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}



RUSSIAN_MONTHS = [
    "янв", "фев", "мар", "апр", "май", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
]

INTENT_FOLDERS = {
    "note": "notes",
    "diary": "diary",
    "calendar": "calendar",
    "task": "tasks",
}


BOT_WELCOME_TEXT = """
👋 Добро пожаловать в FamilyLog!

Как пользоваться:
1. Выбери тип записи кнопкой внизу экрана
2. Отправляй голосовые, фото или текст — они войдут в сессию
3. Когда закончил — нажми ту же кнопку снова (закроет сессию)

Типы записей:
📝 Заметка — быстрая мысль, информация
📔 Дневник — события дня  
📅 Календарь — событие/напоминание
✅ Задание — что нужно сделать
"""

KEYBOARD_BUTTONS = [
    ["📝 заметка", "📔 дневник"],
    ["📅 календарь", "✅ задание"],
]

SUMMARY_MARKER_PATH = "_system/LAST_SUMMARY.md"
SUMMARY_FOLDERS = ("notes", "diary", "calendar", "tasks")
NOISE_TAGS = {"дневник", "заметка", "семья", "планы", "мысли", "задания", "календарь"}