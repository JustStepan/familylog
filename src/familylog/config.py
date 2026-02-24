from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    BOT_TOKEN: str
    OBSIDIAN_VAULT_PATH: str
    DATABASE_URL: str = "sqlite+aiosqlite:///familylog.db"
    LM_STUDIO_URL: str = "http://localhost:1234/v1"
    OBSIDIAN_API_KEY: str
    OBSIDIAN_API_URL: str = "http://localhost:27123"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()