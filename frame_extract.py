"""
frame_extract.py — Trích một số khung hình đại diện từ 1 khoảng thời gian
trong video, dùng làm input cho model vision (Gemma 4 31B qua Cerebras...).

Chỉ trích đúng số khung cần thiết (config.DIRECTOR_FRAMES_PER_BLOCK), resize
nhỏ lại trước khi encode base64 (config.DIRECTOR_FRAME_MAX_WIDTH) để giảm
băng thông upload và số token ảnh — đây là phần "tiết kiệm" quan trọng nhất:
không bao giờ decode/gửi nguyên video, chỉ gửi vài JPEG nhỏ mỗi khi thực sự
cần.
"""
import subprocess
from pathlib import Path

import config


def extract_frames(video_path: Path, start: float, end: float, count: int, out_dir: Path, tag: str) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    count = max(1, count)
    duration = max(end - start, 0.01)
    paths = []
    for i in range(count):
        # Lấy mẫu đều nhau, lùi vào giữa mỗi phần để tránh dính đúng khung
        # chuyển cảnh (dễ bị đen/mờ) ở đúng biên start/end.
        frac = (i + 0.5) / count
        ts = start + duration * frac
        out_path = out_dir / f"frame_{tag}_{i}.jpg"
        cmd = [
            "ffmpeg", "-y", "-ss", f"{ts:.3f}", "-i", str(video_path),
            "-frames:v", "1",
            "-vf", f"scale='min({config.DIRECTOR_FRAME_MAX_WIDTH},iw)':-2",
            "-q:v", "4", str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not out_path.exists():
            print(f"⚠️ [frame_extract] Trích khung hình lỗi tại {ts:.1f}s: {result.stderr[-300:].strip()}")
            continue
        paths.append(out_path)
    return paths
