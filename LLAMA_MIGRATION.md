# Миграция FamilyLog с LM Studio на llama.cpp (llama-server)

## Зачем?

Бенчмарки показали прирост скорости **~25%**: llama-server выдает ~55 t/s против ~42 t/s у LM Studio на тех же моделях и железе. При ежедневной обработке голосовых, фото и текстовых заметок это существенная экономия времени.

---

## 1. Сравнение llama-server и LM Studio

| Параметр | llama-server | LM Studio |
|---|---|---|
| **Скорость генерации** | ~55 t/s | ~42 t/s |
| **API** | OpenAI-совместимый (`/v1/chat/completions`) | OpenAI-совместимый (`/v1/chat/completions`) |
| **Динамическая загрузка моделей** | Нет — нужен перезапуск процесса | Да — `POST /api/v1/models/load`, `/unload` |
| **Мультимодель** | Один процесс = одна модель | Несколько моделей одновременно |
| **VRAM** | Чуть эффективнее (нет GUI оверхеда) | Небольшой оверхед GUI-обертки |
| **Настройка** | CLI-флаги, полный контроль | GUI, удобно для начала |
| **Vision (mmproj)** | `--mmproj` флаг | Автоматически, если модель поддерживает |
| **Лицензия** | MIT (llama.cpp) | Проприетарная |
| **Headless-режим** | Нативно (CLI) | Требует запущенного приложения |

**Вывод**: llama-server быстрее и легче, но требует ручного управления процессами вместо удобного API LM Studio для загрузки/выгрузки моделей.

---

## 2. Архитектура: LlamaServerManager

Вместо HTTP-вызовов к API LM Studio (`model_manager.py`) нам нужен менеджер, который **запускает и останавливает процессы llama-server** как subprocess. Каждая модель — отдельный процесс на своем порту.

### Текущий model_manager.py (LM Studio)

Текущий код использует HTTP API LM Studio:

```python
# src/familylog/LLMs_calls/model_manager.py (ТЕКУЩИЙ)
LM_STUDIO_LOAD_URL   = f"{LM_STUDIO_BASE}/api/v1/models/load"
LM_STUDIO_UNLOAD_URL = f"{LM_STUDIO_BASE}/api/v1/models/unload"

async def load_model(model_id: str, wait_seconds: int = 60) -> None:
    async with httpx.AsyncClient(timeout=120) as client:
        await client.post(LM_STUDIO_LOAD_URL, json={"model": model_id})
    # ... polling get_loaded_models()

async def unload_model(model_id: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(LM_STUDIO_UNLOAD_URL, json={"instance_id": model_id})
```

### Новый LlamaServerManager

```python
# src/familylog/LLMs_calls/llama_server_manager.py

import asyncio
import logging
import os
import signal
import subprocess
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


class LlamaServerManager:
    """
    Менеджер процессов llama-server.

    Заменяет model_manager.py (LM Studio API) на прямое управление
    процессами llama-server. Каждая модель запускается как отдельный
    subprocess на указанном порту.
    """

    def __init__(self, llama_server_path: str):
        """
        Args:
            llama_server_path: Абсолютный путь к бинарнику llama-server.
                               Например: /usr/local/bin/llama-server
        """
        self._server_path = llama_server_path
        self._processes: dict[int, subprocess.Popen] = {}  # port -> process
        self._model_paths: dict[int, str] = {}              # port -> model_path
        self._log_files: dict[int, object] = {}             # port -> log file handle

        if not Path(llama_server_path).exists():
            raise FileNotFoundError(
                f"llama-server не найден: {llama_server_path}"
            )

    async def load_model(
        self,
        model_path: str,
        port: int = 8080,
        n_gpu_layers: int = -1,
        ctx_size: int = 8192,
        mmproj: str | None = None,
        n_threads: int | None = None,
        extra_args: list[str] | None = None,
    ) -> None:
        """
        Запускает llama-server с указанной моделью.

        Args:
            model_path:   Путь к GGUF-файлу модели.
            port:         Порт для API-сервера.
            n_gpu_layers: Количество слоев на GPU (-1 = все).
            ctx_size:     Размер контекста в токенах.
            mmproj:       Путь к файлу мультимодальной проекции (для vision-моделей).
            n_threads:    Количество потоков CPU (None = авто).
            extra_args:   Дополнительные аргументы командной строки.
        """
        # Если на этом порту уже есть процесс — сначала выгружаем
        if port in self._processes:
            logger.warning(
                "Порт %d уже занят моделью %s, выгружаем...",
                port, self._model_paths.get(port, "unknown"),
            )
            await self.unload_model(port)

        # Проверяем файл модели
        if not Path(model_path).exists():
            raise FileNotFoundError(f"Файл модели не найден: {model_path}")

        if mmproj and not Path(mmproj).exists():
            raise FileNotFoundError(f"Файл mmproj не найден: {mmproj}")

        # Собираем команду
        cmd = [
            self._server_path,
            "--model", model_path,
            "--port", str(port),
            "--n-gpu-layers", str(n_gpu_layers),
            "--ctx-size", str(ctx_size),
            "--host", "127.0.0.1",
        ]

        if mmproj:
            cmd.extend(["--mmproj", mmproj])

        if n_threads:
            cmd.extend(["--threads", str(n_threads)])

        if extra_args:
            cmd.extend(extra_args)

        logger.info("Запускаем llama-server: %s", " ".join(cmd))

        # Логи процесса в файл
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        log_file = open(log_dir / f"llama-server-{port}.log", "a")
        self._log_files[port] = log_file

        # Запускаем процесс
        try:
            process = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid,  # Отдельная группа процессов
            )
        except OSError as e:
            log_file.close()
            del self._log_files[port]
            raise RuntimeError(
                f"Не удалось запустить llama-server: {e}"
            ) from e

        self._processes[port] = process
        self._model_paths[port] = model_path

        # Ждем готовности
        try:
            await self.wait_ready(port, timeout=120)
        except TimeoutError:
            # Процесс запустился, но не ответил — убиваем
            logger.error(
                "llama-server на порту %d не стал ready, убиваем процесс", port
            )
            await self.unload_model(port)
            raise

        model_name = Path(model_path).stem
        logger.info("Модель %s готова на порту %d (PID %d)", model_name, port, process.pid)

    async def unload_model(self, port: int) -> None:
        """
        Останавливает llama-server на указанном порту.

        Последовательность: SIGTERM -> ожидание 10с -> SIGKILL если не завершился.
        """
        process = self._processes.get(port)
        if process is None:
            logger.warning("Нет процесса на порту %d, пропускаем unload", port)
            return

        model_name = Path(self._model_paths.get(port, "unknown")).stem
        pid = process.pid
        logger.info("Останавливаем модель %s на порту %d (PID %d)...", model_name, port, pid)

        # Шаг 1: SIGTERM (graceful shutdown)
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except ProcessLookupError:
            logger.info("Процесс PID %d уже завершен", pid)
            self._cleanup_port(port)
            return

        # Шаг 2: ждем завершения до 10 секунд
        for _ in range(100):  # 100 * 0.1s = 10s
            if process.poll() is not None:
                logger.info("Процесс PID %d завершился (код %d)", pid, process.returncode)
                self._cleanup_port(port)
                return
            await asyncio.sleep(0.1)

        # Шаг 3: SIGKILL если не завершился
        logger.warning("Процесс PID %d не завершился по SIGTERM, отправляем SIGKILL", pid)
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
            process.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass

        self._cleanup_port(port)
        logger.info("Модель %s выгружена с порта %d", model_name, port)

    async def switch_model(
        self,
        port: int,
        new_model_path: str,
        **kwargs,
    ) -> None:
        """
        Переключает модель на указанном порту: выгружает текущую, загружает новую.

        Args:
            port:           Порт для переключения.
            new_model_path: Путь к новой GGUF-модели.
            **kwargs:       Дополнительные параметры для load_model
                            (n_gpu_layers, ctx_size, mmproj и т.д.).
        """
        current_model = self._model_paths.get(port, "нет модели")
        new_name = Path(new_model_path).stem
        logger.info(
            "Переключаем порт %d: %s -> %s",
            port, Path(current_model).stem, new_name,
        )

        await self.unload_model(port)
        # Небольшая пауза для освобождения VRAM
        await asyncio.sleep(2)
        await self.load_model(new_model_path, port=port, **kwargs)

    async def wait_ready(self, port: int, timeout: int = 60) -> None:
        """
        Ожидает готовности llama-server, опрашивая GET /health.

        llama-server возвращает {"status": "ok"} когда модель загружена
        и готова к обработке запросов.

        Args:
            port:    Порт сервера.
            timeout: Максимальное время ожидания в секундах.

        Raises:
            TimeoutError: Если сервер не стал ready за timeout секунд.
            RuntimeError: Если процесс завершился до готовности.
        """
        url = f"http://127.0.0.1:{port}/health"
        logger.info("Ожидаем готовности llama-server на порту %d...", port)

        async with httpx.AsyncClient(timeout=5) as client:
            for elapsed in range(timeout):
                # Проверяем что процесс еще жив
                process = self._processes.get(port)
                if process and process.poll() is not None:
                    raise RuntimeError(
                        f"llama-server на порту {port} завершился с кодом "
                        f"{process.returncode} до достижения готовности. "
                        f"Проверьте logs/llama-server-{port}.log"
                    )

                try:
                    r = await client.get(url)
                    if r.status_code == 200:
                        data = r.json()
                        if data.get("status") == "ok":
                            logger.info(
                                "llama-server на порту %d готов (за %dс)", port, elapsed
                            )
                            return
                except (httpx.ConnectError, httpx.ReadTimeout):
                    pass  # Сервер еще стартует

                await asyncio.sleep(1)

        raise TimeoutError(
            f"llama-server на порту {port} не стал ready за {timeout} секунд. "
            f"Проверьте logs/llama-server-{port}.log"
        )

    def get_loaded_models(self) -> dict[int, str]:
        """
        Возвращает словарь {порт: путь_к_модели} для запущенных процессов.

        Проверяет что процессы действительно живы (poll()).
        """
        alive = {}
        dead_ports = []

        for port, process in self._processes.items():
            if process.poll() is None:  # None = процесс жив
                alive[port] = self._model_paths[port]
            else:
                dead_ports.append(port)

        # Чистим мертвые процессы
        for port in dead_ports:
            logger.warning(
                "Обнаружен мертвый процесс на порту %d, очищаем", port
            )
            self._cleanup_port(port)

        return alive

    async def shutdown(self) -> None:
        """Останавливает все запущенные серверы. Вызывать при завершении программы."""
        ports = list(self._processes.keys())
        if not ports:
            return

        logger.info("Останавливаем все llama-server процессы: %s", ports)
        for port in ports:
            await self.unload_model(port)

    def _cleanup_port(self, port: int) -> None:
        """Очищает внутреннее состояние для указанного порта."""
        self._processes.pop(port, None)
        self._model_paths.pop(port, None)
        log_file = self._log_files.pop(port, None)
        if log_file:
            log_file.close()
```

### Ключевые отличия от model_manager.py

| Аспект | model_manager.py (LM Studio) | LlamaServerManager |
|---|---|---|
| Загрузка модели | HTTP POST к API LM Studio | `subprocess.Popen` запускает процесс |
| Выгрузка модели | HTTP POST к API LM Studio | `SIGTERM` -> `SIGKILL` процесса |
| Проверка готовности | Polling `GET /api/v1/models` | Polling `GET /health` |
| Идентификатор | Имя модели (`qwen/qwen3-vl-8b`) | Порт + путь к GGUF файлу |
| Vision-модели | Автоматически | Требует явный `--mmproj` |

---

## 3. Конфигурация

### Новые переменные в .env

```env
# ── llama.cpp (вместо LM Studio) ────────────────────────────────
LLAMA_SERVER_PATH=/usr/local/bin/llama-server

# Vision-модель (qwen3-vl-8b)
VISION_MODEL_GGUF=/models/qwen3-vl-8b-Q4_K_M.gguf
VISION_MMPROJ=/models/qwen3-vl-8b-mmproj.gguf

# LLM-модель (qwen3.5-27b или GPT-OSS-20B)
LLM_MODEL_GGUF=/models/qwen3.5-27b-Q4_K_M.gguf

# Параметры запуска
LLAMA_GPU_LAYERS=-1
LLAMA_CTX_SIZE=8192
```

### Изменения в config.py

Добавить новые поля в класс `Settings`:

```python
class Settings(BaseSettings):
    # ... существующие поля ...

    # llama.cpp settings (для CONNECTION_TYPE="offline")
    LLAMA_SERVER_PATH: str = "/usr/local/bin/llama-server"
    VISION_MODEL_GGUF: str = ""
    VISION_MMPROJ: str = ""
    LLM_MODEL_GGUF: str = ""
    LLAMA_GPU_LAYERS: int = -1
    LLAMA_CTX_SIZE: int = 8192

    # Порты для llama-server
    LLAMA_VISION_PORT: int = 8081
    LLAMA_LLM_PORT: int = 8082
```

Свойство `llm_base_url` нужно будет обновить для выбора правильного порта:

```python
@property
def llm_base_url(self) -> str:
    if self.CONNECTION_TYPE == "offline":
        return f"http://127.0.0.1:{self.LLAMA_LLM_PORT}/v1"
    return self.OPENROUTER_URL

@property
def vision_base_url(self) -> str:
    if self.CONNECTION_TYPE == "offline":
        return f"http://127.0.0.1:{self.LLAMA_VISION_PORT}/v1"
    return self.OPENROUTER_URL
```

---

## 4. Два подхода к работе с моделями

### Подход A: один порт, переключение моделей

**Подходит для**: 16 GB VRAM (напр. RTX 4080, Mac M1 Pro 16GB)

```
[Vision: 5GB VRAM] --> выгрузка --> [LLM: 16GB VRAM]
     порт 8080              ~10с           порт 8080
```

Модели используют один и тот же порт. Перед переключением текущая модель выгружается, VRAM освобождается, новая загружается. Задержка при переключении 5-15 секунд.

**Логика в run.py**:

```python
manager = LlamaServerManager(settings.LLAMA_SERVER_PATH)
PORT = 8080

# Фаза vision
await manager.load_model(
    settings.VISION_MODEL_GGUF, port=PORT,
    mmproj=settings.VISION_MMPROJ,
)
# ... обработка фото ...

# Переключаемся на LLM
await manager.switch_model(
    PORT, settings.LLM_MODEL_GGUF,
)
# ... генерация заметок ...

# Завершение
await manager.unload_model(PORT)
```

### Подход B: два порта, параллельная работа

**Подходит для**: 24+ GB VRAM (напр. RTX 4090, Mac M2 Ultra 64GB)

```
[Vision: 5GB VRAM]  порт 8081  ─┐
                                 ├── обе модели в памяти одновременно
[LLM: 16GB VRAM]    порт 8082  ─┘
```

Обе модели загружены одновременно на разных портах. Нет задержки при переключении, но требуется значительно больше VRAM.

Потребление VRAM (примерно):
- Vision (qwen3-vl-8b Q4_K_M): ~5 GB
- LLM (qwen3.5-27b Q4_K_M): ~16 GB
- Итого: ~21 GB + накладные расходы

**Логика в run.py**:

```python
manager = LlamaServerManager(settings.LLAMA_SERVER_PATH)

# Запускаем обе модели
await manager.load_model(
    settings.VISION_MODEL_GGUF,
    port=settings.LLAMA_VISION_PORT,  # 8081
    mmproj=settings.VISION_MMPROJ,
)
await manager.load_model(
    settings.LLM_MODEL_GGUF,
    port=settings.LLAMA_LLM_PORT,  # 8082
)

# Обработка фото -> OpenAI client указывает на порт 8081
# Генерация заметок -> OpenAI client указывает на порт 8082

# Завершение
await manager.shutdown()
```

### Рекомендация

Для типичной конфигурации FamilyLog (одна задача за раз, пакетная обработка в `run.py`) **подход A** — оптимальный выбор. Переключение моделей занимает 5-15 секунд, что несущественно при пакетной обработке. Весь VRAM достается одной модели, что позволяет использовать больший контекст или модели с более высоким уровнем квантования.

---

## 5. Пошаговый план миграции

### Шаг 1. Установка llama.cpp

**Вариант A: сборка из исходников (рекомендуется для macOS с Metal)**

```bash
git clone https://github.com/ggml-org/llama.cpp.git
cd llama.cpp
cmake -B build -DGGML_METAL=ON   # macOS с Metal GPU
# cmake -B build -DGGML_CUDA=ON  # Linux с NVIDIA GPU
cmake --build build --config Release -j $(nproc)
```

Бинарник будет в `build/bin/llama-server`.

**Вариант B: предсобранный бинарник**

Скачать последний релиз с https://github.com/ggml-org/llama.cpp/releases и распаковать.

**Проверка**:

```bash
./llama-server --version
```

### Шаг 2. Скачивание GGUF-моделей

Скачать модели с Hugging Face. Рекомендуемая квантизация: Q4_K_M (баланс качества и скорости).

```bash
# Vision-модель
huggingface-cli download Qwen/Qwen3-VL-8B-GGUF \
    qwen3-vl-8b-Q4_K_M.gguf \
    qwen3-vl-8b-mmproj.gguf \
    --local-dir /models/

# LLM-модель
huggingface-cli download Qwen/Qwen3.5-27B-GGUF \
    qwen3.5-27b-Q4_K_M.gguf \
    --local-dir /models/
```

> **Примечание**: Точные имена репозиториев и файлов могут отличаться.
> Проверьте наличие нужных файлов на https://huggingface.co

### Шаг 3. Проверка моделей вручную

Перед интеграцией в код, проверить что каждая модель работает:

```bash
# Тест LLM
./llama-server \
    --model /models/qwen3.5-27b-Q4_K_M.gguf \
    --port 8080 \
    --n-gpu-layers -1 \
    --ctx-size 8192

# В другом терминале:
curl http://127.0.0.1:8080/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{
        "model": "local",
        "messages": [{"role": "user", "content": "Привет!"}],
        "max_tokens": 100
    }'
```

```bash
# Тест Vision
./llama-server \
    --model /models/qwen3-vl-8b-Q4_K_M.gguf \
    --mmproj /models/qwen3-vl-8b-mmproj.gguf \
    --port 8080 \
    --n-gpu-layers -1 \
    --ctx-size 4096
```

### Шаг 4. Создание llama_server_manager.py

Создать файл `src/familylog/LLMs_calls/llama_server_manager.py` с кодом `LlamaServerManager` из раздела 2.

### Шаг 5. Обновление config.py

Добавить в `Settings` новые поля (см. раздел 3).

### Шаг 6. Обновление .env

```env
# Добавить:
LLAMA_SERVER_PATH=/path/to/llama-server
VISION_MODEL_GGUF=/models/qwen3-vl-8b-Q4_K_M.gguf
VISION_MMPROJ=/models/qwen3-vl-8b-mmproj.gguf
LLM_MODEL_GGUF=/models/qwen3.5-27b-Q4_K_M.gguf
LLAMA_GPU_LAYERS=-1
LLAMA_CTX_SIZE=8192
```

### Шаг 7. Обновление run.py

Заменить импорты и логику управления моделями. Ниже пример для подхода A (один порт):

```python
# run.py — ключевые изменения

# Было:
from src.familylog.LLMs_calls.model_manager import (
    get_loaded_models, load_model, unload_model, switch_model
)

# Стало:
from src.familylog.LLMs_calls.llama_server_manager import LlamaServerManager


async def main():
    await init_db()

    # Инициализируем менеджер
    manager = LlamaServerManager(settings.LLAMA_SERVER_PATH)
    PORT = 8080

    async with AsyncSessionLocal() as session:

        # ── 1. Сбор сообщений ──
        collected = await collect_messages(session)

        # ── 2. STT ──
        voice_count = await process_voice_messages(session)

        # ── 3. Vision (фото) ──
        if settings.CONNECTION_TYPE == "offline":
            # Проверяем есть ли pending фото
            pending_photos = await session.execute(
                select(Message).where(
                    Message.message_type == "photo",
                    Message.status == "pending"
                )
            )
            has_photos = pending_photos.scalars().first() is not None

            if has_photos:
                await manager.load_model(
                    settings.VISION_MODEL_GGUF,
                    port=PORT,
                    mmproj=settings.VISION_MMPROJ,
                    n_gpu_layers=settings.LLAMA_GPU_LAYERS,
                    ctx_size=settings.LLAMA_CTX_SIZE,
                )

        photo_count = await process_photo_messages(session)

        # ── 4. Переключаемся на LLM ──
        if settings.CONNECTION_TYPE == "offline":
            loaded = manager.get_loaded_models()
            if PORT in loaded:
                # Vision была загружена — переключаем
                await manager.switch_model(
                    PORT,
                    settings.LLM_MODEL_GGUF,
                    n_gpu_layers=settings.LLAMA_GPU_LAYERS,
                    ctx_size=settings.LLAMA_CTX_SIZE,
                )
            else:
                await manager.load_model(
                    settings.LLM_MODEL_GGUF,
                    port=PORT,
                    n_gpu_layers=settings.LLAMA_GPU_LAYERS,
                    ctx_size=settings.LLAMA_CTX_SIZE,
                )

        # ── 5-7. Сборка и запись ──
        closed = await close_all_open_sessions(session)
        assembled = await assemble_sessions(session)
        obsidian_count = await process_assembled_sessions(session)

        # ── 8. Выгружаем модель ──
        if settings.CONNECTION_TYPE == "offline":
            await manager.shutdown()
```

### Шаг 8. Обновление клиентского кода

Код, который делает запросы к модели (через OpenAI-клиент), менять не нужно:
llama-server предоставляет тот же `/v1/chat/completions` эндпоинт, что и LM Studio.

Единственное отличие: если модель на llama-server запущена на порту, отличном от 1234, нужно обновить `llm_base_url` / `vision_base_url` в `config.py` (см. раздел 3).

> **Важно**: llama-server игнорирует поле `model` в запросе — он всегда использует модель, с которой был запущен. Это не влияет на работу, но стоит иметь в виду при отладке.

### Шаг 9. Тестирование полного пайплайна

```bash
# Запустить полный цикл обработки
uv run python run.py
```

Проверить:
- Vision-модель загружается и описывает фото
- Переключение на LLM проходит без ошибок
- Заметки генерируются корректно
- Модель выгружается при завершении
- Логи процессов в `logs/llama-server-*.log`

---

## 6. Откат на LM Studio

Если миграция на llama-server приводит к проблемам, откатиться на LM Studio можно за несколько минут:

1. **Вернуть model_manager.py**: если файл был переименован или удален — восстановить из git:

   ```bash
   git checkout main -- src/familylog/LLMs_calls/model_manager.py
   ```

2. **Вернуть импорты в run.py**:

   ```python
   # Раскомментировать/вернуть:
   from src.familylog.LLMs_calls.model_manager import (
       get_loaded_models, load_model, unload_model, switch_model
   )
   ```

3. **Убедиться что LM Studio запущена** и модели доступны на `localhost:1234`.

4. **Убрать переменные llama.cpp из .env** (необязательно, но чтобы не путаться).

> **Совет**: при миграции не удаляйте `model_manager.py`, а переименуйте его в `model_manager_lmstudio.py`. Так откат будет мгновенным без обращения к git.

---

## Известные ограничения llama-server

1. **Нет hot-reload моделей** — для смены модели нужен полный перезапуск процесса (5-15 секунд).
2. **Один процесс = одна модель** — для параллельной работы двух моделей нужны два процесса на разных портах.
3. **Поле `model` в запросах игнорируется** — сервер всегда использует модель, указанную при запуске.
4. **preexec_fn=os.setsid не работает на Windows** — если планируется кроссплатформенность, нужно использовать `creationflags=subprocess.CREATE_NEW_PROCESS_GROUP` на Windows.
