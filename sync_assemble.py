import os
import platform
import subprocess
from pathlib import Path
import config


def get_ffmpeg_compatible_subtitles_filter(srt_path):
    pure_path = Path(srt_path).resolve()
    path_str = str(pure_path)
    # Escape dấu nháy đơn và dấu hai chấm trên Windows
    if platform.system() == "Windows":
        path_str = path_str.replace("\\", "/").replace(":", "\\:")
    # Escape dấu nháy đơn trong đường dẫn cho ffmpeg filter
    path_str = path_str.replace("'", "'\\''")
    return f"subtitles='{path_str}'"


def assemble_video_and_audio(original_video, srt_path, tts_segments, output_video_path, keep_bg=False, no_subs=False):
    if not os.path.exists(original_video):
        print(f"❌ Không tìm thấy video gốc: {original_video}")
        return False

    n_tts = len(tts_segments)
    inputs = ["-i", str(original_video)]
    for seg in tts_segments:
        inputs.extend(["-i", seg["audio_path"]])

    # Audio filter: delay từng TTS track rồi mix
    audio_filter = ""
    for i in range(n_tts):
        start_ms = int(tts_segments[i]["start"] * 1000)
        audio_filter += f"[{i+1}:a]adelay={start_ms}|{start_ms}[a{i}];"

    mix_inputs = "".join([f"[a{i}]" for i in range(n_tts)])
    if keep_bg:
        if n_tts > 0:
            audio_filter += f"[0:a]volume=0.2[bg];{mix_inputs}amix=inputs={n_tts}:normalize=0[tts_mix];[bg][tts_mix]amix=inputs=2:normalize=0[final_a]"
        else:
            audio_filter += "[0:a]volume=0.2[final_a]"
    else:
        if n_tts > 0:
            audio_filter += f"{mix_inputs}amix=inputs={n_tts}:normalize=0[final_a]"
        else:
            audio_filter += "anullsrc=r=44100:cl=stereo[final_a]"

    sub_filter = None
    if not no_subs and os.path.exists(srt_path):
        sub_filter = get_ffmpeg_compatible_subtitles_filter(srt_path)

    cmd = ["ffmpeg", "-y"]
    cmd.extend(inputs)

    if sub_filter:
        vf = f"[0:v]{sub_filter}[vout]"
        cmd.extend(["-filter_complex", f"{audio_filter};{vf}"])
        cmd.extend(["-map", "[vout]", "-map", "[final_a]"])
        cmd.extend(["-c:v", "libx264", "-crf", "23", "-preset", "fast", "-c:a", "aac", "-b:a", "192k"])
    else:
        cmd.extend(["-filter_complex", audio_filter])
        cmd.extend(["-map", "0:v", "-map", "[final_a]"])
        cmd.extend(["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"])

    cmd.extend(["-shortest", str(output_video_path)])

    print(f"🎬 Đang ghép video & đốt phụ đề...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ Lỗi ffmpeg:\n{result.stderr[:2000]}")
        return False
    print(f"✅ Xong: {output_video_path}")
    return True
