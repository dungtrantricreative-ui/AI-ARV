import os
import platform
import subprocess
import json
from pathlib import Path
import config


def get_ffmpeg_compatible_subtitles_filter(srt_path):
    pure_path = Path(srt_path).resolve()
    path_str = str(pure_path)
    if platform.system() == "Windows":
        path_str = path_str.replace("\\", "/").replace(":", "\\:")
    path_str = path_str.replace("'", "'\\''")
    force_style = (
        f"FontSize={config.SRT_FONT_SIZE},"
        f"PrimaryColour={config.SRT_PRIMARY_COLOR},"
        f"OutlineColour={config.SRT_OUTLINE_COLOR},"
        f"Outline={config.SRT_OUTLINE_WIDTH}"
    )
    return f"subtitles='{path_str}':force_style='{force_style}'"


def get_duration(file_path):
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)]
    try:
        return float(subprocess.run(cmd, capture_output=True, text=True).stdout.strip())
    except:
        return 0


def assemble_video_and_audio(original_video, srt_path, tts_segments, output_video_path, bgm_path=None, bgm_volume=0.2, bgm_loop=True, no_subs=False):
    if not os.path.exists(original_video):
        print(f"❌ Lỗi: Không tìm thấy video gốc tại {original_video}")
        return False

    update_srt_with_native_duration(srt_path, tts_segments)

    filter_complex = ""
    v_segments = ""
    a_segments = ""
    
    inputs = ["-i", str(original_video)]
    for i, seg in enumerate(tts_segments):
        inputs.extend(["-i", seg["audio_path"]])
        filter_complex += f"[0:v]trim=start={seg['start']}:duration={seg['duration']},setpts=PTS-STARTPTS[v{i}];"
        filter_complex += f"[{i+1}:a]asplit=1[a{i}];"
        v_segments += f"[v{i}]"
        a_segments += f"[a{i}]"

    n = len(tts_segments)
    if n > 0:
        filter_complex += f"{v_segments}concat=n={n}:v=1:a=0[v_concat];"
        filter_complex += f"{a_segments}concat=n={n}:v=0:a=1[a_tts_mix];"
    else:
        return False

    # Xử lý Nhạc nền (BGM)
    if bgm_path and os.path.exists(bgm_path):
        inputs.extend(["-i", str(bgm_path)])
        bgm_idx = n + 1
        video_duration = sum(seg["duration"] for seg in tts_segments)
        bgm_duration = get_duration(bgm_path)
        
        if bgm_loop and bgm_duration > 0 and bgm_duration < video_duration:
            # Lặp nhạc nền nếu ngắn hơn video
            filter_complex += f"[{bgm_idx}:a]aloop=loop=-1:size=2e9[a_bgm_raw];[a_bgm_raw]volume={bgm_volume}[a_bgm];"
        else:
            filter_complex += f"[{bgm_idx}:a]volume={bgm_volume}[a_bgm];"
        
        filter_complex += f"[a_tts_mix][a_bgm]amix=inputs=2:duration=first:normalize=0[aout]"
    else:
        filter_complex += f"[a_tts_mix]asplit=1[aout]"

    sub_filter = None
    if not no_subs and os.path.exists(srt_path):
        sub_filter = get_ffmpeg_compatible_subtitles_filter(srt_path)

    cmd = ["ffmpeg", "-y"]
    cmd.extend(inputs)
    
    if sub_filter:
        final_filter = f"{filter_complex};[v_concat]{sub_filter}[vfinal]"
        cmd.extend(["-filter_complex", final_filter])
        cmd.extend(["-map", "[vfinal]", "-map", "[aout]"])
    else:
        cmd.extend(["-filter_complex", filter_complex])
        cmd.extend(["-map", "[v_concat]", "-map", "[aout]"])

    cmd.extend(["-c:v", "libx264", "-crf", "23", "-preset", "fast", "-c:a", "aac", "-b:a", "192k"])
    cmd.extend([str(output_video_path)])

    print(f"🎬 Đang dựng phim với nhạc nền và Cut-to-Speech...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        log_path = config.WORK_DIR / "ffmpeg_error.log"
        log_path.write_text(result.stderr, encoding="utf-8")
        # Mã lỗi tượng trưng để Agent giải thích
        print(f"❌ LỖI HỆ THỐNG (Mã: FF-ERR-500). Chi tiết: {result.stderr[-500:]}")
        return False
        
    return True


def update_srt_with_native_duration(srt_path, tts_segments):
    if not os.path.exists(srt_path): return
    def format_srt_time(seconds):
        hrs = int(seconds // 3600); mins = int((seconds % 3600) // 60); secs = int(seconds % 60); msecs = int((seconds % 1) * 1000)
        return f"{hrs:02d}:{mins:02d}:{secs:02d},{msecs:03d}"
    current_time = 0.0; new_lines = []
    for i, seg in enumerate(tts_segments):
        start_str = format_srt_time(current_time); end_str = format_srt_time(current_time + seg["duration"])
        new_lines.extend([f"{i+1}", f"{start_str} --> {end_str}", seg["text"], ""])
        current_time += seg["duration"]
    with open(srt_path, "w", encoding="utf-8") as f: f.write("\n".join(new_lines))
