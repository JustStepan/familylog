# 📓 FamilyLog

> Семейный дневник, который ведёт себя сам

FamilyLog превращает голосовые сообщения, фото, текст и документы из Telegram в красивые структурированные заметки в вашем личном [Obsidian](https://obsidian.md/) vault — автоматически, без лишних действий.

---

## Как это работает

Вы просто пишете боту как обычно. Выбираете тип записи кнопкой, отправляете голосовые сообщения, фото или текст — и всё. Раз в день (или когда вам удобно) запускаете один скрипт, и FamilyLog:

- расшифровывает голосовые сообщения в текст
- описывает фотографии
- группирует всё в логичные сессии
- генерирует красивые markdown-заметки с тегами, связями и frontmatter
- записывает в ваш Obsidian vault

Периодически бот присылает сводку — что было записано за неделю.

```
Вы пишете боту в Telegram
        ↓
[раз в день] uv run run.py
        ↓
STT → Vision → LLM → Obsidian
        ↓
Готовые заметки в vault
```

---

## Что умеет бот

Нажмите на кнопку внизу экрана — и начнётся новая сессия записи:

| Кнопка | Что сохраняется |
|--------|-----------------|
| 📝 Заметка | Мысль, идея, информация — отдельный файл |
| 📔 Дневник | События дня — добавляется в файл текущего дня |
| 📅 Календарь | Событие или напоминание — отдельный файл |
| ✅ Задание | Задача с чекбоксом — в файл текущей недели |

**Как пользоваться:**
1. Нажмите кнопку (например, 📔 Дневник) — сессия открыта
2. Отправляйте голосовые, фото, текст — всё войдёт в одну запись
3. Когда закончили — нажмите ту же кнопку снова (или любую другую — предыдущая сессия закроется)
4. Можно пересылать сообщения из каналов — источник сохранится автоматически

---

## Требования

Перед установкой убедитесь, что у вас есть:

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** — менеджер пакетов Python
- **[ffmpeg](https://ffmpeg.org/)** — для обработки голосовых сообщений
- **[LM Studio](https://lmstudio.ai/)** — для локальной обработки через LLM (если используете offline режим)
- **[Obsidian](https://obsidian.md/)** + плагин **[Local REST API](https://github.com/coddingtonbear/obsidian-local-rest-api)**
- Telegram бот — создаётся через [@BotFather](https://t.me/BotFather)

---

## Установка

### 1. Клонируйте репозиторий

```bash
git clone https://github.com/JustStepan/familylog.git
cd familylog
uv sync
```

### 2. Скачайте STT модель

```bash
uv run download_models.py
```

Это загрузит модель для распознавания речи (~225–892 MB в зависимости от выбранной модели).

### 3. Настройте `.env`

```bash
cp .env.example .env
```

Откройте `.env` и заполните:

```env
# Telegram
BOT_TOKEN=ваш_токен_от_BotFather
FAMILY_CHAT_IDS=[123456789, 987654321]   # Telegram ID всех членов семьи

# Obsidian
OBSIDIAN_VAULT_PATH=/путь/к/вашему/vault
OBSIDIAN_API_KEY=ключ_из_плагина_Local_REST_API
OBSIDIAN_API_URL=http://localhost:27123

# Режим работы: offline (LM Studio) | online (OpenRouter)
CONNECTION_TYPE=offline

# Модели (offline — LM Studio)
LLM_MODEL_OFFLINE=openai/gpt-oss-20b
VISION_MODEL_OFFLINE=qwen3.5-4b-mlx
STT_MODEL_OFFLINE=gigaam-v3-e2e-rnnt

# Суммаризация
SUMMARY_INTERVAL_DAYS=7
```

> **Как узнать свой Telegram ID:** напишите боту [@userinfobot](https://t.me/userinfobot)

### 4. Настройте Obsidian vault

Скопируйте шаблоны системных файлов в ваш vault:

```bash
cp -r vault_templates/_system /путь/к/vault/_system
```

Структура которая должна получиться:

```
vault/
  _system/
    AGENT_CONFIG.md       ← инструкции для LLM-агента
    FAMILY_MEMORY.md      ← информация о членах семьи (заполните вручную)
    TAGS_GLOSSARY.md      ← глоссарий тегов
    CURRENT_CONTEXT.md    ← последние записи (обновляется автоматически)
    LAST_SUMMARY.md       ← время последней сводки
    intents/
      note.md
      diary.md
      calendar.md
      task.md
```

Откройте `_system/FAMILY_MEMORY.md` и добавьте информацию о членах семьи — имена, Telegram ID, роли. Это поможет боту правильно определять авторов записей.

---

## Запуск

### Основной пайплайн

```bash
uv run run.py
```

Запускает полный цикл: сбор сообщений → STT → Vision → LLM → запись в Obsidian.

Если с момента последней суммаризации прошло `SUMMARY_INTERVAL_DAYS` дней — автоматически сгенерирует сводку и отправит в Telegram.

### Принудительная суммаризация

```bash
uv run run.py --summary
```

Генерирует и отправляет сводку прямо сейчас, независимо от расписания.

### Отправить клавиатуру боту

```bash
uv run setup_bot.py
```

Отправляет reply-клавиатуру всем членам семьи. Запускайте при первой настройке или если клавиатура пропала.

### Скачать STT модели

```bash
uv run download_models.py
```

---

## Структура vault после работы

```
vault/
  notes/        ← заметки (отдельный файл на каждую)
  diary/        ← дневник (один файл на день, записи добавляются)
  calendar/     ← события (отдельный файл на каждое)
  tasks/        ← задания (один файл на неделю, чекбоксы)
  summaries/    ← еженедельные сводки
  attachments/
    photos/     ← фотографии из Telegram
    documents/  ← документы (PDF, EPUB и др.)
  _system/      ← конфигурация (не трогайте руками кроме FAMILY_MEMORY)
```

---

## Структура проекта

```
familylog/
├── run.py                    ← главная точка входа
├── setup_bot.py              ← отправка клавиатуры
├── download_models.py        ← скачивание STT моделей
├── vault_templates/          ← шаблоны системных файлов Obsidian
└── src/
    ├── config.py             ← все настройки (pydantic-settings + .env)
    ├── constants.py          ← текстовые константы
    └── familylog/
        ├── collector/
        │   └── telegram.py   ← сбор сообщений из Telegram
        ├── processor/
        │   ├── stt.py        ← расшифровка голосовых (GigaAM / Parakeet)
        │   ├── vision.py     ← описание фото (Qwen-VL)
        │   ├── documents.py  ← обработка документов
        │   ├── assembler.py  ← сборка сессий
        │   ├── summary.py    ← генерация сводок
        │   └── obsidian/
        │       ├── api.py          ← Obsidian REST API
        │       ├── general_data.py ← загрузка системных файлов
        │       ├── utils.py        ← генерация имён файлов
        │       └── write_files.py  ← запись и обновление vault
        ├── LLMs_calls/
        │   ├── client.py        ← OpenAI-совместимый клиент
        │   ├── calls.py         ← вызовы LLM
        │   └── model_manager.py ← управление моделями LM Studio
        ├── storage/
        │   ├── database.py      ← SQLAlchemy async
        │   ├── models.py        ← таблицы БД
        │   └── telegram_files.py ← скачивание файлов
        └── bot/
            ├── keyboards.py  ← построение клавиатуры
            └── sender.py     ← отправка сообщений в Telegram
```

---

## Технологический стек

| Компонент | Технология |
|-----------|-----------|
| Backend | Python 3.12, asyncio |
| БД | SQLite + SQLAlchemy async |
| Telegram | aiogram, httpx |
| STT (offline) | onnx-asr: GigaAM v3 (русский язык) |
| STT (online) | Google Gemini via OpenRouter |
| Vision (offline) | Qwen3-VL через LM Studio |
| Vision (online) | Qwen-VL-Plus via OpenRouter |
| LLM (offline) | LM Studio (любая совместимая модель) |
| LLM (online) | OpenRouter (Claude, GPT и др.) |
| Obsidian | Local REST API плагин |
| Настройки | pydantic-settings |

---

## Часто задаваемые вопросы

**Бот не отвечает на сообщения в реальном времени — это нормально?**
Да. FamilyLog не работает в режиме реального времени. Бот принимает сообщения, Telegram хранит их в очереди. Когда вы запускаете `run.py` — всё накопленное обрабатывается разом.

**Можно ли использовать без LM Studio?**
Да — установите `CONNECTION_TYPE=online` в `.env` и укажите `OPENROUTER_API_KEY`. Тогда все модели будут облачными.

**Что если сессия не закрылась?**
Сессии закрываются автоматически если последнее сообщение было более `SESSION_TIMEOUT_MINUTES` минут назад (по умолчанию 30). Это значение можно изменить в `.env`.

**Как добавить нового члена семьи?**
Добавьте его Telegram ID в `FAMILY_CHAT_IDS` в `.env` и опишите в `_system/FAMILY_MEMORY.md` в vault.

---

## Автор

Степан — [@StefanDKO](https://t.me/StefanDKO)

---

## Дополнительно

- [VULNERABILITIES.md](VULNERABILITIES.md) — аудит безопасности и открытые задачи