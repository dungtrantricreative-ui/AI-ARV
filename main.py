import os
import sys
import json
import shutil
import argparse
from pathlib import Path

import config
from scene_detect import detect_scenes
from transcribe import transcribe_video
from script_gen import generate_script
from tts import process_all_tts
from subtitles import build_srt
from sync_assemble import assemble_video_and_audio
from download import download_video


def check_dependencies():
    for binary in ["ffmpeg", "ffprobe"]:
        if not shutil.which(binary):
            print(f"❌ LỖI NGHIÊM TRỌNG: Không tìm thấy lệnh '{binary}' trong hệ thống!")
            print("👉 macOS: brew install ffmpeg | Ubuntu: sudo apt install ffmpeg | Windows: thêm vào PATH")
            sys.exit(1)
    print("✅ Kiểm tra hệ thống: Đầy đủ dependencies (ffmpeg, ffprobe).")


def validate_and_load_script(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Không tìm thấy tệp kịch bản: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Kịch bản phải là JSON Array.")
    required = {"ref_start", "ref_end", "text"}
    for idx, item in enumerate(data):
        missing = required - item.keys()
        if missing:
            raise KeyError(f"Dòng {idx+1} thiếu các trường: {missing}")
    return data


def cmd_download(args):
    # Trước đây download.py tồn tại nhưng không có subcommand nào gọi tới,
    # nên tính năng tải video coi như chết. Thêm subcommand "download".
    if not shutil.which("yt-dlp"):
        print("❌ Không tìm thấy 'yt-dlp'. Cài bằng: pip install yt-dlp")
        sys.exit(1)
    video_path = download_video(args.url)
    print(f"\n✅ Đã tải xong: {video_path}")
    print(f"👉 Chạy tiếp: python main.py prepare \"{video_path}\"")


def cmd_prepare(args):
    check_dependencies()
    if not args.video_path:
        print("❌ Cần cung cấp đường dẫn file video.")
        sys.exit(1)

    video_path = Path(args.video_path).resolve()
    if not video_path.exists():
        print(f"❌ Không tìm thấy file: {video_path}")
        sys.exit(1)

    dest_path = config.WORK_DIR / "source.mp4"
    if video_path != dest_path:
        if args.force or not dest_path.exists():
            print(f"[prepare] Copy video vào workdir: {dest_path}")
            shutil.copy2(str(video_path), str(dest_path))
        else:
            print(f"[prepare] Dùng source.mp4 có sẵn trong workdir (bỏ qua --force để ghi đè)")
    video_path = dest_path

    # Bước 2: Chia cảnh
    scenes = detect_scenes(video_path)

    # Bước 3: Phiên âm
    transcript = transcribe_video(video_path)

    # Bước 4: Sinh script nháp
    draft_path = config.WORK_DIR / "script_draft.json"
    generate_script(transcript, scenes, draft_path)

    print(f"\n✅ Xong bước PREPARE. Kịch bản nháp: {draft_path}")
    print("👉 Hãy sửa file trên thành 'workdir/script_final.json' rồi chạy: python main.py render")


def cmd_render(args):
    check_dependencies()
    script_final_path = config.WORK_DIR / "script_final.json"
    try:
        script = validate_and_load_script(script_final_path)
        print(f"✅ Kịch bản hợp lệ: {len(script)} dòng thoại.")
    except Exception as e:
        print(f"❌ {e}")
        sys.exit(1)

    video_path = config.WORK_DIR / "source.mp4"
    if not video_path.exists():
        print("❌ Không tìm thấy source.mp4 trong workdir. Chạy 'prepare' trước.")
        sys.exit(1)

    # Bước 5: TTS + neo mốc
    tts_segments = process_all_tts(script)

    # Bước 6: Phụ đề
    srt_path = config.WORK_DIR / "recap.srt"
    build_srt(tts_segments, srt_path)

    # Bước 7: Ghép video cuối
    output_path = config.OUTPUT_DIR / "recap_final.mp4"
    if output_path.exists() and not args.force:
        print(f"❌ {output_path} đã tồn tại. Dùng --force để ghi đè.")
        sys.exit(1)
    assemble_video_and_audio(
        video_path,
        srt_path,
        tts_segments,
        output_path,
        keep_bg=args.keep_bg_audio,
        no_subs=args.no_subtitles,
    )
    print(f"\n🎬 Video cuối nằm tại: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="AI Video Recap Tool")
    sub = parser.add_subparsers(dest="command")

    p_dl = sub.add_parser("download", help="Tải video từ URL bằng yt-dlp (tùy chọn, cần cài yt-dlp)")
    p_dl.add_argument("url", help="URL video (YouTube, v.v.)")

    p_prep = sub.add_parser("prepare", help="Chia cảnh, phiên âm, sinh script nháp từ file video")
    p_prep.add_argument("video_path", nargs="?", help="Đường dẫn file video (.mp4, .mkv, .mov...)")
    p_prep.add_argument("--force", action="store_true", help="Ghi đè source.mp4 nếu đã tồn tại")

    p_render = sub.add_parser("render", help="TTS, phụ đề, ghép video")
    p_render.add_argument("--no-subtitles", action="store_true", dest="no_subtitles", help="Không burn phụ đề")
    p_render.add_argument("--keep-bg-audio", action="store_true", dest="keep_bg_audio", help="Giữ tiếng nền nhỏ")
    p_render.add_argument("--force", action="store_true", help="Bỏ qua cache nếu có")

    args = parser.parse_args()
    if args.command == "download":
        cmd_download(args)
    elif args.command == "prepare":
        cmd_prepare(args)
    elif args.command == "render":
        cmd_render(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
