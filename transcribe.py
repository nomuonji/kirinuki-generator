
import whisper

model = whisper.load_model("base")
result = model.transcribe("tmp/video.mp4.webm", language="Japanese", fp16=False)

import json
with open("tmp/transcript.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print("Transcription completed successfully!")
