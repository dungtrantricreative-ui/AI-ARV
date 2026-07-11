"""
frame_extract.py — Trích một số khung hình đại diện từ 1 khoảng thời gian
trong video, dùng làm input cho model vision (Gemma 4 31B qua Cerebras...).

Chỉ trích đúng số khung cần thiết (config.DIRECTOR_FRAMES_PER_BLOCK), resize
nhỏ lại trước khi encode base64 (config.DIRECTOR_FRAME_MAX_WIDTH) để giảm
băng thông upload và số token ảnh — đây là phần "tiết kiệm" quan trọng nhất:
không bao giờ decode/gửi nguyên video, chỉ gửi vài JPEG nhỏ mỗi khi thực sự
cần.

VỊ TRÍ khung hình được chọn CÀNG CÁCH XA NHAU về thời gian càng tốt (dựa trên
config.DIRECTOR_FRAME_EDGE_MARGIN, lùi vào từ 2 mép của block) thay vì dồn
gần giữa: mặc định gửi 2 khung/block, 1 khung gần đầu + 1 khung gần cuối, để
model vision có thể SO SÁNH 2 thời điểm khác nhau (ai vừa xuất hiện/biến mất,
tư thế/biểu cảm/bối cảnh đổi thế nào) thay vì suy đoán từ 2 khung gần như
giống hệt nhau -> hiểu đúng diễn biến/ngữ cảnh của câu thoại tốt hơn.
"""
import subprocess
from pathlib import Path

import config
import logutil


def extract_frames(video_path: Path, start: float, end: float, count: int, out_dir: Path, tag: str) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    count = max(1, count)
    duration = max(end - start, 0.01)
    margin = min(max(getattr(config, "DIRECTOR_FRAME_EDGE_MARGIN", 0.15), 0.0), 0.45)
    paths = []
    for i in range(count):
        if count == 1:
            # Chỉ 1 khung -> lấy giữa block như cũ (không có gì để so sánh).
            frac = 0.5
        else:
            # Trải đều từ mép margin đến mép (1-margin): khung đầu/cuối lùi
            # vào một chút để tránh đúng khung chuyển cảnh (dễ đen/mờ) ở sát
            # biên start/end, nhưng vẫn tối đa hoá khoảng cách thời gian giữa
            # các khung để tăng ngữ cảnh (thấy được thay đổi trong đoạn).
            frac = margin + (1.0 - 2 * margin) * (i / (count - 1))
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
            logutil.warn(f"⚠️ [frame_extract] Trích khung hình lỗi tại {ts:.1f}s: {result.stderr[-300:].strip()}")
            continue
        paths.append(out_path)
    return paths
