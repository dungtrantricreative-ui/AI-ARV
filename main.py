import os
import sys
import json
import shutil
import argparse
import subprocess
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


def is_valid_video(video_path: Path) -> bool:
    """Kiểm tra xem file có phải là video hợp lệ và không bị lỗi moov atom không."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode == 0
    except:
        return False


def smart_agent_mode():
    check_dependencies()
    print("\n" + "🤖"*20)
    print("   AI-ARV AGENT: TRỢ LÝ DỰNG PHIM THÔNG MINH")
    print("🤖"*20 + "\n")

    print("AI: Chào chủ nhân! Tôi đã sẵn sàng. Bạn muốn làm video từ đâu? (Nhập link hoặc đường dẫn file)")
    
    # Vòng lặp chính của Agent
    while True:
        try:
            user_input = input("\nBạn: ").strip()
            if not user_input:
                continue
                
            if user_input.lower() in ['exit', 'quit', 'q', 'dừng', 'thoát', 'stop']:
                print("AI: Tạm biệt chủ nhân! Hẹn gặp lại.")
                break

            ai_data = agent.chat(user_input)
            
            if ai_data.get("intent") == "stop_program":
                print(f"AI: {ai_data['response']}")
                break
                
            # Kiểm tra xem người dùng có muốn render trước không
            if ai_data.get("intent") == "start_render" or user_input.lower() in ['render', 'render now', 'bắt đầu đi']:
                if not (config.WORK_DIR / "source.mp4").exists():
                    print("AI: Chủ nhân ơi, tôi chưa có video đầu vào để render. Hãy cho tôi link hoặc path video trước nhé!")
                else:
                    run_render_flow()
                continue

            # Xử lý video đầu vào (chỉ chạy khi intent là process_video hoặc có đường dẫn mới)
            video_input = ai_data.get("params", {}).get("video_path")
            
            # Nếu AI không trích xuất được video_path nhưng user_input có vẻ là một đường dẫn/link
            if not video_input:
                potential_path = user_input.strip("'\" ")
                if potential_path.startswith("http") or (os.path.exists(potential_path) and potential_path.lower().endswith(('.mp4', '.mkv', '.avi', '.mov'))):
                    video_input = potential_path

            if video_input:
                video_input_str = str(video_input).strip("'\" ")
                is_video_input = False
                video_path = None
                
                if video_input_str.startswith("http"):
                    is_video_input = True
                    print(f"AI: Đang tải video từ URL: {video_input_str} ...")
                    try:
                        video_path = download_video(video_input_str)
                    except Exception as e:
                        print(f"AI: Lỗi khi tải video: {e}")
                        continue
                elif os.path.exists(video_input_str) and video_input_str.lower().endswith(('.mp4', '.mkv', '.avi', '.mov')):
                    is_video_input = True
                    video_path_orig = Path(video_input_str).resolve()
                    dest_path = config.WORK_DIR / "source.mp4"
                    
                    if not is_valid_video(video_path_orig):
                        print(f"AI: ❌ File video gốc có vẻ bị lỗi (moov atom not found hoặc không hợp lệ).")
                        continue

                    if video_path_orig != dest_path: 
                        print(f"AI: Đang sao chép video vào bộ nhớ tạm...")
                        if dest_path.exists():
                            dest_path.unlink()
                        shutil.copy2(video_path_orig, dest_path)
                    video_path = dest_path

                if is_video_input and video_path:
                    print(f"\nAI: Đã nhận video. Đang phân tích phim và soạn kịch bản nháp...")
                    try:
                        if config.TEMP_DIR.exists():
                            shutil.rmtree(config.TEMP_DIR)
                        config.TEMP_DIR.mkdir(parents=True, exist_ok=True)
                        
                        scenes = detect_scenes(video_path)
                        transcript = transcribe_video(video_path)
                        draft_path = config.WORK_DIR / "script_draft.json"
                        generate_script(transcript, scenes, draft_path, video_path=video_path)
                        
                        print(f"AI: Phân tích xong! Kịch bản nháp đã sẵn sàng tại {draft_path}.")
                        print("AI: Bạn có muốn chỉnh sửa gì không, hay gõ 'render' để tôi bắt đầu dựng phim?")
                    except Exception as e:
                        print(f"AI: ❌ Có lỗi xảy ra trong quá trình phân tích video: {e}")
                    continue

            # Nếu không phải lệnh render hay video mới, trả lời chat bình thường
            print(f"AI: {ai_data['response']}")
            
        except KeyboardInterrupt:
            print("\nAI: Tạm biệt chủ nhân!")
            break
        except Exception as e:
            print(f"AI: ⚠️ Lỗi hệ thống: {e}")
            continue


def run_render_flow():
    print("\n🎨 AI: Bắt đầu quá trình dựng phim (Render)...")
    final_path = config.WORK_DIR / "script_final.json"
    draft_path = config.WORK_DIR / "script_draft.json"
    
    if not draft_path.exists():
        print("AI: Lỗi: Không tìm thấy kịch bản nháp. Vui lòng cung cấp video trước.")
        return

    # Nếu người dùng chưa tạo file final, tự động dùng file draft
    if not final_path.exists():
        shutil.copy(draft_path, final_path)

    try:
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
    except Exception as e:
        print(f"AI: ❌ Lỗi khi render: {e}")


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
        pass

if __name__ == "__main__":
    main()
