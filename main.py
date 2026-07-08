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
from subtitles import build_srt as generate_srt
from sync_assemble import assemble_video_and_audio
from download import download_video


def check_dependencies():
    for binary in ["ffmpeg", "ffprobe"]:
        if not shutil.which(binary):
            print(f"❌ LỖI NGHIÊM TRỌNG: Không tìm thấy lệnh '{binary}' trong hệ thống!")
            sys.exit(1)


def wizard_mode():
    check_dependencies()
    print("\n" + "="*50)
    print("🎬 CHÀO MỪNG BẠN ĐẾN VỚI TRÌNH DỰNG PHIM AI-ARV 🎬")
    print("="*50 + "\n")

    # Bước 1: Nhập Video
    video_input = input("👉 Nhập link YouTube hoặc đường dẫn file video: ").strip()
    if not video_input:
        print("❌ Vui lòng nhập thông tin!")
        return

    if video_input.startswith("http"):
        print(f"📥 Đang tải video từ YouTube...")
        video_path = download_video(video_input)
    else:
        video_path = Path(video_input).resolve()
        if not video_path.exists():
            print(f"❌ Không tìm thấy file: {video_input}")
            return
        dest_path = config.WORK_DIR / "source.mp4"
        if video_path != dest_path:
            shutil.copy(video_path, dest_path)
        video_path = dest_path

    # Bước 2: Chọn chế độ cắt
    print("\n🎞️ Chọn chế độ chia cảnh:")
    print("1. Cắt thô bạo (Interval - Nhanh, khuyên dùng cho phim dài)")
    print("2. Cắt thông minh (Content - Chính xác, cần CPU mạnh)")
    choice = input("Lựa chọn của bạn (1/2, mặc định 1): ").strip()
    
    if choice == "2":
        config.SCENE_DETECT_METHOD = "content"
    else:
        config.SCENE_DETECT_METHOD = "interval"

    # Bước 3: Chạy Prepare
    print("\n🚀 Bắt đầu bước CHUẨN BỊ (Prepare)...")
    if config.TEMP_DIR.exists():
        shutil.rmtree(config.TEMP_DIR)
    config.TEMP_DIR.mkdir(parents=True, exist_ok=True)
    
    print("[1/4] Đang phân tích cảnh quay...")
    scenes = detect_scenes(video_path)
    
    print("[2/4] Đang phiên âm audio...")
    transcript = transcribe_video(video_path)
    
    print("[3/4] AI đang viết kịch bản tóm tắt...")
    draft_path = config.WORK_DIR / "script_draft.json"
    generate_script(transcript, scenes, draft_path, video_path=video_path)
    
    final_path = config.WORK_DIR / "script_final.json"
    
    print(f"\n✅ Đã soạn xong kịch bản nháp tại: {draft_path}")
    print("💡 Bạn có thể mở file trên để chỉnh sửa nội dung theo ý muốn.")
    
    confirm = input("\n👉 Bạn đã sẵn sàng để RENDER chưa? (Ấn Enter để tiếp tục, hoặc 'q' để dừng): ").strip().lower()
    if confirm == 'q':
        print("👋 Đã dừng quy trình. Bạn có thể chạy lại lệnh 'render' sau khi sửa kịch bản.")
        return

    if not final_path.exists():
        shutil.copy(draft_path, final_path)

    # Bước 4: Chạy Render
    run_render_flow()


def run_render_flow():
    check_dependencies()
    print("\n🎨 Bắt đầu bước XUẤT VIDEO (Render)...")
    final_path = config.WORK_DIR / "script_final.json"
    if not final_path.exists():
        print(f"❌ Không tìm thấy {final_path}. Vui lòng chạy bước 'prepare' trước.")
        return

    with open(final_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    print("[1/3] Đang tạo giọng đọc AI (Native)...")
    tts_segments = process_all_tts(script)

    print("[2/3] Đang tạo phụ đề...")
    srt_path = config.WORK_DIR / "recap.srt"
    generate_srt(tts_segments, srt_path)

    print("[3/3] Đang dựng phim theo lời bình (Cut-to-Speech)...")
    output_path = config.OUTPUT_DIR / "recap_final.mp4"
    
    if output_path.exists():
        os.remove(output_path)
        
    success = assemble_video_and_audio(
        config.WORK_DIR / "source.mp4",
        srt_path,
        tts_segments,
        output_path,
        keep_bg=False
    )

    if success:
        print(f"\n🎉 THÀNH CÔNG! Video của bạn đã sẵn sàng tại: {output_path}")
    else:
        print("\n❌ Quá trình Render gặp lỗi. Vui lòng kiểm tra log.")


def main():
    parser = argparse.ArgumentParser(description="AI Video Recap Tool")
    sub = parser.add_subparsers(dest="command")

    p_setup = sub.add_parser("setup")
    p_setup.add_argument("--force", action="store_true")

    p_dl = sub.add_parser("download")
    p_dl.add_argument("url")

    p_prep = sub.add_parser("prepare")
    p_prep.add_argument("video_path", nargs="?")
    p_prep.add_argument("--force", action="store_true")

    p_render = sub.add_parser("render")
    p_render.add_argument("--force", action="store_true")

    args = parser.parse_args()

    if not args.command:
        wizard_mode()
    elif args.command == "setup":
        print("Chức năng setup đang được nâng cấp...")
    elif args.command == "download":
        download_video(args.url)
    elif args.command == "prepare":
        video_path = Path(args.video_path).resolve()
        dest_path = config.WORK_DIR / "source.mp4"
        if video_path != dest_path:
            shutil.copy(video_path, dest_path)
        scenes = detect_scenes(dest_path)
        transcript = transcribe_video(dest_path)
        generate_script(transcript, scenes, config.WORK_DIR / "script_draft.json", video_path=dest_path)
    elif args.command == "render":
        run_render_flow()


if __name__ == "__main__":
    main()
