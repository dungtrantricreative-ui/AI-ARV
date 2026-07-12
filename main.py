import os
import sys
import json
import shutil
import argparse
import subprocess
from pathlib import Path

import config
import logutil
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
            logutil.err(f"❌ LỖI: Không tìm thấy '{binary}'!")
            sys.exit(1)


def is_valid_video(video_path: Path) -> bool:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode == 0
    except Exception:
        return False


def smart_agent_mode():
    check_dependencies()
    print("\n" + "✨"*20)
    print("   AI-ARV AGENT: NGƯỜI BẠN ĐỒNG HÀNH DỰNG PHIM")
    print("✨"*20 + "\n")

    print("AI: Chào chủ nhân! Tôi đã sẵn sàng rồi đây. Hôm nay chúng ta sẽ cùng tạo nên một siêu phẩm video recap nhé! Bạn đã có video chưa, hay muốn trò chuyện một chút?")
    
    while True:
        try:
            user_input = input("\nBạn: ").strip()
            if not user_input:
                continue
                
            # Gửi yêu cầu cho AI xử lý ý định tự do
            ai_data = agent.chat(user_input)
            
            # 1. Ý định dừng chương trình
            if ai_data.get("intent") == "stop_program":
                print(f"AI: {ai_data['response']}")
                break
                
            # 2. Ý định Render (Được ưu tiên để tránh lặp lại prepare)
            # AI giờ đây tự nhận diện các câu như "lên phim", "xuất xưởng"
            if ai_data.get("intent") == "start_render":
                if not (config.WORK_DIR / "source.mp4").exists():
                    print(f"AI: {ai_data['response']}")
                    print("(Gợi ý: Tôi chưa thấy video đâu cả, bạn gửi cho tôi nhé!)")
                else:
                    print(f"AI: {ai_data['response']}")
                    run_render_flow()
                continue

            # 3. Ý định xử lý Video
            video_input = ai_data.get("params", {}).get("video_path")
            
            # Logic dự phòng nếu AI không trích xuất được params nhưng user_input có path
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
                    print(f"AI: Đang tải video từ URL cho bạn đây...")
                    try:
                        video_path = download_video(video_input_str)
                    except Exception as e:
                        print(f"AI: ôi, có lỗi khi tải video rồi: {e}")
                        continue
                elif os.path.exists(video_input_str) and video_input_str.lower().endswith(('.mp4', '.mkv', '.avi', '.mov')):
                    is_video_input = True
                    video_path_orig = Path(video_input_str).resolve()
                    dest_path = config.WORK_DIR / "source.mp4"
                    
                    if not is_valid_video(video_path_orig):
                        print(f"AI: File video này có vẻ hơi 'mệt' (lỗi moov atom), bạn kiểm tra lại giúp tôi nhé.")
                        continue

                    if video_path_orig != dest_path: 
                        if dest_path.exists(): dest_path.unlink()
                        shutil.copy2(video_path_orig, dest_path)
                    video_path = dest_path

                if is_video_input and video_path:
                    print(f"AI: {ai_data['response']}")
                    print(f"\n[Hệ thống]: Đang bắt đầu quy trình phân tích tự động...")
                    try:
                        if config.TEMP_DIR.exists(): shutil.rmtree(config.TEMP_DIR)
                        config.TEMP_DIR.mkdir(parents=True, exist_ok=True)
                        
                        scenes = detect_scenes(video_path)
                        transcript = transcribe_video(video_path)
                        draft_path = config.WORK_DIR / "script_draft.json"
                        generate_script(transcript, scenes, draft_path, video_path=video_path)
                        
                        print(f"\nAI: Tuyệt quá! Tôi đã phân tích xong phim và soạn sẵn kịch bản tại {draft_path} rồi.")

                        if config.RENDER_AUTO:
                            print("AI: (auto_render đang bật) Tôi render luôn cho bạn nhé, khỏi cần chờ xác nhận!")
                            run_render_flow()
                        else:
                            print("AI: Bạn xem qua kịch bản nhé, nếu ưng ý rồi thì bảo tôi 'lên phim' hay 'render' là xong ngay!")
                    except Exception as e:
                        print(f"AI: ❌ Có chút trục trặc trong lúc phân tích: {e}")
                    continue

            # 4. Trả lời chat bình thường hoặc kết quả Terminal
            print(f"AI: {ai_data['response']}")
            
        except KeyboardInterrupt:
            print("\nAI: Tạm biệt chủ nhân! Chúc bạn một ngày tốt lành.")
            break
        except Exception as e:
            print(f"AI: ⚠️ Có lỗi hệ thống nhỏ: {e}")
            continue


def run_render_flow():
    print("\n🎨 AI: Đang bắt đầu 'phù phép' để xuất phim cho bạn...")
    final_path = config.WORK_DIR / "script_final.json"
    draft_path = config.WORK_DIR / "script_draft.json"
    
    if not draft_path.exists():
        print("AI: Ơ kìa, tôi chưa có kịch bản nháp. Bạn đưa video cho tôi xử lý trước nhé!")
        return

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
            bgm_loop=agent.bgm_loop,
            no_subs=not config.SUBTITLE_ENABLED
        )

        if success:
            print(f"\n🎉 AI: HOÀN THÀNH RỒI! Siêu phẩm của bạn đã sẵn sàng tại: {output_path}")
            print("AI: Bạn xem thử video đi, hy vọng bạn sẽ thích nó!")
        else:
            explanation = agent.report_error("FF-ERR-500", "Lỗi trong quá trình ghép video cuối cùng.")
            print(f"\nAI: {explanation}")
    except Exception as e:
        print(f"AI: ❌ Lỗi khi render: {e}")


def main():
    parser = argparse.ArgumentParser(description="AI-ARV Agent Mode")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("render", help="Render trực tiếp từ script_final.json (hoặc script_draft.json) đã có sẵn.")

    args = parser.parse_args()
    if not args.command:
        smart_agent_mode()
    elif args.command == "render":
        run_render_flow()

if __name__ == "__main__":
    main()
