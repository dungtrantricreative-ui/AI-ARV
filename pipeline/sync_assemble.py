"""
Bước 7: Ghép video gốc (câm tiếng gốc) với các đoạn audio TTS đã time-stretch,
đặt MỖI đoạn vào ĐÚNG vị trí tuyệt đối (start) trên timeline bằng ffmpeg
adelay + amix — giống cách phụ đề hoạt động, không nối chuỗi liên tiếp.
Vì vậy lỗi lệch (nếu có) chỉ giới hạn trong phạm vi từng dòng, không cộng dồn
qua cả phim.
"""
import sys
import subprocess
import json
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from config import WORK_DIR, OUTPUT_DIR
from pipeline.subtitles import build_srt


def assemble_final_video(
    video_path: Path,
    segments: list[dict],
    output_name: str = "recap_final.mp4",
    burn_subtitles: bool = True,
    keep_original_audio_bg: bool = False,
    original_audio_volume: float = 0.08,
) -> Path:
    """
    video_path: video gốc (hình ảnh giữ nguyên).
    segments: output của tts.generate_synced_tts (mỗi dòng có start, end, file).
    keep_original_audio_bg: nếu True, giữ lại tiếng gốc ở mức nhỏ (nhạc nền/hiệu ứng)
        trộn cùng giọng recap thay vì tắt hẳn.
    """
    output_path = OUTPUT_DIR / output_name
    srt_path = WORK_DIR / "recap.srt"
    build_srt(segments, srt_path)

    inputs = ["-i", str(video_path)]
    for seg in segments:
        inputs += ["-i", seg["file"]]

    filter_parts = []
    mix_labels = []

    for i, seg in enumerate(segments):
        audio_idx = i + 1
        delay_ms = int(round(seg["start"] * 1000))
        label = f"a{i}"
        filter_parts.append(f"[{audio_idx}:a]adelay={delay_ms}|{delay_ms}[{label}]")
        mix_labels.append(f"[{label}]")

    if keep_original_audio_bg:
        filter_parts.append(f"[0:a]volume={original_audio_volume}[bg]")
        mix_labels.append("[bg]")

    n_inputs = len(mix_labels)
    if n_inputs == 0:
        filter_parts.append("anullsrc=channel_layout=stereo:sample_rate=44100[aout]")
    elif n_inputs == 1:
        filter_parts.append(f"{mix_labels[0]}anull[aout]")
    else:
        filter_parts.append(
            f"{''.join(mix_labels)}amix=inputs={n_inputs}:normalize=0:dropout_transition=0[aout]"
        )

    video_map = "0:v:0"
    vf_args = []
    if burn_subtitles:
        # subtitles filter cần re-encode video (không dùng được -c:v copy)
        escaped_srt = str(srt_path).replace(":", "\\:")
        filter_parts.append(f"[{video_map}]subtitles='{escaped_srt}'[vout]")
        video_map_out = "[vout]"
    else:
        video_map_out = f"{video_map}"

    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", video_map_out,
        "-map", "[aout]",
    ]
    if burn_subtitles:
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]
    else:
        cmd += ["-c:v", "copy"]
    cmd += ["-c:a", "aac", "-shortest", str(output_path)]

    print("[assemble] Đang render video cuối (có thể mất vài phút)...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg lỗi:\n{result.stderr[-3000:]}")

    print(f"[assemble] Xong -> {output_path}")
    return output_path


if __name__ == "__main__":
    video_path = WORK_DIR / "source.mp4"
    segments = json.load(open(WORK_DIR / "tts_segments.json", encoding="utf-8"))
    assemble_final_video(video_path, segments)
