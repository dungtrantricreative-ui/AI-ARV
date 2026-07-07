"""
Entry point chính của pipeline. Chia làm 2 lệnh vì có checkpoint con người
BẮT BUỘC ở giữa (sửa script trước khi render giọng đọc):

  python main.py prepare "<url video>"
      -> tải video, chia cảnh, phiên âm, sinh script_draft.json

  (bạn mở workdir/script_draft.json, sửa "text" theo gu riêng,
   lưu thành workdir/script_final.json)

  python main.py render
      -> TTS theo script_final.json, neo mốc, ghép video, xuất ra output/

Dùng --force để chạy lại bước dù đã có file kết quả cũ (mặc định sẽ resume,
bỏ qua bước đã xong để đỡ tốn API call khi test).
"""
import sys
import json
import shutil
import argparse
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
from config import WORK_DIR

from pipeline.download import download_video
from pipeline.scene_detect import detect_scenes
from pipeline.transcribe import transcribe
from pipeline.script_gen import generate_script
from pipeline.tts import generate_synced_tts
from pipeline.sync_assemble import assemble_final_video


def cmd_prepare(args):
    video_path = WORK_DIR / "source.mp4"
    if args.force or not video_path.exists():
        video_path = download_video(args.url)
    else:
        print(f"[prepare] Dùng video đã tải: {video_path}")

    scenes_path = WORK_DIR / "scenes.json"
    if args.force or not scenes_path.exists():
        scenes = detect_scenes(video_path)
    else:
        scenes = json.load(open(scenes_path, encoding="utf-8"))
        print(f"[prepare] Dùng scenes đã có ({len(scenes)} cảnh)")

    transcript_path = WORK_DIR / "transcript.json"
    if args.force or not transcript_path.exists():
        transcript = transcribe(video_path)
    else:
        transcript = json.load(open(transcript_path, encoding="utf-8"))
        print(f"[prepare] Dùng transcript đã có ({len(transcript)} đoạn)")

    script_draft_path = WORK_DIR / "script_draft.json"
    if args.force or not script_draft_path.exists():
        generate_script(transcript, scenes)
    else:
        print(f"[prepare] script_draft.json đã tồn tại, không sinh lại (dùng --force nếu muốn)")

    print("\n=== CHECKPOINT ===")
    print(f"Mở file: {script_draft_path}")
    print("Sửa lại nội dung 'text' theo gu riêng của bạn.")
    print(f"Sau khi sửa xong, lưu/đổi tên thành: {WORK_DIR / 'script_final.json'}")
    print("Rồi chạy: python main.py render")


def cmd_render(args):
    script_final_path = WORK_DIR / "script_final.json"
    if not script_final_path.exists():
        print(f"[render] Chưa thấy {script_final_path}.")
        answer = input("Bạn có muốn copy script_draft.json (chưa sửa) để test nhanh không? [y/N] ")
        if answer.lower() == "y":
            shutil.copy(WORK_DIR / "script_draft.json", script_final_path)
        else:
            print("Dừng lại. Hãy sửa script_draft.json rồi lưu thành script_final.json.")
            sys.exit(1)

    script = json.load(open(script_final_path, encoding="utf-8"))

    tts_segments_path = WORK_DIR / "tts_segments.json"
    if args.force or not tts_segments_path.exists():
        segments = generate_synced_tts(script)
    else:
        segments = json.load(open(tts_segments_path, encoding="utf-8"))
        print(f"[render] Dùng tts_segments đã có ({len(segments)} dòng)")

    video_path = WORK_DIR / "source.mp4"
    assemble_final_video(
        video_path,
        segments,
        burn_subtitles=not args.no_subtitles,
        keep_original_audio_bg=args.keep_bg_audio,
    )


def main():
    parser = argparse.ArgumentParser(description="Video recap pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p_prepare = sub.add_parser("prepare", help="Tải video -> chia cảnh -> phiên âm -> sinh script nháp")
    p_prepare.add_argument("url", help="Link video nguồn")
    p_prepare.add_argument("--force", action="store_true", help="Chạy lại từ đầu, bỏ qua cache")
    p_prepare.set_defaults(func=cmd_prepare)

    p_render = sub.add_parser("render", help="TTS -> neo mốc -> ghép video từ script_final.json")
    p_render.add_argument("--force", action="store_true", help="Sinh lại TTS dù đã có cache")
    p_render.add_argument("--no-subtitles", action="store_true", help="Không burn phụ đề vào video")
    p_render.add_argument("--keep-bg-audio", action="store_true", help="Giữ tiếng gốc ở mức nhỏ làm nền")
    p_render.set_defaults(func=cmd_render)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
