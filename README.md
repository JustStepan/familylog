# FamilyLog

Семейный Telegram-бот, который превращает голосовые, текстовые, фото и документ-сообщения в структурированные заметки в Obsidian vault.

## Архитектура

```
Telegram Bot (polling)
    |
    v
[Collector] --- сообщения --> SQLite DB
    |
    v
[STT] --- голосовые --> текст (onnx-asr: GigaAM/Parakeet)
    |
    v
[Vision] --- фото --> описание (Qwen3-VL через LM Studio)
    |
    v
[Documents] --- файлы --> метаданные
    |
    v
[Assembler] --- собирает все части сессии в assembled_content
    |
    v
[LLM] --- assembled_content --> JSON (title, content, tags, related...)
    |
    v
[Obsidian Writer] --- JSON --> markdown файл в vault через Local REST API
```

## Требования

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — менеджер пакетов
- [LM Studio](https://lmstudio.ai/) — локальный LLM инференс
- [Obsidian](https://obsidian.md/) + плагин [Local REST API](https://github.com/coddingtonbear/obsidian-local-rest-api)
- ffmpeg — для конвертации голосовых сообщений

## Установка

```bash
git clone https://github.com/JustStepan/familylog.git
cd familylog
uv sync
```

### Скачивание STT модели

```bash
uv run download_models.py
```

### Настройка .env

```bash
cp .env.example .env
```

```env
BOT_TOKEN=<токен Telegram бота от @BotFather>
OBSIDIAN_VAULT_PATH=/path/to/vault
OBSIDIAN_API_KEY=<ключ из плагина Local REST API>
OBSIDIAN_API_URL=http://localhost:27123

# Режим: offline (LM Studio) | online (OpenRouter)
CONNECTION_TYPE=offline

# LM Studio
LM_STUDIO_URL=http://localhost:1234/v1
LM_STUDIO_BASE_URL=http://localhost:1234

# Модели (offline)
VISION_MODEL_OFFLINE=qwen/qwen3-vl-8b
LLM_MODEL_OFFLINE=openai/gpt-oss-20b
STT_MODEL_OFFLINE=gigaam-v3-e2e-rnnt
```

### Настройка Obsidian vault

Скопируйте шаблоны системных файлов в vault:

```
vault/
  _system/
    AGENT_CONFIG.md       — промпт для LLM-агента
    FAMILY_MEMORY.md      — информация о членах семьи
    TAGS_GLOSSARY.md      — глоссарий тегов
    CURRENT_CONTEXT.md    — последние записи (auto-generated)
    intents/
      note.md             — правила для заметок
      diary.md            — правила для дневника
      calendar.md         — правила для календаря
      task.md             — правила для заданий
```

## Запуск

### Полный автоматический пайплайн

```bash
uv run run.py
```

Автоматически загружает/выгружает модели в LM Studio:
1. Загружает vision модель (если есть фото)
2. Обрабатывает фото
3. Переключает на LLM модель
4. Генерирует заметки
5. Записывает в Obsidian
6. Выгружает модель

### Двухфазный ручной пайплайн

```bash
uv run handle_run.py
```

- **Фаза 1**: сбор сообщений, STT, vision, документы, сборка
- **Пауза**: вручную загрузите нужную LLM в LM Studio
- **Фаза 2**: LLM обработка → запись в Obsidian

### Summary (периодическая сводка)

```bash
uv run run_summary.py           # summary + отправка в Telegram
uv run run_summary.py --dry-run # только генерация, без отправки
```

Собирает все записи с момента последнего summary, генерирует сводку через LLM, сохраняет в `summaries/`, отправляет в Telegram с клавиатурой.

### Установка клавиатуры бота

```bash
uv run setup_bot.py
```

Отправляет reply keyboard с кнопками интентов всем членам семьи.

## Интенты

| Кнопка | Код | Папка | Формат файла |
|--------|-----|-------|------|
| 📝 заметка | note | `notes/` | `Slug_title_DD-ммм-YY.md` |
| 📔 дневник | diary | `diary/` | `DD-ммм-YY_дневник.md` (append) |
| 📅 календарь | calendar | `calendar/` | `Slug_DD-ммм-YY.md` |
| ✅ задание | task | `tasks/` | `неделя_DD-ммм-YY.md` (понедельник, append) |

## Структура vault

```
vault/
  notes/           — заметки (отдельный файл на каждую)
  diary/           — дневник (один файл на день, append)
  calendar/        — события (отдельный файл на каждое)
  tasks/           — задания (один файл на неделю, checkboxes)
  summaries/       — периодические сводки
  attachments/
    photos/        — фотографии
    documents/     — документы (PDF, EPUB, и пр.)
  _system/         — конфигурация агента и память
```

## Структура проекта

```
src/
  config.py                          — настройки (pydantic-settings + .env)
  familylog/
    collector/
      telegram.py                    — сбор сообщений из Telegram API
    processor/
      stt.py                         — Speech-to-Text (onnx-asr)
      vision.py                      — описание фото через Vision LLM
      documents.py                   — обработка документов
      assembler.py                   — сборка сессий
      obsidian_writer.py             — запись в Obsidian (основной модуль)
      summary.py                     — генерация периодических сводок
    LLMs_calls/
      client.py                      — OpenAI-совместимый клиент
      calls.py                       — вызовы LLM (photo, session, summary)
      model_manager.py               — управление моделями LM Studio
    storage/
      database.py                    — SQLAlchemy async engine
      models.py                      — модели БД (Session, Message, Setting)
      telegram_files.py              — скачивание файлов из Telegram
    schema/
      llm.py                         — Pydantic схемы (PhotoOutput)
    bot/
      keyboards.py                   — клавиатура Telegram бота

run.py                — полный автоматический пайплайн
handle_run.py         — двухфазный ручной пайплайн
run_summary.py        — генерация summary + Telegram
setup_bot.py          — установка клавиатуры
reset.py              — сброс БД
download_models.py    — скачивание STT моделей
```

## Пайплайн обработки сообщения

1. **Collector** — polling Telegram API, сохранение в SQLite
2. **STT** — транскрипция voice через GigaAM (offline) или Gemini (online)
3. **Vision** — описание фото через Qwen3-VL (offline) или Qwen-VL-Plus (online)
4. **Documents** — скачивание файлов, формирование метаданных
5. **Assembler** — объединение всех частей сессии в `assembled_content`
6. **LLM** — генерация JSON: title, content (markdown + frontmatter), tags, related, people, context_summary
7. **Obsidian Writer** — запись файла через Local REST API, обновление системных файлов (CURRENT_CONTEXT, TAGS_GLOSSARY, FAMILY_MEMORY), поиск related по тегам, backlinks

## Дополнительная документация

- [VULNERABILITIES.md](VULNERABILITIES.md) — аудит безопасности и предложения по улучшению
- [LLAMA_MIGRATION.md](LLAMA_MIGRATION.md) — план миграции с LM Studio на llama.cpp
