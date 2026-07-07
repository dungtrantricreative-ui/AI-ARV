"""
Bước 1: Tải video từ link (YouTube hoặc nguồn khác) bằng yt-dlp.
"""
import subprocess
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent))
from config import WORK_DIR


def download_video(url: str, out_name: str = "source") -> Path:
    """
    Tải video về workdir, trả về đường dẫn file .mp4 đã tải.
    """
    out_template = str(WORK_DIR / f"{out_name}.%(ext)s")
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

    video_path = WORK_DIR / f"{out_name}.mp4"
    if not video_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file tải về tại {video_path}")

    print(f"[download] Xong: {video_path}")
    return video_path


if __name__ == "__main__":
    # Test nhanh: python pipeline/download.py <url>
    url = sys.argv[1] if len(sys.argv) > 1 else input("Nhập link video: ")
    download_video(url)
