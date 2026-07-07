"""
Bước 5: Đọc script_final.json (bản BẠN ĐÃ SỬA từ script_draft.json), sinh TTS
cho từng dòng, rồi time-stretch để khớp ĐÚNG khoảng (ref_start, ref_end) gốc
của dòng đó — không phân bổ theo tỷ lệ ký tự trên tổng thời lượng phim.

Đây là điểm khác biệt cốt lõi so với cách làm sai: mỗi dòng neo vào đúng
vị trí tuyệt đối của nó, lỗi (nếu có) chỉ nằm trong phạm vi dòng đó,
không cộng dồn và không làm nội dung lệch cảnh.
"""
import sys
import json
import subprocess
import asyncio
from pathlib import Path

import edge_tts

sys.path.append(str(Path(__file__).parent.parent))
from config import (
    WORK_DIR, TTS_VOICE_VI,
    MIN_TIME_STRETCH_RATIO, MAX_TIME_STRETCH_RATIO,
)

TTS_DIR = WORK_DIR / "tts_segments"


def _ffprobe_duration(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


async def _synth(text: str, out_path: Path, voice: str = TTS_VOICE_VI):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(out_path))


def _apply_atempo(src: Path, dst: Path, ratio: float):
    ratio = max(MIN_TIME_STRETCH_RATIO, min(MAX_TIME_STRETCH_RATIO, ratio))
    cmd = ["ffmpeg", "-y", "-i", str(src), "-filter:a", f"atempo={ratio:.4f}", str(dst)]
    subprocess.run(cmd, capture_output=True, check=True)
    return ratio


def generate_synced_tts(script: list[dict]) -> list[dict]:
    """
    Với mỗi dòng script {scene_id, ref_start, ref_end, text}, tạo file audio
    đã time-stretch để khớp đúng (ref_end - ref_start) giây.

    Trả về list segment kèm:
      - start, end: vị trí TUYỆT ĐỐI để đặt trên timeline cuối (bằng ref_start/ref_end)
      - file: đường dẫn audio đã sync
      - atempo: hệ số đã áp dụng (để debug)
      - duration_mismatch_sec: nếu > 0.3s nghĩa là câu quá dài/ngắn so với khung gốc,
        NÊN quay lại sửa text ở bước 5 cho khớp hơn, thay vì để atempo kéo giãn quá mức.
    """
    TTS_DIR.mkdir(exist_ok=True)
    results = []

    for i, line in enumerate(script):
        raw_path = TTS_DIR / f"line_{i:04d}_raw.mp3"
        synced_path = TTS_DIR / f"line_{i:04d}_synced.mp3"

        asyncio.run(_synth(line["text"], raw_path))
        actual_dur = _ffprobe_duration(raw_path)

        target_dur = max(0.05, line["ref_end"] - line["ref_start"])
        raw_ratio = actual_dur / target_dur
        applied_ratio = _apply_atempo(raw_path, synced_path, raw_ratio)

        final_dur = _ffprobe_duration(synced_path)
        mismatch = round(final_dur - target_dur, 3)

        results.append({
            "scene_id": line.get("scene_id"),
            "text": line["text"],
            "start": line["ref_start"],       # vị trí tuyệt đối trên timeline cuối
            "end": line["ref_start"] + final_dur,
            "target_dur": round(target_dur, 3),
            "actual_dur": round(final_dur, 3),
            "atempo": round(applied_ratio, 3),
            "duration_mismatch_sec": mismatch,
            "file": str(synced_path),
        })

        flag = "  ⚠ lệch nhiều, nên sửa lại text" if abs(mismatch) > 0.3 else ""
        print(f"[tts] dòng {i}: target={target_dur:.2f}s actual={final_dur:.2f}s atempo={applied_ratio:.2f}{flag}")

    out_path = WORK_DIR / "tts_segments.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"[tts] Xong {len(results)} dòng -> {out_path}")
    return results


if __name__ == "__main__":
    script_path = WORK_DIR / "script_final.json"
    if not script_path.exists():
        print(f"Chưa có {script_path}. Hãy copy script_draft.json -> script_final.json sau khi sửa xong.")
        sys.exit(1)
    script = json.load(open(script_path, encoding="utf-8"))
    generate_synced_tts(script)
