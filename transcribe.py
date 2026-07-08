import time
import json
import shutil
import tempfile
import subprocess
from pathlib import Path
import config

# Độ dài mỗi đoạn audio khi cắt nhỏ (giây). 10 phút là mốc an toàn cho hầu hết
# API ASR (Groq/OpenAI) tránh bị timeout hoặc từ chối vì file quá lớn.
CHUNK_DURATION_SEC = 600


def _get_audio_duration(audio_path: Path) -> float:
    """Lấy thời lượng audio (giây) bằng ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"ffprobe không đọc được thời lượng audio:\n{result.stderr[-500:]}")
    return float(result.stdout.strip())


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


def _split_audio_chunks(audio_path: Path, chunk_dir: Path, chunk_sec: int = CHUNK_DURATION_SEC) -> list[dict]:
    """Cắt audio dài thành nhiều đoạn nhỏ (mặc định 10 phút/đoạn) để tránh
    timeout / lỗi file quá lớn khi gọi API ASR.

    Trả về danh sách [{"path": Path, "offset": float}], theo đúng thứ tự thời
    gian trong video gốc. `offset` là số giây đoạn này bắt đầu so với audio
    gốc, dùng để cộng dồn timestamp sau khi có kết quả.

    Dùng `ffmpeg -f segment` để cắt rồi đo lại thời lượng thật của từng đoạn
    bằng ffprobe -> offset cộng dồn chính xác, tránh trôi (drift) do làm
    tròn số nếu tự tính "index * chunk_sec".
    """
    duration = _get_audio_duration(audio_path)
    if duration <= chunk_sec:
        # File đủ ngắn, không cần cắt.
        return [{"path": audio_path, "offset": 0.0}]

    chunk_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(chunk_dir / "chunk_%04d.mp3")
    cmd = [
        "ffmpeg", "-y", "-i", str(audio_path),
        "-f", "segment", "-segment_time", str(chunk_sec),
        "-c", "copy", "-reset_timestamps", "1",
        pattern,
    ]
    print(f"[transcribe] Audio dài {duration:.0f}s > {chunk_sec}s -> cắt thành từng đoạn {chunk_sec}s...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ ffmpeg cắt audio thất bại:\n{result.stderr[-2000:]}")
        raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)

    chunk_paths = sorted(chunk_dir.glob("chunk_*.mp3"))
    if not chunk_paths:
        raise RuntimeError("Cắt audio thành công nhưng không tạo ra đoạn nào (kiểm tra lại ffmpeg).")

    chunks = []
    offset = 0.0
    for p in chunk_paths:
        chunks.append({"path": p, "offset": offset})
        offset += _get_audio_duration(p)
    print(f"[transcribe] Đã cắt thành {len(chunks)} đoạn.")
    return chunks


def call_api_with_retry(api_func, *args, max_retries=4, base_wait=5, label="asr", **kwargs):
    """Tự động thử lại khi gặp lỗi tạm thời: Timeout, Rate Limit (429),
    quota, hoặc server quá tải (503/overloaded). Các lỗi khác (vd sai định
    dạng, API key sai) sẽ raise ngay, không thử lại vô ích."""
    last_err = None
    for attempt in range(max_retries):
        try:
            return api_func(*args, **kwargs)
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            is_timeout = isinstance(e, TimeoutError) or "timeout" in msg or "timed out" in msg
            is_rate_limit = "429" in msg or "rate limit" in msg or "quota" in msg
            is_overloaded = "503" in msg or "overloaded" in msg
            is_transient = is_timeout or is_rate_limit or is_overloaded

            if is_transient and attempt < max_retries - 1:
                wait_time = base_wait * (attempt + 1)
                reason = "Timeout" if is_timeout else ("Rate limit/Quota" if is_rate_limit else "Server quá tải")
                print(f"⚠️ [{label}] {reason}. Chờ {wait_time}s rồi thử lại ({attempt + 1}/{max_retries})...")
                time.sleep(wait_time)
            else:
                print(f"❌ [{label}] Lỗi API nghiêm trọng: {e}")
                raise
    raise RuntimeError(f"[{label}] API từ chối sau {max_retries} lần thử: {last_err}")


def transcribe_video(video_path: Path) -> list[dict]:
    print(f"[transcribe] Đang phiên âm: {video_path}")

    # Trích audio trước khi gửi API (tránh lỗi file quá lớn / không đúng format)
    audio_path = _extract_audio(video_path)

    provider = config.ASR_PROVIDER.lower()
    if provider == "groq":
        transcribe_fn = _transcribe_groq
    elif provider == "openai":
        transcribe_fn = _transcribe_openai
    else:
        raise ValueError(f"ASR provider không hỗ trợ: {provider}")

    # Dùng tempfile.TemporaryDirectory (tự dọn dẹp, tương thích Windows/Linux,
    # không để lại rác nếu chương trình bị ngắt giữa chừng nhờ khối try/finally
    # nội bộ của contextmanager) thay vì tự quản lý đường dẫn tạm bằng tay.
    segments: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="arv_chunks_", dir=str(config.TEMP_DIR)) as tmp_dir:
        chunk_dir = Path(tmp_dir)
        chunks = _split_audio_chunks(audio_path, chunk_dir)
        n_chunks = len(chunks)

        for i, chunk in enumerate(chunks, 1):
            chunk_path, offset = chunk["path"], chunk["offset"]
            print(f"[transcribe] Đang gửi đoạn {i}/{n_chunks} (offset +{offset:.1f}s) -> {chunk_path.name}")
            chunk_segments = transcribe_fn(chunk_path, label=f"asr-chunk-{i}/{n_chunks}")
            # Đồng bộ thời gian: cộng dồn offset để khớp với video gốc.
            for seg in chunk_segments:
                seg["start"] = round(seg.get("start", 0.0) + offset, 3)
                seg["end"] = round(seg.get("end", 0.0) + offset, 3)
            segments.extend(chunk_segments)
        # TemporaryDirectory tự xoá toàn bộ chunk khi thoát khối `with`,
        # kể cả khi có exception ở giữa vòng lặp -> không rác file tạm.

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


def _transcribe_groq(audio_path: Path, label: str = "asr-groq"):
    from groq import Groq
    client = Groq(api_key=config.ASR_API_KEY)

    def _call():
        with open(audio_path, "rb") as f:
            return client.audio.transcriptions.create(
                file=f,
                model=config.ASR_MODEL,
                response_format="verbose_json"
            )
    return _extract_segments(call_api_with_retry(_call, label=label))


def _transcribe_openai(audio_path: Path, label: str = "asr-openai"):
    from openai import OpenAI
    client = OpenAI(api_key=config.ASR_API_KEY, base_url=config.ASR_BASE_URL)

    def _call():
        with open(audio_path, "rb") as f:
            return client.audio.transcriptions.create(
                model=config.ASR_MODEL,
                file=f,
                response_format="verbose_json"
            )
    return _extract_segments(call_api_with_retry(_call, label=label))
