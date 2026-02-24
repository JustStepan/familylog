import onnx_asr
from src.config import settings

model = onnx_asr.load_model("nemo-conformer-tdt", settings.MODEL_PATH, quantization="int8")
result = model.recognize("test_audio.wav")
print(result)