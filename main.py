import os
import sys
import json
import shutil
import argparse
from pathlib import Path

import config
from download import download_video
from scene_detect import detect_scenes
from transcribe import transcribe_video
from script_gen import generate_script
from tts import process_all_tts
from subtitles import build_srt as generate_srt
from sync_assemble import assemble_video_and_audio
from agent_manager import agent


def check_dependencies():
    for binary in ["ffmpeg", "ffprobe"]:
        if not shutil.which(binary):
            print(f"❌ LỖI: Không tìm thấy '{binary}'!")
            sys.exit(1)


def smart_agent_mode():
    check_dependencies()
    print("\n" + "🤖"*20)
    print("   AI-ARV AGENT: TRỢ LÝ DỰNG PHIM THÔNG MINH")
    print("🤖"*20 + "\n")

    print("AI: Chào chủ nhân! Tôi đã sẵn sàng. Bạn muốn làm video từ đâu?")
    video_input = input("Bạn: ").strip()
    
    if video_input.startswith("http"):
        print("AI: Đang tải video cho bạn, đợi tôi một chút...")
        video_path = download_video(video_input)
    else:
        video_path = Path(video_input).resolve()
        if not video_path.exists():
            print(f"AI: Tôi không tìm thấy file {video_input}, bạn kiểm tra lại nhé.")
            return
        dest_path = config.WORK_DIR / "source.mp4"
        if video_path != dest_path: shutil.copy(video_path, dest_path)
        video_path = dest_path

    # Chạy Prepare tự động
    print("\nAI: Đang phân tích phim và soạn kịch bản nháp...")
    if config.TEMP_DIR.exists(): shutil.rmtree(config.TEMP_DIR)
    config.TEMP_DIR.mkdir(parents=True, exist_ok=True)
    
    scenes = detect_scenes(video_path)
    transcript = transcribe_video(video_path)
    draft_path = config.WORK_DIR / "script_draft.json"
    generate_script(transcript, scenes, draft_path, video_path=video_path)
    
    print(f"AI: Kịch bản đã xong tại {draft_path}. Bạn có muốn thêm nhạc nền hay yêu cầu gì đặc biệt không?")
    
    while True:
        user_req = input("Bạn (nhập 'render' để bắt đầu, 'q' để thoát): ").strip()
        if user_req.lower() == 'render':
            break
        if user_req.lower() == 'q':
            return
            
        # AI xử lý yêu cầu ngôn ngữ tự nhiên
        ai_response = agent.chat(user_req)
        print(f"AI: {ai_response}")

    # Chạy Render
    run_render_flow()


def run_render_flow():
    print("\n🎨 AI: Bắt đầu quá trình dựng phim (Render)...")
    final_path = config.WORK_DIR / "script_final.json"
    if not final_path.exists():
        shutil.copy(config.WORK_DIR / "script_draft.json", final_path)

    with open(final_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    tts_segments = process_all_tts(script)
    srt_path = config.WORK_DIR / "recap.srt"
    generate_srt(tts_segments, srt_path)

    output_path = config.OUTPUT_DIR / "recap_final.mp4"
    if output_path.exists(): os.remove(output_path)
        
    success = assemble_video_and_audio(
        config.WORK_DIR / "source.mp4",
        srt_path,
        tts_segments,
        output_path,
        bgm_path=agent.bgm_path,
        bgm_volume=agent.bgm_volume,
        bgm_loop=agent.bgm_loop
    )

    if success:
        print(f"\n🎉 AI: TUYỆT VỜI! Video đã xong tại: {output_path}")
    else:
        explanation = agent.report_error("FF-ERR-500", "Lỗi trong quá trình ghép video cuối cùng.")
        print(f"\nAI: {explanation}")


def main():
    parser = argparse.ArgumentParser(description="AI-ARV Agent Mode")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("setup")
    sub.add_parser("download").add_argument("url")
    sub.add_parser("prepare").add_argument("video_path", nargs="?")
    sub.add_parser("render")

    args = parser.parse_args()
    if not args.command:
        smart_agent_mode()
    elif args.command == "render":
        run_render_flow()
    else:
        # Giữ tương thích cho các lệnh cũ
        pass

if __name__ == "__main__":
    main()
