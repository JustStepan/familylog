from openai import OpenAI
from src.config import settings


_conection = None


def get_client():
    global _conection
    if _conection is None:
        if settings.CONNECNTION_TYPE == 'offline':
            _conection = OpenAI(base_url="http://localhost:1234/v1", api_key="dummy-key")
        else:
            _conection = OpenAI(api_key=settings.OPENROUTER_API_KEY, base_url="...")
    return _conection
