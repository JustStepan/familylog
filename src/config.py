from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent


class Settings(BaseSettings):
    # Инфраструктура
    BOT_TOKEN: str
    DATABASE_URL: str = "sqlite+aiosqlite:///familylog.db"
    CONTEXT_MEMORY_DAYS: int = 30
    SESSION_TIMEOUT_MINUTES: int = 30
    SUMMARY_INTERVAL_DAYS: int = 7

    # Telegram
    FAMILY_CHAT_IDS: list[int] = []

    # Obsidian
    OBSIDIAN_VAULT_PATH: str
    OBSIDIAN_API_KEY: str
    OBSIDIAN_API_URL: str = "http://localhost:27123"

    # Режим подключения: offline (LM Studio) | online (OpenRouter)
    CONNECTION_TYPE: str = "offline"

    # ---------------------------------------------------------------------------
    # STT (Speech-to-Text)
    # ---------------------------------------------------------------------------
    # Рекомендуемые модели для русского языка (по убыванию качества):
    #   "gigaam-v3-e2e-rnnt" — лучшее качество, пунктуация из коробки (~892MB)
    #   "gigaam-v3-e2e-ctc"  — быстрее и легче (~225MB), качество чуть ниже
    #   "nemo-conformer-tdt" — Parakeet, мультиязычный (quantization="int8")
    #
    # STT_MODEL_PATH должен совпадать с папкой куда скачана модель (download_models.py)
    STT_MODEL_OFFLINE: str = "gigaam-v3-e2e-rnnt"
    STT_MODEL_PATH: str = f"{BASE_DIR}/stt_models/gigaam-v3-e2e-rnnt/"

    # Vision
    VISION_MODEL_OFFLINE: str = "qwen3.5-4b-mlx"

    # LLM
    LLM_MODEL_OFFLINE: str = "qwen3.5-4b-mlx" # qwen_qwen3.5-35b-a3b | openai/gpt-oss-20b qwen3.5-9b-mlx

    # LM Studio endpoints
    LM_STUDIO_URL: str = "http://localhost:1234/v1"
    LM_STUDIO_BASE_URL: str = "http://localhost:1234"

    # Google Calendar
    GOOGLE_CALENDAR_ID: str = "primary"
    GOOGLE_CREDENTIALS_FILE: str = "calendar_credentials.json"
    GOOGLE_TOKEN_FILE: str = "calendar_token.json"

    # Далее блок для online режима, просто добавить условие if self.CONNECTION_TYPE == "offline"
    @property
    def stt_model(self) -> str:
        return self.STT_MODEL_OFFLINE

    @property
    def vision_model(self) -> str:
        return self.VISION_MODEL_OFFLINE

    @property
    def llm_model(self) -> str:
        return self.LLM_MODEL_OFFLINE

    @property
    def llm_base_url(self) -> str:
        return self.LM_STUDIO_URL

    @property
    def llm_api_key(self) -> str:
        return "lm-studio"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()  # type ignore