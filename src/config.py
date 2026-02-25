from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

class Settings(BaseSettings):
    BOT_TOKEN: str
    OBSIDIAN_VAULT_PATH: str
    DATABASE_URL: str = "sqlite+aiosqlite:///familylog.db"
    LM_STUDIO_URL: str = "http://localhost:1234/v1"
    OBSIDIAN_API_KEY: str
    OBSIDIAN_API_URL: str = "http://localhost:27123"
    OPENROUTER_API_KEY: str = 'FAKE'
    MODEL_PATH: str = f'{BASE_DIR}/model/parakeet-tdt-0.6b-v3-int8/'
    CONNECNTION_TYPE: str = 'offline'

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()


# СДЕЛАТЬ
# class Settings(BaseSettings):
#     CONNECNTION_TYPE: str = 'offline'
    
#     # Локальные модели (LM Studio)
#     VISION_MODEL_LOCAL: str = "qwen/qwen3-vl-8b"
#     STT_MODEL_LOCAL: str = "parakeet-tdt"
#     LLM_MODEL_LOCAL: str = "google/gemma-3-12b"
    
#     # Онлайн модели (OpenRouter)
#     VISION_MODEL_ONLINE: str = "qwen/qwen-vl-plus"
#     LLM_MODEL_ONLINE: str = "anthropic/claude-3-haiku"

#     @property
#     def vision_model(self) -> str:
#         return self.VISION_MODEL_LOCAL if self.CONNECNTION_TYPE == 'offline' else self.VISION_MODEL_ONLINE

#     @property
#     def llm_model(self) -> str:
#         return self.LLM_MODEL_LOCAL if self.CONNECNTION_TYPE == 'offline' else self.LLM_MODEL_ONLINE