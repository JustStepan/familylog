from functools import lru_cache
from openai import OpenAI
from src.config import settings

@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    """Синглтон OpenAI клиента. lru_cache гарантирует один экземпляр."""
    return OpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
    )
