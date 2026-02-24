from faster_whisper import WhisperModel

model = WhisperModel("medium", device="cpu", compute_type="int8")
segments, info = model.transcribe("test_audio.wav", language="ru")
print("".join(segment.text for segment in segments))