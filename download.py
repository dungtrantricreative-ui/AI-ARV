import subprocess
from pathlib import Path
import config


def download_video(url: str, out_name: str = "source") -> Path:
    out_template = str(config.WORK_DIR / f"{out_name}.%(ext)s")
    cmd = [
        "yt-dlp",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", out_template,
        url,
    ]
    print(f"[download] Đang tải: {url}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp lỗi:\n{result.stderr}")
    video_path = config.WORK_DIR / f"{out_name}.mp4"
    if not video_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file tải về: {video_path}")
    print(f"[download] Xong: {video_path}")
    return video_path
