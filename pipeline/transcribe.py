"""
Bước 3: Trích audio từ video và phiên âm có timestamp bằng Groq Whisper API.
Groq trả về timestamp theo từng segment (câu/cụm) — đủ để dùng làm mốc neo
cho bước ghép sau này. Nếu sau này cần timestamp CHÍNH XÁC TỪNG TỪ, có thể
thêm WhisperX align chạy trên GPU (Modal T4) như bước mở rộng.
"""
import sys
import json
import subprocess
from pathlib import Path

from groq import Groq

sys.path.append(str(Path(__file__).parent.parent))
from config import WORK_DIR, GROQ_API_KEY, GROQ_ASR_MODEL


def extract_audio(video_path: Path) -> Path:
    audio_path = WORK_DIR / "source_audio.wav"
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000",
        str(audio_path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return audio_path


def transcribe(video_path: Path) -> list[dict]:
    """
    Trả về list segment: [{"start": 0.0, "end": 3.2, "text": "..."}, ...]
    """
    if not GROQ_API_KEY:
        raise RuntimeError("Thiếu GROQ_API_KEY trong file .env")

    audio_path = extract_audio(video_path)
    print(f"[transcribe] Đang gửi audio lên Groq Whisper API...")

    client = Groq(api_key=GROQ_API_KEY)
    with open(audio_path, "rb") as f:
        response = client.audio.transcriptions.create(
            file=(audio_path.name, f.read()),
            model=GROQ_ASR_MODEL,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )

    segments = [
        {"start": round(seg["start"], 3), "end": round(seg["end"], 3), "text": seg["text"].strip()}
        for seg in response.segments
    ]

    out_path = WORK_DIR / "transcript.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)

    print(f"[transcribe] {len(segments)} đoạn thoại -> {out_path}")
    return segments


if __name__ == "__main__":
    video = sys.argv[1] if len(sys.argv) > 1 else str(WORK_DIR / "source.mp4")
    transcribe(Path(video))
