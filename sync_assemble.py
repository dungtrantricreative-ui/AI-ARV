"""
sync_assemble.py — Ghép video + giọng đọc (TTS) + phụ đề + nhạc nền thành
file recap cuối cùng.

THIẾT KẾ MỚI (so với bản cũ dùng 1 filter_complex khổng lồ cho toàn bộ video):
--------------------------------------------------------------------------
Bản cũ trim từng đoạn video bằng filter `trim=` bên trong MỘT filter_complex
duy nhất rồi concat tất cả trong cùng 1 tiến trình ffmpeg. Với phim dài có
hàng trăm dòng thoại, đó là một filter graph khổng lồ chạy ĐƠN LUỒNG, không
có log tiến trình (chỉ biết kết quả sau khi xong), và một lỗi ở giữa graph
có thể làm hỏng toàn bộ.

Bản này chia render thành 3 giai đoạn, tối ưu cho cả TỐC ĐỘ lẫn CHẤT LƯỢNG:

  Giai đoạn 1 — CẮT SONG SONG: mỗi đoạn video (khớp với 1 dòng lời bình)
    được cắt bằng 1 tiến trình ffmpeg riêng, chạy song song trên nhiều lõi
    CPU (hoặc GPU nếu có). Việc này tận dụng hết phần cứng thay vì 1 luồng
    duy nhất xử lý tuần tự -> nhanh hơn đáng kể trên máy nhiều nhân.
    Nếu 1 đoạn lỗi, thử cắt lại; nếu vẫn lỗi, chèn khung hình đen đúng thời
    lượng đó thay vì bỏ đoạn — để âm thanh (lời đọc) và hình ảnh KHÔNG bị
    trôi lệch nhau ở các đoạn phía sau.

  Giai đoạn 2 — GHÉP: nối các đoạn đã cắt bằng concat demuxer (`-c copy`,
    không re-encode) — gần như tức thời vì không phải xử lý pixel nào cả.

  Giai đoạn 3 — TRỘN ÂM THANH + PHỤ ĐỀ: ghép audio TTS + nhạc nền, và CHỈ
    khi cần gắn phụ đề mới re-encode lại phần hình (vì burn phụ đề bắt
    buộc phải render lại pixel). Nếu tắt phụ đề, video được copy thẳng
    (không nén lại lần 2) -> vừa nhanh vừa giữ nguyên chất lượng gốc từ
    giai đoạn 1.

Toàn bộ 3 giai đoạn đều log tiến trình chi tiết (%, tốc độ, ETA) ra console
và vào file `workdir/render.log` để theo dõi/debug khi render video dài.

GPU: hệ thống tự dò xem máy có NVIDIA NVENC không; nếu có sẽ dùng để tăng
tốc encode, nếu không sẽ dùng libx264 (CPU) như bình thường. Có thể ép cứng
qua config (RENDER_FORCE_ENCODER).
"""
import os
import platform
import subprocess
import shutil
import time
import json
import concurrent.futures
from pathlib import Path

import config


# ============================================================
#  DÒ ENCODER (GPU nếu có, fallback CPU)
# ============================================================

_ENCODER_CACHE = None


def _pick_encoder() -> str:
    global _ENCODER_CACHE
    if _ENCODER_CACHE is not None:
        return _ENCODER_CACHE

    forced = getattr(config, "RENDER_FORCE_ENCODER", "") or ""
    if forced:
        _ENCODER_CACHE = forced
        print(f"[render] Dùng encoder ép cứng theo config: {forced}")
        return _ENCODER_CACHE

    try:
        test_cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.2",
            "-c:v", "h264_nvenc", "-frames:v", "3", "-f", "null", "-",
        ]
        r = subprocess.run(test_cmd, capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            _ENCODER_CACHE = "h264_nvenc"
            print("[render] Phát hiện GPU NVIDIA (NVENC) -> dùng để tăng tốc encode.")
            return _ENCODER_CACHE
    except Exception:
        pass

    _ENCODER_CACHE = "libx264"
    return _ENCODER_CACHE


def _encoder_args(encoder: str, crf: int, preset: str) -> list:
    if encoder == "h264_nvenc":
        # NVENC dùng thang preset p1(nhanh nhất)..p7(chậm nhất/nét nhất) và
        # -cq (chất lượng không đổi) tương đương tinh thần của crf bên x264.
        nvenc_preset = {"veryfast": "p2", "fast": "p3", "medium": "p5", "slow": "p6"}.get(preset, "p5")
        return ["-c:v", "h264_nvenc", "-preset", nvenc_preset, "-rc:v", "vbr", "-cq:v", str(crf), "-b:v", "0"]
    return ["-c:v", "libx264", "-crf", str(crf), "-preset", preset]


# ============================================================
#  TIỆN ÍCH PROBE
# ============================================================

def get_duration(file_path) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)]
    try:
        return float(subprocess.run(cmd, capture_output=True, text=True).stdout.strip())
    except Exception:
        return 0.0


def _get_fps(video_path) -> float:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
           "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
        if "/" in out:
            num, den = out.split("/")
            den_f = float(den)
            return float(num) / den_f if den_f else 25.0
        return float(out) if out else 25.0
    except Exception:
        return 25.0


def _get_resolution(video_path):
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
           "-of", "csv=s=x:p=0", str(video_path)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
        w, h = out.split("x")
        return int(w), int(h)
    except Exception:
        return 1920, 1080


# ============================================================
#  LOG TIẾN TRÌNH REAL-TIME (thay vì chỉ biết kết quả sau khi xong)
# ============================================================

def _run_ffmpeg_logged(cmd: list, total_duration: float, stage_label: str, log_path: Path) -> bool:
    full_cmd = list(cmd) + ["-progress", "pipe:1", "-nostats"]
    with open(log_path, "a", encoding="utf-8") as logf:
        logf.write(f"\n===== {stage_label} ({time.strftime('%H:%M:%S')}) =====\n")
        logf.write("$ " + " ".join(str(c) for c in cmd) + "\n")
        logf.flush()

        proc = subprocess.Popen(full_cmd, stdout=subprocess.PIPE, stderr=logf, text=True, bufsize=1)
        start_t = time.time()
        last_print = 0.0
        out_time = 0.0
        speed_str = "?"
        try:
            for line in proc.stdout:
                line = line.strip()
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                if key in ("out_time_us", "out_time_ms"):
                    try:
                        out_time = int(val) / 1_000_000
                    except ValueError:
                        pass
                elif key == "speed":
                    speed_str = val.strip()
                elif key == "progress":
                    now = time.time()
                    is_end = (val == "end")
                    if is_end or now - last_print >= 2.0:
                        pct = min(100.0, out_time / total_duration * 100) if total_duration > 0 else 0.0
                        wall = now - start_t
                        eta_str = ""
                        try:
                            spd = float(speed_str.rstrip("x"))
                            if spd > 0 and total_duration > 0:
                                remain = max(total_duration - out_time, 0) / spd
                                eta_str = f" | còn ~{remain:.0f}s"
                        except ValueError:
                            pass
                        msg = (f"[render] {stage_label}: {pct:5.1f}% "
                               f"({out_time:.1f}s/{total_duration:.1f}s) tốc độ={speed_str}{eta_str} "
                               f"| đã chạy {wall:.0f}s")
                        print(msg)
                        logf.write(msg + "\n")
                        logf.flush()
                        last_print = now
                    if is_end:
                        break
        finally:
            proc.wait()

        ok = proc.returncode == 0
        logf.write(f"===== {stage_label}: {'OK' if ok else 'THẤT BẠI (mã ' + str(proc.returncode) + ')'} =====\n")
        return ok


# ============================================================
#  GIAI ĐOẠN 1 — CẮT SONG SONG
# ============================================================

def _cut_segment(job):
    idx, video_path, start, duration, out_path, encoder, crf, preset, fps = job
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{max(start, 0):.3f}",
        "-i", str(video_path),
        "-t", f"{max(duration, 0.05):.3f}",
        "-an",
        "-vf", f"fps={fps}",
        "-pix_fmt", "yuv420p",
    ] + _encoder_args(encoder, crf, preset) + [
        "-movflags", "+faststart",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    ok = result.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0
    return idx, ok, ("" if ok else result.stderr[-800:])


def _make_filler_segment(duration, out_path, encoder, crf, preset, fps, width, height):
    """Chèn khung hình đen đúng thời lượng khi không cắt được đoạn video
    gốc — ưu tiên giữ đồng bộ audio/hình cho các đoạn phía sau hơn là bỏ
    hẳn đoạn (bỏ đoạn sẽ làm lệch toàn bộ timeline từ đó về sau)."""
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"color=c=black:s={width}x{height}:d={max(duration, 0.05):.3f}:r={fps}",
        "-pix_fmt", "yuv420p",
    ] + _encoder_args(encoder, crf, preset) + [str(out_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0 and out_path.exists()


def _cut_all_segments_parallel(original_video, tts_segments, seg_dir, encoder, crf, preset, fps, width, height, log_path):
    n = len(tts_segments)
    max_workers = getattr(config, "RENDER_MAX_WORKERS", 0) or min(32, (os.cpu_count() or 4))
    if encoder == "h264_nvenc":
        # NVENC giới hạn số phiên encode đồng thời trên nhiều GPU tiêu dùng.
        max_workers = min(max_workers, 3)

    jobs = []
    for idx, seg in enumerate(tts_segments):
        out_path = seg_dir / f"seg_{idx:05d}.mp4"
        jobs.append((idx, original_video, seg["start"], seg["duration"], out_path, encoder, crf, preset, fps))

    print(f"[render] Giai đoạn 1/3: Cắt {n} đoạn video song song ({max_workers} luồng, encoder={encoder})...")
    t0 = time.time()
    failed = []
    done_count = 0
    step = max(1, n // 10)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_cut_segment, job): job[0] for job in jobs}
        for fut in concurrent.futures.as_completed(futures):
            idx, ok, err = fut.result()
            done_count += 1
            if not ok:
                failed.append((idx, err))
            if done_count % step == 0 or done_count == n:
                pct = done_count / n * 100
                print(f"[render] Giai đoạn 1/3: {done_count}/{n} đoạn ({pct:.0f}%) | đã chạy {time.time() - t0:.0f}s")

    with open(log_path, "a", encoding="utf-8") as logf:
        logf.write(f"\n===== Giai đoạn 1 (cắt song song): {n - len(failed)}/{n} thành công trong {time.time() - t0:.1f}s =====\n")
        for idx, err in failed:
            logf.write(f"-- Đoạn {idx} lỗi lần 1:\n{err}\n")

    if failed:
        print(f"⚠️ [render] {len(failed)}/{n} đoạn cắt lỗi ở lần 1, đang thử cắt lại tuần tự...")
        still_failed = []
        for idx, _ in failed:
            job = jobs[idx]
            _, ok, err = _cut_segment(job)
            if not ok:
                still_failed.append((idx, err))
        if still_failed:
            with open(log_path, "a", encoding="utf-8") as logf:
                for idx, err in still_failed:
                    logf.write(f"-- Đoạn {idx} vẫn lỗi sau khi thử lại, chèn khung hình đen thay thế:\n{err}\n")
            print(f"⚠️ [render] {len(still_failed)} đoạn vẫn lỗi -> chèn khung hình đen đúng thời lượng "
                  f"để giữ đồng bộ audio/hình (xem chi tiết tại {log_path}).")
            for idx, _ in still_failed:
                seg = tts_segments[idx]
                out_path = seg_dir / f"seg_{idx:05d}.mp4"
                _make_filler_segment(seg["duration"], out_path, encoder, crf, preset, fps, width, height)

    seg_paths = [seg_dir / f"seg_{idx:05d}.mp4" for idx in range(n)]
    seg_paths = [p for p in seg_paths if p.exists() and p.stat().st_size > 0]
    return seg_paths


# ============================================================
#  GIAI ĐOẠN 2 — GHÉP (concat demuxer, không re-encode -> rất nhanh)
# ============================================================

def _concat_segments(seg_paths, seg_dir, log_path) -> Path:
    print(f"[render] Giai đoạn 2/3: Ghép {len(seg_paths)} đoạn video...")
    concat_list = seg_dir / "concat_list.txt"
    with open(concat_list, "w", encoding="utf-8") as f:
        for p in seg_paths:
            f.write(f"file '{p.resolve().as_posix()}'\n")
    v_concat_path = seg_dir / "v_concat.mp4"
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(v_concat_path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    with open(log_path, "a", encoding="utf-8") as logf:
        logf.write(f"\n===== Giai đoạn 2 (ghép video): {'OK' if r.returncode == 0 else 'LỖI'} =====\n")
        if r.returncode != 0:
            logf.write(r.stderr[-2000:] + "\n")
    if r.returncode != 0 or not v_concat_path.exists():
        print(f"❌ [render] Ghép video lỗi. Chi tiết: {r.stderr[-500:]}")
        return None
    return v_concat_path


# ============================================================
#  GIAI ĐOẠN 3 — TRỘN ÂM THANH + PHỤ ĐỀ + XUẤT FILE CUỐI
# ============================================================

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


def _final_mux(v_concat_path, tts_segments, srt_path, output_video_path, bgm_path, bgm_volume, bgm_loop,
               no_subs, encoder, crf, preset, total_duration, log_path):
    inputs = ["-i", str(v_concat_path)]
    filter_complex = ""
    a_segments = ""
    n = len(tts_segments)
    for i, seg in enumerate(tts_segments):
        inputs.extend(["-i", seg["audio_path"]])
        filter_complex += f"[{i + 1}:a]asplit=1[a{i}];"
        a_segments += f"[a{i}]"
    filter_complex += f"{a_segments}concat=n={n}:v=0:a=1[a_tts_mix];"

    if bgm_path and os.path.exists(bgm_path):
        inputs.extend(["-i", str(bgm_path)])
        bgm_idx = n + 1
        bgm_duration = get_duration(bgm_path)
        if bgm_loop and bgm_duration > 0 and bgm_duration < total_duration:
            filter_complex += f"[{bgm_idx}:a]aloop=loop=-1:size=2e9[a_bgm_raw];[a_bgm_raw]volume={bgm_volume}[a_bgm];"
        else:
            filter_complex += f"[{bgm_idx}:a]volume={bgm_volume}[a_bgm];"
        filter_complex += f"[a_tts_mix][a_bgm]amix=inputs=2:duration=first:normalize=0[aout]"
    else:
        filter_complex += f"[a_tts_mix]asplit=1[aout]"

    sub_filter = None
    if not no_subs and os.path.exists(srt_path):
        sub_filter = get_ffmpeg_compatible_subtitles_filter(srt_path)

    cmd = ["ffmpeg", "-y"] + inputs

    if sub_filter:
        # Cần re-encode vì phải burn phụ đề vào pixel.
        final_filter = f"{filter_complex};[0:v]{sub_filter}[vfinal]"
        cmd += ["-filter_complex", final_filter, "-map", "[vfinal]", "-map", "[aout]"]
        cmd += _encoder_args(encoder, crf, preset)
        stage_label = "Giai đoạn 3/3 (trộn âm thanh + burn phụ đề + xuất file)"
    else:
        # Không phụ đề -> copy thẳng luồng hình từ giai đoạn 1 (không nén lại
        # lần 2), chỉ xử lý audio. Nhanh hơn nhiều và giữ nguyên chất lượng.
        cmd += ["-filter_complex", filter_complex, "-map", "0:v", "-map", "[aout]"]
        cmd += ["-c:v", "copy"]
        stage_label = "Giai đoạn 3/3 (trộn âm thanh + xuất file)"

    cmd += ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output_video_path)]

    ok = _run_ffmpeg_logged(cmd, total_duration, stage_label, log_path)
    if not ok:
        print(f"❌ LỖI HỆ THỐNG (Mã: FF-ERR-500). Xem chi tiết đầy đủ tại {log_path}")
    return ok


# ============================================================
#  HÀM CHÍNH
# ============================================================

def assemble_video_and_audio(original_video, srt_path, tts_segments, output_video_path,
                              bgm_path=None, bgm_volume=0.2, bgm_loop=True, no_subs=False):
    if not os.path.exists(original_video):
        print(f"❌ Lỗi: Không tìm thấy video gốc tại {original_video}")
        return False
    if not tts_segments:
        print("❌ Lỗi: Không có đoạn audio nào để dựng phim.")
        return False

    update_srt_with_native_duration(srt_path, tts_segments)

    log_path = config.WORK_DIR / "render.log"
    log_path.write_text("", encoding="utf-8")  # log mới mỗi lần render

    encoder = _pick_encoder()
    if encoder == "libx264":
        print("⚠️ [render] Không tìm thấy GPU NVIDIA (NVENC) -> dùng CPU (libx264), sẽ CHẬM hơn nhiều "
              "cho các phim dài. Nếu đang chạy trên Google Colab: Runtime -> Change runtime type -> "
              "Hardware accelerator = GPU (T4), rồi chạy lại render để tự động dùng GPU.")
    crf = getattr(config, "RENDER_CRF", 20)
    preset = getattr(config, "RENDER_PRESET", "medium")
    fps = _get_fps(original_video)
    width, height = _get_resolution(original_video)

    total_duration = sum(seg["duration"] for seg in tts_segments)
    n = len(tts_segments)
    t_start = time.time()
    print(f"🎬 [render] Bắt đầu dựng phim: {n} đoạn thoại, tổng thời lượng dự kiến ~{total_duration / 60:.1f} phút, "
          f"encoder={encoder}, crf={crf}, preset={preset}. Log chi tiết: {log_path}")

    seg_dir = config.TEMP_DIR / "render_segments"
    if seg_dir.exists():
        shutil.rmtree(seg_dir, ignore_errors=True)
    seg_dir.mkdir(parents=True, exist_ok=True)

    try:
        seg_paths = _cut_all_segments_parallel(
            original_video, tts_segments, seg_dir, encoder, crf, preset, fps, width, height, log_path,
        )
        if not seg_paths:
            print("❌ [render] Không cắt được đoạn video nào, dừng render.")
            return False

        v_concat_path = _concat_segments(seg_paths, seg_dir, log_path)
        if v_concat_path is None:
            return False

        ok = _final_mux(
            v_concat_path, tts_segments, srt_path, output_video_path, bgm_path, bgm_volume, bgm_loop,
            no_subs, encoder, crf, preset, total_duration, log_path,
        )
    finally:
        shutil.rmtree(seg_dir, ignore_errors=True)

    if ok:
        print(f"✅ [render] Hoàn tất trong {time.time() - t_start:.0f}s. Log chi tiết tại: {log_path}")
    return ok


def update_srt_with_native_duration(srt_path, tts_segments):
    if not os.path.exists(srt_path):
        return

    def format_srt_time(seconds):
        hrs = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        msecs = int((seconds % 1) * 1000)
        return f"{hrs:02d}:{mins:02d}:{secs:02d},{msecs:03d}"

    current_time = 0.0
    new_lines = []
    for i, seg in enumerate(tts_segments):
        start_str = format_srt_time(current_time)
        end_str = format_srt_time(current_time + seg["duration"])
        new_lines.extend([f"{i + 1}", f"{start_str} --> {end_str}", seg["text"], ""])
        current_time += seg["duration"]
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines))
