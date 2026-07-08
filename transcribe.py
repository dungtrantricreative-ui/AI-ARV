import time
import json
import subprocess
from pathlib import Path
import config


def _extract_audio(video_path: Path) -> Path:
    """Trích xuất audio sang mp3 để gửi API, giảm dung lượng xuống ~5-10%.

    Cache key dựa trên tên file + size + mtime của video gốc, KHÔNG chỉ theo
    stem. Trước đây cache chỉ theo stem ("source") nên chạy `prepare` lần 2
    với video khác (dù ghi đè source.mp4 bằng --force) vẫn dùng nhầm audio
    .mp3 cũ trong TEMP_DIR -> phiên âm sai nội dung.
    """
    stat = video_path.stat()
    cache_key = f"{video_path.stem}_{stat.st_size}_{int(stat.st_mtime)}"
    audio_path = config.TEMP_DIR / f"audio_{cache_key}.mp3"
    if audio_path.exists():
        print(f"[transcribe] Dùng audio cache có sẵn -> {audio_path}")
        return audio_path
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-ar", "16000", "-ac", "1", "-b:a", "32k",
        str(audio_path)
    ]
    print(f"[transcribe] Trích audio -> {audio_path}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ ffmpeg trích audio thất bại:\n{result.stderr[-2000:]}")
        raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)
    return audio_path


def call_api_with_retry(api_func, *args, **kwargs):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return api_func(*args, **kwargs)
        except Exception as e:
            err_msg = str(e).lower()
            if "429" in err_msg or "rate limit" in err_msg or "quota" in err_msg:
                wait_time = 5 * (attempt + 1)
                print(f"⚠️ Rate limit. Chờ {wait_time}s rồi thử lại...")
                time.sleep(wait_time)
            else:
                print(f"❌ Lỗi API nghiêm trọng: {e}")
                raise
    raise RuntimeError("API từ chối sau 3 lần thử.")


def transcribe_video(video_path: Path) -> list[dict]:
    print(f"[transcribe] Đang phiên âm: {video_path}")

    # Trích audio trước khi gửi API (tránh lỗi file quá lớn / không đúng format)
    audio_path = _extract_audio(video_path)

    provider = config.ASR_PROVIDER.lower()
    if provider == "groq":
        segments = _transcribe_groq(audio_path)
    elif provider == "openai":
        segments = _transcribe_openai(audio_path)
    else:
        raise ValueError(f"ASR provider không hỗ trợ: {provider}")

    out = config.WORK_DIR / "transcript.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)
    print(f"[transcribe] Xong: {len(segments)} đoạn -> {out}")
    return segments


def _extract_segments(resp):
    # Xử lý nhiều kiểu response từ các SDK khác nhau
    data = resp
    if hasattr(resp, "model_dump"):
        data = resp.model_dump()
    elif hasattr(resp, "to_dict"):
        data = resp.to_dict()
    elif hasattr(resp, "text") and not isinstance(data, dict):
        try:
            data = json.loads(resp.text)
        except Exception:
            pass

    segs = data.get("segments", []) if isinstance(data, dict) else []
    result = []
    for s in segs:
        if isinstance(s, dict):
            result.append({
                "start": s.get("start", 0),
                "end": s.get("end", 0),
                "text": s.get("text", "")
            })
        else:
            result.append({
                "start": getattr(s, "start", 0),
                "end": getattr(s, "end", 0),
                "text": getattr(s, "text", "")
            })
    return result


def _transcribe_groq(audio_path: Path):
    from groq import Groq
    client = Groq(api_key=config.ASR_API_KEY)

    def _call():
        with open(audio_path, "rb") as f:
            return client.audio.transcriptions.create(
                file=f,
                model=config.ASR_MODEL,
                response_format="verbose_json"
            )
    return _extract_segments(call_api_with_retry(_call))


def _transcribe_openai(audio_path: Path):
    from openai import OpenAI
    client = OpenAI(api_key=config.ASR_API_KEY, base_url=config.ASR_BASE_URL)

    def _call():
        with open(audio_path, "rb") as f:
            return client.audio.transcriptions.create(
                model=config.ASR_MODEL,
                file=f,
                response_format="verbose_json"
            )
    return _extract_segments(call_api_with_retry(_call))
