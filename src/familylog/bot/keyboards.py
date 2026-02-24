from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_intent_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="📝 Заметка", callback_data="intent_note"),
            InlineKeyboardButton(text="📔 Дневник", callback_data="intent_diary"),
        ],
        [
            InlineKeyboardButton(text="📅 Календарь", callback_data="intent_calendar"),
            InlineKeyboardButton(text="⏰ Напоминание", callback_data="intent_reminder"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)