import os
import shutil
import subprocess
import asyncio
import json
from pathlib import Path
import config


def get_audio_duration(file_path):
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
        return float(out) if out else 0.0
    except (subprocess.CalledProcessError, ValueError) as e:
        print(f"⚠️ Không đo được duration: {e}")
        return 0.0


def build_atempo_filter(ratio):
    # Clamp theo giới hạn cấu hình trong config.py (MIN/MAX_TIME_STRETCH_RATIO),
    # trước đây bị hardcode 0.2-5.0 nên bỏ qua config hoàn toàn -> giọng có thể
    # bị kéo dãn/nén quá đà nghe méo. Mặc định 0.5x-2.0x, chỉnh trong config.py nếu cần.
    ratio = max(config.MIN_TIME_STRETCH_RATIO, min(config.MAX_TIME_STRETCH_RATIO, ratio))
    filters = []
    # atempo filter của ffmpeg chỉ nhận 0.5-2.0 mỗi lần, cần chia nhỏ nếu range cấu hình
    # rộng hơn (vd nếu người dùng tự nới MAX lên 4.0 trong config.py)
    while ratio > 2.0:
        filters.append("atempo=2.0")
        ratio /= 2.0
    while ratio < 0.5:
        filters.append("atempo=0.5")
        ratio /= 0.5
    filters.append(f"atempo={ratio:.2f}")
    return ",".join(filters)


async def _synth(text, output_path, voice=config.DEFAULT_VOICE):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


async def safe_synth_with_retry(text, raw_path, max_retries=3):
    for attempt in range(max_retries):
        try:
            await _synth(text, raw_path)
            if os.path.exists(raw_path) and os.path.getsize(raw_path) > 0:
                return
        except Exception as e:
            print(f"⚠️ TTS lỗi lần {attempt+1}: {e}")
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)


async def _process_tts_line_async(line, idx):
    raw_path = config.TEMP_DIR / f"tts_{idx}_raw.mp3"
    final_path = config.TEMP_DIR / f"tts_{idx}_fit.mp3"

    try:
        await safe_synth_with_retry(line["text"], str(raw_path))
    except Exception as e:
        print(f"❌ Không thể tạo giọng nói dòng {idx}: {e}")
        return None

    target_duration = line["ref_end"] - line["ref_start"]
    if target_duration <= 0:
        print(f"⚠️ Line {idx}: ref_start/ref_end không hợp lệ ({line['ref_start']}-{line['ref_end']}), "
              f"dùng fallback 2.0s. Kiểm tra lại script_final.json nếu audio bị cắt/lệch.")
        target_duration = 2.0
    actual_duration = get_audio_duration(raw_path)
    if actual_duration == 0:
        actual_duration = 2.0

    ratio = actual_duration / target_duration
    print(f"🎤 Line {idx} -> raw: {actual_duration:.2f}s | target: {target_duration:.2f}s | ratio: {ratio:.2f}x")

    atempo_filter = build_atempo_filter(ratio)
    cmd = [
        "ffmpeg", "-y", "-i", str(raw_path),
        "-filter:a", atempo_filter,
        str(final_path)
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"⚠️ atempo lỗi, dùng raw fallback (audio sẽ không khớp mốc thời gian): {e}")
        if e.stderr:
            print(f"   ffmpeg stderr: {e.stderr[-800:]}")
        shutil.copy(str(raw_path), str(final_path))

    return {
        "idx": idx,
        "start": line["ref_start"],
        "end": line["ref_end"],
        "text": line["text"],
        "audio_path": str(final_path)
    }


async def process_all_tts_async(script):
    tasks = [_process_tts_line_async(line, idx) for idx, line in enumerate(script)]
    segments = await asyncio.gather(*tasks)
    segments = [s for s in segments if s is not None]
    out = config.WORK_DIR / "tts_segments.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)
    return segments


def process_all_tts(script):
    # Chạy async một lần duy nhất, tránh lỗi event loop lồng nhau
    return asyncio.run(process_all_tts_async(script))
