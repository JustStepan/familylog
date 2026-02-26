from openai import OpenAI
from src.config import settings


_conection = None


def get_client():
    global _connection
    if _connection is None:
        _connection = OpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
        )
    return _connection
