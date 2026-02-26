"""
Скрипт для загрузки STT моделей перед первым запуском.
Запуск: uv run download_models.py
"""
import onnx_asr
from src.config import settings

MODELS = {
    "gigaam-v3-e2e-rnnt": "stt_models/gigaam-v3-e2e-rnnt/",       # GigaAM v3 (рекомендуется, ~892MB)
    "gigaam-v3-e2e-ctc":  "stt_models/gigaam-v3-e2e-ctc/",        # GigaAM v3 CTC (~225MB, int8)
    # "nemo-conformer-tdt": "stt_models/parakeet-tdt-0.6b-v3-int8/", # Parakeet (английский/мультиязычный)
}

def download(model_name: str, path: str):
    print(f"\n⬇️  Загружаем {model_name} → {path}")
    onnx_asr.load_model(model_name, path)
    print(f"✅ {model_name} готов")

if __name__ == "__main__":
    # Загружаем только текущую модель из конфига
    download(settings.STT_MODEL_OFFLINE, settings.STT_MODEL_PATH)