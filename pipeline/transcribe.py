"""
Bước 3: Trích audio từ video và phiên âm.
Hỗ trợ nhiều dịch vụ ASR (Groq, OpenAI).
"""
import sys
import json
import subprocess
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from config import WORK_DIR, ASR_PROVIDER, ASR_API_KEY, ASR_MODEL, ASR_BASE_URL


def extract_audio(video_path: Path) -> Path:
    audio_path = WORK_DIR / "source_audio.wav"
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000",
        str(audio_path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return audio_path


def _seg_value(seg, key: str):
    if isinstance(seg, dict):
        return seg[key]
    return getattr(seg, key)


def _normalize_segments(raw_segments) -> list[dict]:
    normalized = []
    for seg in raw_segments or []:
        normalized.append({
            "start": round(float(_seg_value(seg, "start")), 3),
            "end": round(float(_seg_value(seg, "end")), 3),
            "text": str(_seg_value(seg, "text")).strip(),
        })
    return normalized


def transcribe(video_path: Path) -> list[dict]:
    """
    Trả về list segment: [{"start": 0.0, "end": 3.2, "text": "..."}, ...]
    """
    if not ASR_API_KEY:
        raise RuntimeError(f"Thiếu API key cho {ASR_PROVIDER} ASR - hãy đặt ASR_API_KEY hoặc key theo provider trong .env")

    audio_path = extract_audio(video_path)
    print(f"[transcribe] Dùng {ASR_PROVIDER} ASR, model: {ASR_MODEL}")
    if ASR_BASE_URL:
        print(f"[transcribe] Base URL: {ASR_BASE_URL}")

    provider = ASR_PROVIDER.strip().lower()
    if provider == "groq":
        segments = _transcribe_groq(audio_path)
    elif provider == "openai":
        segments = _transcribe_openai(audio_path)
    else:
        raise ValueError(f"Không hỗ trợ ASR provider: {ASR_PROVIDER}")

    out_path = WORK_DIR / "transcript.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)

    print(f"[transcribe] {len(segments)} đoạn thoại -> {out_path}")
    return segments


def _transcribe_groq(audio_path: Path) -> list[dict]:
    from groq import Groq

    client = Groq(api_key=ASR_API_KEY)
    with open(audio_path, "rb") as f:
        response = client.audio.transcriptions.create(
            file=(audio_path.name, f.read()),
            model=ASR_MODEL,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )

    return _normalize_segments(getattr(response, "segments", None))


def _transcribe_openai(audio_path: Path) -> list[dict]:
    from openai import OpenAI

    client = OpenAI(api_key=ASR_API_KEY, base_url=ASR_BASE_URL or None)
    with open(audio_path, "rb") as f:
        response = client.audio.transcriptions.create(
            file=(audio_path.name, f.read()),
            model=ASR_MODEL,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )

    return _normalize_segments(getattr(response, "segments", None))


if __name__ == "__main__":
    video = sys.argv[1] if len(sys.argv) > 1 else str(WORK_DIR / "source.mp4")
    transcribe(Path(video))
