import mlx.core as mx
from parakeet_mlx import from_pretrained

model = from_pretrained(
    "mlx-community/parakeet-tdt-0.6b-v3",
    dtype=mx.bfloat16
)
result = model.transcribe("test_audio.wav")
print(result.text)