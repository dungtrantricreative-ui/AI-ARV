import os
import re
import shutil
import subprocess
import asyncio
import json
from pathlib import Path
import config
import logutil

# Lưới an toàn thứ 2 (script_gen.py đã lọc trước khi lưu script_draft.json,
# nhưng nếu người dùng tự sửa tay file JSON hoặc dùng script cũ chưa lọc,
# vẫn không để lọt nhãn "importance: N" vào audio đọc lên).
_IMPORTANCE_LEAK_RE = re.compile(
    r"[\.\s]*\(?\s*importance\s*[:\-]?\s*[1-5]\s*\)?\s*\.?\s*$", re.IGNORECASE
)


def get_audio_duration(file_path):
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
        return float(out) if out else 0.0
    except (subprocess.CalledProcessError, ValueError) as e:
        logutil.warn(f"⚠️ Không đo được duration: {e}")
        return 0.0


async def _synth(text, output_path, voice=config.DEFAULT_VOICE):
    import edge_tts
    rate = getattr(config, "TTS_RATE", "+0%") or "+0%"
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(output_path)


async def safe_synth_with_retry(text, raw_path, max_retries=3):
    for attempt in range(max_retries):
        try:
            await _synth(text, raw_path)
            if os.path.exists(raw_path) and os.path.getsize(raw_path) > 0:
                return
        except Exception as e:
            logutil.warn(f"⚠️ TTS lỗi lần {attempt+1}: {e}")
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)


async def _process_tts_line_async(line, idx, semaphore):
    raw_path = config.TEMP_DIR / f"tts_{idx}_raw.mp3"
    final_path = config.TEMP_DIR / f"tts_{idx}_native.mp3"

    text = _IMPORTANCE_LEAK_RE.sub("", line["text"] or "").strip()
    if not text:
        logutil.warn(f"⚠️ Dòng {idx} rỗng sau khi lọc, bỏ qua.")
        return None

    try:
        async with semaphore:
            await safe_synth_with_retry(text, str(raw_path))
    except Exception as e:
        logutil.err(f"❌ Không thể tạo giọng nói dòng {idx}: {e}")
        return None

    actual_duration = get_audio_duration(raw_path)
    if actual_duration == 0:
        actual_duration = 2.0
    
    # Dùng audio native không kéo dãn
    shutil.copy(str(raw_path), str(final_path))
    
    logutil.mic(f"🎤 Line {idx} -> Native: {actual_duration:.2f}s")

    return {
        "idx": idx,
        "start": line["ref_start"],
        "end": line["ref_end"],
        "text": text,
        "audio_path": str(final_path),
        "duration": actual_duration
    }


async def process_all_tts_async(script):
    max_concurrent = max(1, getattr(config, "TTS_MAX_CONCURRENT", 4))
    semaphore = asyncio.Semaphore(max_concurrent)
    tasks = [_process_tts_line_async(line, idx, semaphore) for idx, line in enumerate(script)]
    segments = await asyncio.gather(*tasks)
    segments = [s for s in segments if s is not None]
    out = config.WORK_DIR / "tts_segments.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)
    return segments


def process_all_tts(script):
    return asyncio.run(process_all_tts_async(script))
