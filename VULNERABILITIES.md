# Аудит безопасности и качества кода — FamilyLog

Дата аудита: 2026-02-28
Версия: на момент коммита `14469d3`

---

## 1. Критические уязвимости

### 1.1 Реальные API-ключи в `.env`

**Файл:** `.env` (корень проекта)
**Что:** Файл содержит реальные значения `BOT_TOKEN`, `OBSIDIAN_API_KEY`, `OPENROUTER_API_KEY`. Хотя `.gitignore` включает `.env`, если файл был закоммичен хотя бы раз — ключи уже в истории Git и считаются скомпрометированными.

**Риск:** Утечка токенов Telegram бота и API-ключей при публикации репозитория или передаче `.git` директории.

**Как исправить:**
1. Немедленно ротировать все ключи:
   - `BOT_TOKEN` — через [@BotFather](https://t.me/BotFather) → `/revoke`
   - `OBSIDIAN_API_KEY` — пересоздать в настройках плагина Obsidian Local REST API
   - `OPENROUTER_API_KEY` — пересоздать в личном кабинете OpenRouter
2. Вычистить из истории Git (если файл когда-либо попадал в коммит):
   ```bash
   git filter-branch --force --index-filter \
     'git rm --cached --ignore-unmatch .env' \
     --prune-empty --tag-name-filter cat -- --all
   ```
   Или использовать `git-filter-repo` (предпочтительнее):
   ```bash
   pip install git-filter-repo
   git filter-repo --invert-paths --path .env
   ```
3. Добавить `.env.example` с плейсхолдерами для документации:
   ```
   BOT_TOKEN=your_telegram_bot_token
   OBSIDIAN_API_KEY=your_obsidian_api_key
   OPENROUTER_API_KEY=your_openrouter_key
   ```

---

### 1.2 Отключена проверка SSL-сертификатов (`verify=False`)

**Файл:** `src/familylog/processor/obsidian_writer.py`
**Строки:** 22, 35, 58, 92, 108

Все вызовы `httpx.AsyncClient(verify=False)` в функциях:
- `obsidian_get()` — строка 22
- `obsidian_create()` — строка 35
- `obsidian_upload_image()` — строка 58
- `obsidian_upload_document()` — строка 92
- `obsidian_list_files()` — строка 108

**Риск:** Отключение TLS-верификации делает соединение уязвимым для MITM-атак. Для localhost (текущий `OBSIDIAN_API_URL = "http://localhost:27123"`) это не критично — трафик и так не шифруется (HTTP, не HTTPS). Но если кто-то поменяет URL на удалённый сервер — передача API-ключа пойдёт без защиты.

**Как исправить:**
Добавить настройку в `config.py` и использовать её:

```python
# src/config.py
class Settings(BaseSettings):
    ...
    OBSIDIAN_SSL_VERIFY: bool = False  # True для production с удалённым Obsidian
```

```python
# src/familylog/processor/obsidian_writer.py
async def obsidian_get(path: str) -> str | None:
    async with httpx.AsyncClient(verify=settings.OBSIDIAN_SSL_VERIFY) as client:
        ...
```

Альтернативно — вынести создание клиента в отдельную функцию (см. пункт 2.7 про connection pooling).

---

## 2. Проблемы среднего уровня

### 2.1 Широкий перехват исключений (`except Exception`)

Встречается в 10+ местах. Конкретные примеры:

| Файл | Строка | Контекст |
|------|--------|----------|
| `obsidian_writer.py` | 502 | `inject_tags_to_frontmatter` — молча возвращает неизменённый контент |
| `obsidian_writer.py` | 545-546 | `find_related_by_tags` — пропускает файл без логирования |
| `obsidian_writer.py` | 590-591 | `inject_related_to_frontmatter` — молча глотает ошибку |
| `obsidian_writer.py` | 624-625 | `add_backlinks` — пропускает файл |
| `obsidian_writer.py` | 746-747 | добавление `created` в frontmatter — `pass` |
| `obsidian_writer.py` | 816-817 | вставка `related` — `pass` |
| `obsidian_writer.py` | 826-827 | блок related — логирует, но не типизированно |
| `obsidian_writer.py` | 869-872 | главный цикл — ставит `error_obsidian`, но без деталей |
| `stt.py` | 114-117 | транскрипция — ставит `error_stt` |
| `vision.py` | 78-81 | обработка фото — ставит `error_img` |
| `documents.py` | 58-61 | обработка документов — ставит `error_doc` |

**Риск:** Молчаливые ошибки усложняют отладку. Ошибка парсинга YAML frontmatter (строка 502) проглатывается — пользователь не узнает, что теги не были вставлены.

**Как исправить:**
```python
# Вместо:
except Exception:
    continue

# Использовать:
except (yaml.YAMLError, KeyError) as e:
    logger.warning("Не удалось прочитать frontmatter %s: %s", filepath, e)
    continue
```

Для основных циклов обработки (`stt.py:114`, `vision.py:78`, `documents.py:58`) широкий `except Exception` допустим — но нужно логировать полный traceback:
```python
except Exception:
    logger.exception("Ошибка обработки сообщения %d", msg.id)
    msg.status = "error_stt"
    await session.commit()
```

---

### 2.2 Отсутствие валидации входных данных

**a) `resolve_author()` — наивный поиск по строке**

Файл: `src/familylog/processor/obsidian_writer.py`, строка 200-209

```python
def resolve_author(author_id: int, family_memory: str) -> str:
    blocks = family_memory.split("### ")
    for block in blocks:
        if str(author_id) in block:  # <-- substring match
            ...
```

Если `author_id = 123`, сматчится и блок с ID `1234567`. Например, при `author_id = 6293` сматчится любой блок, содержащий число `6293` в любом контексте.

**Как исправить:**
```python
import re

def resolve_author(author_id: int, family_memory: str) -> str:
    pattern = rf'\b{author_id}\b'
    blocks = family_memory.split("### ")
    for block in blocks:
        if re.search(pattern, block):
            name = block.split("\n")[0].strip()
            if name:
                return name
    return f"user_{author_id}"
```

**b) JSON-ответ Telegram без try-except**

Файл: `src/familylog/storage/telegram_files.py`, строка 20

```python
telegram_path = r.json()["result"]["file_path"]
```

Если Telegram вернёт ошибку (например, `{"ok": false, "error_code": 400}`), упадёт с `KeyError` без понятного сообщения.

**Как исправить:**
```python
data = r.json()
if not data.get("ok"):
    raise RuntimeError(f"Telegram API error: {data.get('description', 'unknown')}")
telegram_path = data["result"]["file_path"]
```

**c) JSON-ответ LM Studio без валидации**

Файл: `src/familylog/LLMs_calls/model_manager.py`, строка 20

```python
data = r.json()
loaded = []
for m in data.get("models", []):
```

Если LM Studio вернёт невалидный JSON или неожиданную структуру, ошибка будет непонятной.

---

### 2.3 Глобальное состояние без потокобезопасности

**a) `client.py` — глобальный `_connection`**

Файл: `src/familylog/LLMs_calls/client.py`, строки 5-15

```python
_connection = None

def get_client():
    global _connection
    if _connection is None:
        _connection = OpenAI(...)
    return _connection
```

**b) `stt.py` — глобальная `_model`**

Файл: `src/familylog/processor/stt.py`, строки 20-35

```python
_model = None

def get_model():
    global _model
    if _model is None:
        _model = onnx_asr.load_model(...)
    return _model
```

**Риск:** Классическая гонка (race condition) при конкурентных вызовах — два корутины могут одновременно увидеть `None` и создать два экземпляра. Для `_model` это расходует память (модель ~900MB), для `_connection` — менее критично, но некорректно.

**Как исправить:**
```python
import asyncio

_lock = asyncio.Lock()
_connection = None

async def get_client():
    global _connection
    async with _lock:
        if _connection is None:
            _connection = OpenAI(...)
    return _connection
```

Для STT-модели (синхронная загрузка) — использовать `threading.Lock`, т.к. `onnx_asr.load_model()` блокирующий.

---

### 2.4 Логирование: print() вместо logging

**Статус: ИСПРАВЛЕНО** в текущем PR (миграция на `logging`).

Остаток: `src/familylog/storage/telegram_files.py`, строка 27:
```python
print(r)  # <-- забытый print
```

**Как исправить:** Заменить на `logger.debug("Telegram file response: %s", r.status_code)` или удалить.

---

### 2.5 Захардкоженные константы в `obsidian_writer.py`

**Статус:** `FAMILY_CHAT_IDS` перенесён в `config.py` — **исправлено**.

Оставшиеся хардкоды в `obsidian_writer.py`:

| Константа | Строка | Описание |
|-----------|--------|----------|
| `MIME_MAP` | 72-84 | Маппинг расширений на MIME-типы |
| `RUSSIAN_MONTHS` | 214-217 | Русские сокращения месяцев |
| `INTENT_FOLDERS` | 219-224 | Маппинг intent → папка в vault |

**Как исправить:**
- `MIME_MAP` — вынести в отдельный модуль `utils/mime.py` или использовать стандартный `mimetypes.guess_type()`
- `RUSSIAN_MONTHS` — вынести в `utils/dates.py`
- `INTENT_FOLDERS` — перенести в `config.py` как настройку (пользователь может захотеть другую структуру папок)

---

## 3. Предложения по улучшению

### 3.1 Декомпозиция `obsidian_writer.py` (906 строк)

Файл: `src/familylog/processor/obsidian_writer.py` — 906 строк, выполняет 5+ функций.

**Предлагаемая структура:**

```
src/familylog/processor/
    obsidian/
        __init__.py          # re-export process_assembled_sessions
        api.py               # obsidian_get, obsidian_create, obsidian_append,
                             # obsidian_upload_image, obsidian_upload_document,
                             # obsidian_list_files (~90 строк)
        context.py           # load_system_file, parse_current_context,
                             # load_base_context, load_context (~70 строк)
        metadata.py          # inject_tags_to_frontmatter, inject_related_to_frontmatter,
                             # fix_document_references, strip_frontmatter,
                             # fix_obsidian_embeds, extract_json (~120 строк)
        relationships.py     # find_related_by_tags, validate_related_files,
                             # add_backlinks, _to_wikilink, _from_wikilink (~100 строк)
        memory.py            # update_current_context, update_tags_glossary,
                             # update_family_memory, update_user_interests (~130 строк)
        filenames.py         # generate_filename, resolve_author,
                             # generate_person_tag, RUSSIAN_MONTHS,
                             # INTENT_FOLDERS (~80 строк)
        writer.py            # process_assembled_sessions — главная функция (~200 строк)
```

---

### 3.2 Отсутствие connection pooling для HTTP

Каждый вызов `obsidian_get`, `obsidian_create` и т.д. создаёт новый `httpx.AsyncClient`. При обработке одной сессии это 10-30+ HTTP-запросов, каждый с новым TCP-соединением.

**Как исправить:**
```python
# src/familylog/processor/obsidian/api.py

_client: httpx.AsyncClient | None = None

def get_obsidian_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=settings.OBSIDIAN_API_URL,
            headers={"Authorization": f"Bearer {settings.OBSIDIAN_API_KEY}"},
            verify=settings.OBSIDIAN_SSL_VERIFY,
            timeout=30,
        )
    return _client

async def obsidian_get(path: str) -> str | None:
    client = get_obsidian_client()
    r = await client.get(f"/vault/{path}")
    ...
```

Либо использовать паттерн lifespan (инициализация при старте, закрытие при остановке).

---

### 3.3 N+1 проблема в `find_related_by_tags()`

Файл: `src/familylog/processor/obsidian_writer.py`, строки 506-552

Текущая логика: для каждой из 4 папок получает список файлов, затем **по одному** читает каждый файл:

```python
for filepath in files:       # может быть 100+ файлов
    file_content = await obsidian_get(filepath)  # отдельный HTTP-запрос
```

При 100 файлах в vault — это 100+ последовательных HTTP-запросов.

**Как исправить:**
```python
import asyncio

async def find_related_by_tags(tags, current_filename, intent):
    ...
    all_files = []
    for folder in ("notes", "diary", "calendar", "tasks"):
        files = await obsidian_list_files(folder)
        all_files.extend(f for f in files if f != current_filename)

    # Параллельное чтение батчами по 10
    async def check_file(filepath):
        content = await obsidian_get(filepath)
        if not content:
            return None
        try:
            post = fm.loads(content)
            file_tags = set(_normalize_tag(t) for t in (post.get("tags") or []) if t)
            overlap = len(tags_set & file_tags)
            return (filepath, overlap) if overlap > 0 else None
        except Exception:
            return None

    BATCH_SIZE = 10
    candidates = []
    for i in range(0, len(all_files), BATCH_SIZE):
        batch = all_files[i:i + BATCH_SIZE]
        results = await asyncio.gather(*(check_file(f) for f in batch))
        candidates.extend(r for r in results if r)

    candidates.sort(key=lambda x: x[1], reverse=True)
    return [c[0] for c in candidates[:5]]
```

---

### 3.4 Отсутствие retry-логики для сетевых вызовов

Нет ни одного retry при обращении к:
- Obsidian REST API (может быть перезапущен)
- Telegram API (сеть, rate limits)
- LM Studio / OpenRouter (модель загружается, таймаут)

**Как исправить:**
Использовать `tenacity`:
```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(httpx.TransportError),
)
async def obsidian_get(path: str) -> str | None:
    ...
```

Или встроить retry в общий HTTP-клиент через `httpx`-транспорт.

---

### 3.5 Отсутствие миграций БД

Файл: `src/familylog/storage/database.py`, строка 17-20

```python
async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

`create_all` не изменяет существующие таблицы — только создаёт отсутствующие. При добавлении нового столбца в модель (например, `Message.document_mime_type`) существующая БД не обновится.

**Как исправить:**
Подключить `alembic`:
```bash
pip install alembic
alembic init alembic
# Настроить alembic.ini и env.py для async SQLAlchemy
alembic revision --autogenerate -m "initial"
alembic upgrade head
```

---

### 3.6 Отсутствие индексов на часто запрашиваемых полях

Файл: `src/familylog/storage/models.py`

Текущие запросы фильтруют по:
- `Session.status` (строка 676 в obsidian_writer.py)
- `Message.status` + `Message.message_type` (stt.py:78-82, vision.py:38-42, documents.py:21-26)
- `Message.session_id` (obsidian_writer.py:750-755)

Ни на одном из этих полей нет индекса.

**Как исправить:**
```python
from sqlalchemy import Index

class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_status", "status"),
    )
    ...

class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_status_type", "status", "message_type"),
        Index("ix_messages_session_id", "session_id"),
    )
    ...
```

При текущих объёмах (семейный чат) это не критично, но станет важно при росте.

---

### 3.7 Отсутствие тестов

В проекте нет ни одного unit-теста. Наиболее важные кандидаты для покрытия:

| Приоритет | Функция | Почему |
|-----------|---------|--------|
| Высокий | `extract_json()` | Парсинг непредсказуемых ответов LLM (think-теги, code fences) |
| Высокий | `generate_filename()` | Логика с 4 ветками (note/diary/calendar/task) |
| Высокий | `inject_tags_to_frontmatter()` | Мутирует YAML — легко сломать |
| Высокий | `resolve_author()` | Substring matching — хрупкая логика |
| Средний | `fix_obsidian_embeds()` | Regex-замены — легко получить регресс |
| Средний | `parse_current_context()` | Парсинг дат и секций |

**Как начать:**
```bash
pip install pytest pytest-asyncio
mkdir tests
```

```python
# tests/test_obsidian_writer.py
from src.familylog.processor.obsidian_writer import extract_json, generate_filename

def test_extract_json_with_think_tags():
    raw = '<think>reasoning here</think>{"title": "test"}'
    assert extract_json(raw) == '{"title": "test"}'

def test_extract_json_with_code_fences():
    raw = '```json\n{"title": "test"}\n```'
    assert extract_json(raw) == '{"title": "test"}'

def test_generate_filename_note():
    from datetime import datetime
    dt = datetime(2026, 2, 27, 14, 30)
    result = generate_filename("Моя заметка", "note", dt)
    assert result == "notes/Moia_zametka_27-фев-26.md"
```

---

### 3.8 Отсутствие dependency injection

Модули напрямую импортируют друг друга и глобальный `settings`:

- `obsidian_writer.py` импортирует `llm_process_session` напрямую
- `vision.py` импортирует `llm_process_photo` напрямую
- `stt.py` обращается к `settings.STT_MODEL_OFFLINE` напрямую

Это делает невозможным:
- Подмену LLM в тестах (mock)
- Замену STT-движка без правки кода
- Параллельный запуск с разными конфигурациями

**Как исправить (минимально):**
Передавать зависимости как параметры функций:
```python
async def process_assembled_sessions(
    session: AsyncSession,
    llm_fn=llm_process_session,       # можно подменить в тестах
    obsidian_client=None,              # можно передать mock
) -> int:
    ...
```

**Как исправить (полноценно):**
Использовать DI-контейнер (`dependency-injector`, `dishka`), но для проекта такого размера это может быть overkill.

---

### 3.9 Отсутствие абстракции LLM-провайдера

Файл: `src/config.py`, строки 56-74

Переключение между LM Studio (offline) и OpenRouter (online) реализовано через `@property` в Settings:

```python
@property
def llm_base_url(self) -> str:
    return self.LM_STUDIO_URL if self.CONNECTION_TYPE == "offline" else self.OPENROUTER_URL
```

При добавлении третьего провайдера (Ollama, vLLM, Groq) придётся добавлять ветки в каждый property.

**Как исправить:**
```python
# src/familylog/LLMs_calls/providers.py
from abc import ABC, abstractmethod

class LLMProvider(ABC):
    @abstractmethod
    def get_base_url(self) -> str: ...

    @abstractmethod
    def get_api_key(self) -> str: ...

    @abstractmethod
    def get_model(self, task: str) -> str: ...

class LMStudioProvider(LLMProvider):
    def get_base_url(self) -> str:
        return settings.LM_STUDIO_URL

    def get_api_key(self) -> str:
        return "lm-studio"

    def get_model(self, task: str) -> str:
        models = {"llm": settings.LLM_MODEL_OFFLINE, "stt": settings.STT_MODEL_OFFLINE, ...}
        return models[task]

class OpenRouterProvider(LLMProvider):
    ...

def get_provider() -> LLMProvider:
    providers = {"offline": LMStudioProvider, "online": OpenRouterProvider}
    return providers[settings.CONNECTION_TYPE]()
```

---

## Сводная таблица

| # | Уровень | Проблема | Статус |
|---|---------|----------|--------|
| 1.1 | Критический | API-ключи в `.env` / истории Git | Требует ротации ключей |
| 1.2 | Критический | `verify=False` в httpx | Требует параметризации |
| 2.1 | Средний | `except Exception` в 10+ местах | Открыто |
| 2.2 | Средний | Нет валидации входных данных | Открыто |
| 2.3 | Средний | Глобальное состояние без блокировок | Открыто |
| 2.4 | Средний | `print()` вместо `logging` | Исправлено (остался 1 print) |
| 2.5 | Средний | Хардкод констант | Частично исправлено |
| 3.1 | Улучшение | Декомпозиция obsidian_writer.py | Открыто |
| 3.2 | Улучшение | Connection pooling | Открыто |
| 3.3 | Улучшение | N+1 в find_related_by_tags | Открыто |
| 3.4 | Улучшение | Retry-логика | Открыто |
| 3.5 | Улучшение | Миграции БД | Открыто |
| 3.6 | Улучшение | Индексы БД | Открыто |
| 3.7 | Улучшение | Unit-тесты | Открыто |
| 3.8 | Улучшение | Dependency injection | Открыто |
| 3.9 | Улучшение | Абстракция LLM-провайдера | Открыто |
