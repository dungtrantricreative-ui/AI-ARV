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

    print("AI: Chào chủ nhân! Tôi đã sẵn sàng. Bạn muốn làm video từ đâu? (Nhập link hoặc đường dẫn file)")
    
    # Vòng lặp chính của Agent
    while True:
        user_input = input("\nBạn: ").strip()
        if not user_input:
            continue
            
        # Xử lý lệnh dừng ngay lập tức nếu người dùng nhập thủ công các từ khóa thoát
        if user_input.lower() in ['exit', 'quit', 'q', 'dừng', 'thoát', 'stop']:
            print("AI: Tạm biệt chủ nhân! Hẹn gặp lại.")
            break

        # AI xử lý yêu cầu
        ai_data = agent.chat(user_input)
        
        # Nếu AI nhận diện ý định dừng chương trình
        if ai_data.get("intent") == "stop_program":
            print(f"AI: {ai_data['response']}")
            break
            
        # Ưu tiên lấy video_path từ AI trích xuất (params) hoặc từ user_input trực tiếp
        video_input = ai_data.get("params", {}).get("video_path") or user_input
        
        is_video_input = False
        video_path = None
        
        # Kiểm tra xem video_input có phải là URL hay Path hợp lệ không
        if str(video_input).startswith("http"):
            is_video_input = True
            print(f"AI: Đang tải video từ URL: {video_input} ...")
            try:
                video_path = download_video(video_input)
            except Exception as e:
                print(f"AI: Lỗi khi tải video: {e}")
                continue
        elif os.path.exists(str(video_input)) and str(video_input).lower().endswith(('.mp4', '.mkv', '.avi', '.mov')):
            is_video_input = True
            video_path = Path(video_input).resolve()
            dest_path = config.WORK_DIR / "source.mp4"
            if video_path != dest_path: 
                shutil.copy(video_path, dest_path)
            video_path = dest_path

        if is_video_input and video_path:
            # Chạy Prepare tự động khi có video mới
            print(f"\nAI: Đã nhận video tại {video_path}. Đang phân tích phim và soạn kịch bản nháp...")
            if config.TEMP_DIR.exists(): shutil.rmtree(config.TEMP_DIR)
            config.TEMP_DIR.mkdir(parents=True, exist_ok=True)
            
            scenes = detect_scenes(video_path)
            transcript = transcribe_video(video_path)
            draft_path = config.WORK_DIR / "script_draft.json"
            generate_script(transcript, scenes, draft_path, video_path=video_path)
            
            print(f"AI: Phân tích xong! Kịch bản nháp đã sẵn sàng tại {draft_path}.")
            print("AI: Bạn có muốn chỉnh sửa gì không, hay gõ 'render' để tôi bắt đầu dựng phim?")
            continue

        # Nếu người dùng muốn render
        if ai_data.get("intent") == "start_render" or user_input.lower() == 'render':
            if not (config.WORK_DIR / "source.mp4").exists():
                print("AI: Chủ nhân ơi, tôi chưa có video đầu vào để render. Hãy cho tôi link hoặc path video trước nhé!")
            else:
                run_render_flow()
            continue

        # Mặc định là trả lời chat bình thường hoặc kết quả terminal
        print(f"AI: {ai_data['response']}")


def run_render_flow():
    print("\n🎨 AI: Bắt đầu quá trình dựng phim (Render)...")
    final_path = config.WORK_DIR / "script_final.json"
    draft_path = config.WORK_DIR / "script_draft.json"
    
    if not draft_path.exists():
        print("AI: Lỗi: Không tìm thấy kịch bản nháp. Vui lòng cung cấp video trước.")
        return

    # Luôn đồng bộ kịch bản mới nhất nếu người dùng chưa sửa file final
    if not final_path.exists():
        shutil.copy(draft_path, final_path)

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
        # Giữ tương thích cho các lệnh cũ nếu cần
        pass

if __name__ == "__main__":
    main()
