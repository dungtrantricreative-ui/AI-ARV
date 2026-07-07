"""
Bản CLOUD của pipeline, chạy trên Modal.com — dùng khi bạn muốn xử lý
mà không cần bật máy cá nhân, hoặc muốn chạy hàng loạt.

Vì có checkpoint con người ở giữa (sửa script), workdir được lưu vào
modal.Volume để giữ trạng thái giữa 2 lần gọi `prepare` và `render`
(mỗi lần gọi remote là một container mới, không có ổ đĩa cục bộ tồn tại).

Cài đặt:
    pip install modal
    modal setup                     # đăng nhập, không cần thẻ tín dụng
    modal secret create my-api-keys GROQ_API_KEY=xxx GOOGLE_API_KEY=xxx

Chạy:
    modal run modal_app.py --url "https://youtube.com/..." --step prepare
    # -> sửa script trên máy bạn (tải script_draft.json về bằng modal volume get)
    modal run modal_app.py --step render
    # -> tải video kết quả về bằng modal volume get
"""
import modal

app = modal.App("video-recap-tool")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install(
        "yt-dlp",
        "scenedetect[opencv]",
        "groq",
        "google-generativeai",
        "edge-tts",
        "ffmpeg-python",
        "python-dotenv",
        "pydub",
    )
    .add_local_dir("pipeline", remote_path="/root/pipeline")
    .add_local_file("config.py", remote_path="/root/config.py")
)

# Volume giữ workdir/output giữa các lần gọi remote khác nhau (vì có checkpoint người sửa script)
volume = modal.Volume.from_name("video-recap-workdir", create_if_missing=True)
VOLUME_PATH = "/root/persist"


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("my-api-keys")],
    volumes={VOLUME_PATH: volume},
    timeout=1800,
)
def run_prepare(url: str):
    import sys
    sys.path.insert(0, "/root")
    import config
    config.WORK_DIR = __import__("pathlib").Path(VOLUME_PATH) / "workdir"
    config.WORK_DIR.mkdir(parents=True, exist_ok=True)

    from pipeline.download import download_video
    from pipeline.scene_detect import detect_scenes
    from pipeline.transcribe import transcribe
    from pipeline.script_gen import generate_script

    video_path = download_video(url)
    scenes = detect_scenes(video_path)
    transcript = transcribe(video_path)
    generate_script(transcript, scenes)

    volume.commit()
    print("Xong bước prepare. Dùng `modal volume get video-recap-workdir workdir/script_draft.json .` "
          "để tải script về sửa, rồi upload lại thành script_final.json bằng "
          "`modal volume put video-recap-workdir script_final.json workdir/script_final.json`.")


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("my-api-keys")],
    volumes={VOLUME_PATH: volume},
    timeout=1800,
)
def run_render(burn_subtitles: bool = True, keep_bg_audio: bool = False):
    import sys
    import json
    from pathlib import Path
    sys.path.insert(0, "/root")
    import config
    config.WORK_DIR = Path(VOLUME_PATH) / "workdir"
    config.OUTPUT_DIR = Path(VOLUME_PATH) / "output"
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    from pipeline.tts import generate_synced_tts
    from pipeline.sync_assemble import assemble_final_video

    script = json.load(open(config.WORK_DIR / "script_final.json", encoding="utf-8"))
    segments = generate_synced_tts(script)
    video_path = config.WORK_DIR / "source.mp4"
    assemble_final_video(video_path, segments, burn_subtitles=burn_subtitles, keep_original_audio_bg=keep_bg_audio)

    volume.commit()
    print("Xong. Dùng `modal volume get video-recap-workdir output/recap_final.mp4 .` để tải video về.")


@app.local_entrypoint()
def main(url: str = "", step: str = "prepare"):
    if step == "prepare":
        if not url:
            raise ValueError("Cần --url khi step=prepare")
        run_prepare.remote(url)
    elif step == "render":
        run_render.remote()
    else:
        raise ValueError("step phải là 'prepare' hoặc 'render'")
