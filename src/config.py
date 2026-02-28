from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent


class Settings(BaseSettings):
    # Инфраструктура
    BOT_TOKEN: str
    DATABASE_URL: str = "sqlite+aiosqlite:///familylog.db"
    CONTEXT_MEMORY_DAYS: int = 90
    SESSION_TIMEOUT_MINUTES: int = 30

    # Telegram — chat_id всех членов семьи
    FAMILY_CHAT_IDS: list[int] = [987692540, 6293359903]

    # Obsidian
    OBSIDIAN_VAULT_PATH: str
    OBSIDIAN_API_KEY: str
    OBSIDIAN_API_URL: str = "http://localhost:27123"

    # Режим подключения: offline (LM Studio) | online (OpenRouter)
    CONNECTION_TYPE: str = "offline"

    # ---------------------------------------------------------------------------
    # STT (Speech-to-Text)
    # ---------------------------------------------------------------------------
    # Доступные offline модели:
    #   "gigaam-v3-e2e-rnnt"  — лучшее качество RU, пунктуация из коробки (~892MB)
    #   "gigaam-v3-e2e-ctc"   — чуть хуже, но быстрее и легче (~225MB, int8)
    #   "nemo-conformer-tdt"  — Parakeet, мультиязычный (нужен quantization="int8")
    #
    # STT_MODEL_PATH — папка куда скачивается модель (uv run download_models.py)
    # Должна совпадать с именем модели для наглядности.
    STT_MODEL_OFFLINE: str = "gigaam-v3-e2e-rnnt"
    STT_MODEL_PATH: str = f"{BASE_DIR}/stt_models/gigaam-v3-e2e-rnnt/"

    # Онлайн STT — мультимодальный LLM через OpenRouter
    # Используется когда CONNECTION_TYPE="online"
    STT_MODEL_ONLINE: str = "google/gemini-2.5-flash"

    # Vision
    VISION_MODEL_OFFLINE: str = "qwen/qwen3-vl-8b"
    VISION_MODEL_ONLINE: str = "qwen/qwen-vl-plus"

    # LLM
    LLM_MODEL_OFFLINE: str = "openai/gpt-oss-20b"
    LLM_MODEL_ONLINE: str = "anthropic/claude-3-haiku"

    # API endpoints
    LM_STUDIO_URL: str = "http://localhost:1234/v1"
    LM_STUDIO_BASE_URL: str = "http://localhost:1234"    # для model_manager
    OPENROUTER_API_KEY: str = "FAKE"
    OPENROUTER_URL: str = "https://openrouter.ai/api/v1"

    @property
    def stt_model(self) -> str:
        return self.STT_MODEL_OFFLINE if self.CONNECTION_TYPE == "offline" else self.STT_MODEL_ONLINE

    @property
    def vision_model(self) -> str:
        return self.VISION_MODEL_OFFLINE if self.CONNECTION_TYPE == "offline" else self.VISION_MODEL_ONLINE

    @property
    def llm_model(self) -> str:
        return self.LLM_MODEL_OFFLINE if self.CONNECTION_TYPE == "offline" else self.LLM_MODEL_ONLINE

    @property
    def llm_base_url(self) -> str:
        return self.LM_STUDIO_URL if self.CONNECTION_TYPE == "offline" else self.OPENROUTER_URL

    @property
    def llm_api_key(self) -> str:
        return "lm-studio" if self.CONNECTION_TYPE == "offline" else self.OPENROUTER_API_KEY

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()