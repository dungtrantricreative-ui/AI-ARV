"""
sync_assemble.py — Ghép video + giọng đọc (TTS) + phụ đề + nhạc nền thành
file recap cuối cùng.

CHẾ ĐỘ MẶC ĐỊNH — "single_pass" (kiểu Premiere xuất timeline 1 lượt)
--------------------------------------------------------------------
Đây là chế độ MẶC ĐỊNH (config [render] mode = "single_pass"). Toàn bộ pipeline
chỉ chạy ĐÚNG 1 TIẾN TRÌNH FFMPEG DUY NHẤT, xử lý tuần tự hết timeline giống
cách Premiere export 1 lần: trim từng đoạn khớp với từng dòng lời bình, ghép
lại, trộn audio TTS + nhạc nền, và burn phụ đề (nếu bật) — TẤT CẢ trong cùng
1 lần chạy ffmpeg, source video chỉ bị DECODE 1 LẦN DUY NHẤT và ENCODE 1 LẦN
DUY NHẤT (thay vì cắt-rồi-mux lại làm 2 lần encode như trước khi có phụ đề).

Vì sao đổi sang chế độ này: chế độ cũ (xem "segmented" bên dưới) mở song song
hàng chục tiến trình ffmpeg cùng lúc để cắt từng đoạn — trên máy nhiều nhân
CPU/RAM thì nhanh, nhưng với máy YẾU (ít nhân, ít RAM) việc mở hàng chục tiến
trình ffmpeg đồng thời gây tranh chấp CPU/RAM/đĩa nặng nề, có thể treo máy.
Single-pass chỉ có 1 tiến trình, dùng tài nguyên ổn định, dễ đoán, và NHANH
HƠN tổng thể vì bỏ hẳn được 1 lượt re-encode (không còn "cắt rồi mux" 2 lần).

Vẫn giữ ĐẦY ĐỦ log tiến trình real-time (%, tốc độ, ETA) như bản cũ (dùng lại
_run_ffmpeg_logged), và vẫn giữ NGUYÊN cách tính đồng bộ audio/phụ đề: thời
lượng mỗi đoạn hình vẫn khớp CHÍNH XÁC với thời lượng file audio TTS tương ứng
(seg["duration"]), SRT vẫn được tạo lại từ đúng các mốc thời gian TTS thực tế
(update_srt_with_native_duration) — không có gì thay đổi ở phần đồng bộ.

Nếu tiến trình single-pass lỗi (vd video nguồn hỏng giữa file khiến ffmpeg
dừng đột ngột), hệ thống tự động LÙI VỀ chế độ "segmented" bên dưới để vẫn
ra được video thay vì render thất bại hoàn toàn.

CHẾ ĐỘ DỰ PHÒNG — "segmented" (bản cũ, có thể bật lại qua config)
------------------------------------------------------------------
  Giai đoạn 1 — CẮT SONG SONG: mỗi đoạn video (khớp với 1 dòng lời bình)
    được cắt bằng 1 tiến trình ffmpeg riêng, chạy song song trên nhiều lõi
    CPU (hoặc GPU nếu có). Nếu 1 đoạn lỗi, thử cắt lại; nếu vẫn lỗi, chèn
    khung hình đen đúng thời lượng đó thay vì bỏ đoạn — để âm thanh (lời
    đọc) và hình ảnh KHÔNG bị trôi lệch nhau ở các đoạn phía sau.
  Giai đoạn 2 — GHÉP: nối các đoạn đã cắt bằng concat demuxer (`-c copy`,
    không re-encode) — gần như tức thời vì không phải xử lý pixel nào cả.
  Giai đoạn 3 — TRỘN ÂM THANH + PHỤ ĐỀ: ghép audio TTS + nhạc nền, và CHỈ
    khi cần gắn phụ đề mới re-encode lại phần hình. Nếu tắt phụ đề, video
    được copy thẳng (không nén lại lần 2).
  Phù hợp cho máy nhiều nhân CPU muốn tận dụng tối đa song song hoá, hoặc
  dùng làm phương án dự phòng khi single-pass thất bại.

Toàn bộ đều log tiến trình chi tiết (%, tốc độ, ETA) ra console và vào file
`workdir/render.log` để theo dõi/debug khi render video dài.

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
import logutil


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
        logutil.stage(f"[render] Dùng encoder ép cứng theo config: {forced}")
        return _ENCODER_CACHE

    try:
        test_cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.2",
            "-c:v", "h264_nvenc", "-frames:v", "3", "-f", "null", "-",
        ]
        r = subprocess.run(test_cmd, capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            _ENCODER_CACHE = "h264_nvenc"
            logutil.ok("[render] Phát hiện GPU NVIDIA (NVENC) -> dùng để tăng tốc encode.")
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
#  CHẾ ĐỘ MẶC ĐỊNH — SINGLE-PASS (kiểu Premiere: 1 lượt, tuần tự)
# ============================================================
#
# Ý tưởng: dùng filter `trim` nhiều lần trên CÙNG 1 input gốc [0:v] (ffmpeg
# tự động "split" ngầm khi 1 pad được tham chiếu nhiều lần trong filter
# graph) rồi `concat` lại — nguồn chỉ bị decode tuần tự đúng 1 lượt từ đầu
# đến cuối, mỗi khung hình được "phát" cho đúng nhánh trim đang cần nó rồi
# bị các nhánh khác bỏ qua, nên KHÔNG tốn thêm bộ nhớ hay decode lại nhiều
# lần. Audio TTS + nhạc nền + burn phụ đề được trộn NGAY trong cùng lần
# chạy này -> chỉ 1 lần encode duy nhất cho toàn bộ video.
#
# Toàn bộ filter graph được ghi ra 1 file (-filter_complex_script) thay vì
# truyền thẳng qua tham số dòng lệnh, để tránh giới hạn độ dài command-line
# của hệ điều hành khi phim có hàng trăm dòng thoại.

def _build_single_pass_filter_script(tts_segments, fps, sub_filter, bgm_path, bgm_volume, bgm_loop, total_duration,
                                      source_duration: float = 0.0):
    n = len(tts_segments)
    lines = []

    # --- Nhánh hình: trim từng đoạn từ input gốc [0:v] rồi concat lại ---
    #
    # SỬA LỖI ĐỒNG BỘ QUAN TRỌNG: trước đây mỗi đoạn hình được trim đúng
    # [start, start+duration] mà KHÔNG kiểm tra xem video gốc còn đủ khung
    # hình tới đó hay không. Nếu start+duration vượt quá thời lượng thật của
    # video gốc (thường xảy ra ở những dòng cuối kịch bản, hoặc khi lời TTS
    # của 1 dòng dài hơn phần footage còn lại), nhánh trim đó cho ra 1 đoạn
    # NGẮN HƠN đoạn audio TTS tương ứng của nó. Vì nhánh hình (concat riêng)
    # và nhánh tiếng (concat riêng) được ghép ĐỘC LẬP với nhau, một đoạn hình
    # bị hụt như vậy làm lệch tổng thời lượng hình so với tiếng NGAY TỪ ĐÓ,
    # và lệch này CỘNG DỒN cho mọi đoạn phía sau — tới cuối video, hình đã
    # chạy hết khung (đứng lại ở khung cuối) trong khi tiếng vẫn còn tiếp
    # tục phát, đúng hiện tượng "đứng hình nhưng tiếng vẫn chạy".
    #
    # Cách sửa: LUÔN đảm bảo mỗi nhánh hình xuất ra CHÍNH XÁC bằng thời
    # lượng audio TTS của nó. Nếu footage gốc không đủ (chạy tới hết video
    # gốc), phần THIẾU được bù bằng cách "đóng băng" (lặp lại) khung hình
    # cuối cùng của đoạn đó (filter `tpad`) cho tới khi đủ thời lượng, thay
    # vì để đoạn hình ngắn hơn đoạn tiếng. Điều này triệt tiêu hoàn toàn kiểu
    # lệch cộng dồn nói trên — mọi đoạn hình/tiếng phía sau luôn khớp mốc
    # thời gian tuyệt đối như kịch bản đã định, bất kể đoạn nào đó có bị
    # thiếu footage hay không.
    v_labels = []
    for i, seg in enumerate(tts_segments):
        start = max(seg["start"], 0.0)
        req_dur = max(seg["duration"], 0.05)
        if source_duration and source_duration > 0:
            # Không cho phép bắt đầu trim ở/qua mép cuối video gốc.
            start = min(start, max(source_duration - 0.05, 0.0))
            avail = max(source_duration - start, 0.0)
        else:
            avail = req_dur
        clip_dur = max(min(req_dur, avail), 0.05)
        end = start + clip_dur
        pad = max(0.0, req_dur - clip_dur)

        branch = f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS,fps={fps}"
        if pad > 0.02:
            # Lặp lại khung hình cuối của đoạn trim để bù đủ thời lượng còn
            # thiếu, giữ đoạn hình khớp CHÍNH XÁC thời lượng audio TTS.
            branch += f",tpad=stop_mode=clone:stop_duration={pad:.3f}"
        branch += f"[v{i}]"
        lines.append(branch)
        v_labels.append(f"[v{i}]")
    lines.append("".join(v_labels) + f"concat=n={n}:v=1:a=0[vconcat]")

    # --- Nhánh audio: input 1..n là các file TTS, ghép tuần tự đúng thứ tự ---
    a_labels = []
    for i in range(n):
        lines.append(f"[{i + 1}:a]asplit=1[a{i}]")
        a_labels.append(f"[a{i}]")
    lines.append("".join(a_labels) + f"concat=n={n}:v=0:a=1[a_tts_mix]")

    if bgm_path and os.path.exists(bgm_path):
        bgm_idx = n + 1
        bgm_duration = get_duration(bgm_path)
        if bgm_loop and bgm_duration > 0 and bgm_duration < total_duration:
            lines.append(f"[{bgm_idx}:a]aloop=loop=-1:size=2e9[a_bgm_raw]")
            lines.append(f"[a_bgm_raw]volume={bgm_volume}[a_bgm]")
        else:
            lines.append(f"[{bgm_idx}:a]volume={bgm_volume}[a_bgm]")
        lines.append("[a_tts_mix][a_bgm]amix=inputs=2:duration=first:normalize=0[aout]")
    else:
        lines.append("[a_tts_mix]asplit=1[aout]")

    # --- Phụ đề (nếu bật): burn trực tiếp lên [vconcat] ---
    if sub_filter:
        lines.append(f"[vconcat]{sub_filter}[vfinal]")
        video_out_label = "[vfinal]"
    else:
        video_out_label = "[vconcat]"

    return ";\n".join(lines) + "\n", video_out_label


def _assemble_single_pass(original_video, tts_segments, srt_path, output_video_path, bgm_path, bgm_volume,
                           bgm_loop, no_subs, encoder, crf, preset, fps, total_duration, log_path) -> bool:
    n = len(tts_segments)
    logutil.stage(f"[render] Chế độ single-pass (kiểu Premiere): 1 tiến trình ffmpeg xử lý tuần tự "
                  f"{n} đoạn thoại, tổng thời lượng ~{total_duration / 60:.1f} phút...")

    sub_filter = None
    if not no_subs and os.path.exists(srt_path):
        sub_filter = get_ffmpeg_compatible_subtitles_filter(srt_path)

    source_duration = get_duration(original_video)
    if source_duration <= 0:
        logutil.warn("⚠️ [render] Không đo được thời lượng video gốc — bỏ qua bước bù khung hình cuối "
                      "khi thoại TTS vượt quá footage còn lại (hiếm khi cần, nhưng nếu có thể xảy ra "
                      "lệch đồng bộ ở gần cuối video).")

    filter_script_text, video_out_label = _build_single_pass_filter_script(
        tts_segments, fps, sub_filter, bgm_path, bgm_volume, bgm_loop, total_duration, source_duration,
    )

    filter_script_path = config.TEMP_DIR / "single_pass_filter.txt"
    filter_script_path.write_text(filter_script_text, encoding="utf-8")

    inputs = ["-i", str(original_video)]
    for seg in tts_segments:
        inputs.extend(["-i", seg["audio_path"]])
    if bgm_path and os.path.exists(bgm_path):
        inputs.extend(["-i", str(bgm_path)])

    cmd = ["ffmpeg", "-y"] + inputs + ["-filter_complex_script", str(filter_script_path)]
    cmd += ["-map", video_out_label, "-map", "[aout]"]
    cmd += _encoder_args(encoder, crf, preset)
    cmd += ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output_video_path)]

    stage_label = "Single-pass (trim + ghép + trộn audio" + (" + burn phụ đề" if sub_filter else "") + " + xuất file)"
    ok = _run_ffmpeg_logged(cmd, total_duration, stage_label, log_path)
    if not ok:
        logutil.warn(f"⚠️ [render] Single-pass thất bại. Xem chi tiết tại {log_path}. "
                      f"Đang tự động lùi về chế độ 'segmented' để vẫn ra được video...")
    return ok


# ============================================================
#  CHẾ ĐỘ DỰ PHÒNG — SEGMENTED (bản cũ, 3 giai đoạn)
# ============================================================
#  GIAI ĐOẠN 1 — CẮT SONG SONG
# ============================================================

def _cut_segment(job):
    idx, video_path, start, duration, out_path, encoder, crf, preset, fps, source_duration = job
    start = max(start, 0.0)
    req_dur = max(duration, 0.05)

    # Cùng logic sửa lỗi đồng bộ như ở chế độ single-pass (xem giải thích
    # chi tiết trong _build_single_pass_filter_script): nếu video gốc không
    # còn đủ footage cho tới start+req_dur, KHÔNG để đoạn cắt ra ngắn hơn
    # audio TTS tương ứng — bù phần thiếu bằng cách lặp khung hình cuối
    # (tpad), để mọi đoạn cắt ra LUÔN khớp CHÍNH XÁC thời lượng cần thiết.
    if source_duration and source_duration > 0:
        start = min(start, max(source_duration - 0.05, 0.0))
        avail = max(source_duration - start, 0.0)
    else:
        avail = req_dur
    clip_dur = max(min(req_dur, avail), 0.05)
    pad = max(0.0, req_dur - clip_dur)

    vf = f"fps={fps}"
    if pad > 0.02:
        vf += f",tpad=stop_mode=clone:stop_duration={pad:.3f}"

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}",
        "-i", str(video_path),
        "-t", f"{clip_dur:.3f}",
        "-an",
        "-vf", vf,
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

    source_duration = get_duration(original_video)
    if source_duration <= 0:
        logutil.warn("⚠️ [render] Không đo được thời lượng video gốc — bỏ qua bước bù khung hình cuối "
                      "cho các đoạn cắt vượt quá footage còn lại.")

    jobs = []
    for idx, seg in enumerate(tts_segments):
        out_path = seg_dir / f"seg_{idx:05d}.mp4"
        jobs.append((idx, original_video, seg["start"], seg["duration"], out_path, encoder, crf, preset, fps,
                     source_duration))

    logutil.stage(f"[render] Giai đoạn 1/3: Cắt {n} đoạn video song song ({max_workers} luồng, encoder={encoder})...")
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
                logutil.stage(f"[render] Giai đoạn 1/3: {done_count}/{n} đoạn ({pct:.0f}%) | đã chạy {time.time() - t0:.0f}s")

    with open(log_path, "a", encoding="utf-8") as logf:
        logf.write(f"\n===== Giai đoạn 1 (cắt song song): {n - len(failed)}/{n} thành công trong {time.time() - t0:.1f}s =====\n")
        for idx, err in failed:
            logf.write(f"-- Đoạn {idx} lỗi lần 1:\n{err}\n")

    if failed:
        logutil.warn(f"⚠️ [render] {len(failed)}/{n} đoạn cắt lỗi ở lần 1, đang thử cắt lại tuần tự...")
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
            logutil.warn(f"⚠️ [render] {len(still_failed)} đoạn vẫn lỗi -> chèn khung hình đen đúng thời lượng "
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
    logutil.stage(f"[render] Giai đoạn 2/3: Ghép {len(seg_paths)} đoạn video...")
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
        logutil.err(f"❌ [render] Ghép video lỗi. Chi tiết: {r.stderr[-500:]}")
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
        logutil.err(f"❌ LỖI HỆ THỐNG (Mã: FF-ERR-500). Xem chi tiết đầy đủ tại {log_path}")
    return ok


# ============================================================
#  HÀM CHÍNH
# ============================================================

def assemble_video_and_audio(original_video, srt_path, tts_segments, output_video_path,
                              bgm_path=None, bgm_volume=0.2, bgm_loop=True, no_subs=False):
    if not os.path.exists(original_video):
        logutil.err(f"❌ Lỗi: Không tìm thấy video gốc tại {original_video}")
        return False
    if not tts_segments:
        logutil.err("❌ Lỗi: Không có đoạn audio nào để dựng phim.")
        return False

    update_srt_with_native_duration(srt_path, tts_segments)

    log_path = config.WORK_DIR / "render.log"
    log_path.write_text("", encoding="utf-8")  # log mới mỗi lần render

    encoder = _pick_encoder()
    if encoder == "libx264":
        logutil.warn("⚠️ [render] Không tìm thấy GPU NVIDIA (NVENC) khả dụng -> dùng CPU (libx264), sẽ CHẬM hơn "
              "nhiều cho các phim dài. Nếu máy/dịch vụ bạn đang chạy CÓ GPU NVIDIA nhưng chưa được nhận diện: "
              "kiểm tra đã bật/chọn GPU trong cấu hình môi trường chưa (tuỳ nền tảng: card vật lý cần cài driver "
              "+ CUDA, máy ảo/notebook cloud thường có mục chọn loại phần cứng tăng tốc), rồi chạy lại render. "
              "Không có GPU cũng chạy được bình thường, chỉ là lâu hơn.")
    crf = getattr(config, "RENDER_CRF", 20)
    preset = getattr(config, "RENDER_PRESET", "medium")
    fps = _get_fps(original_video)
    width, height = _get_resolution(original_video)

    total_duration = sum(seg["duration"] for seg in tts_segments)
    n = len(tts_segments)
    t_start = time.time()
    render_mode = (getattr(config, "RENDER_MODE", "single_pass") or "single_pass").lower()
    logutil.ok(f"🎬 [render] Bắt đầu dựng phim: {n} đoạn thoại, tổng thời lượng dự kiến ~{total_duration / 60:.1f} phút, "
          f"encoder={encoder}, crf={crf}, preset={preset}, chế độ={render_mode}. Log chi tiết: {log_path}")

    ok = False
    if render_mode != "segmented":
        ok = _assemble_single_pass(
            original_video, tts_segments, srt_path, output_video_path, bgm_path, bgm_volume, bgm_loop,
            no_subs, encoder, crf, preset, fps, total_duration, log_path,
        )

    if not ok:
        ok = _assemble_segmented(
            original_video, tts_segments, srt_path, output_video_path, bgm_path, bgm_volume, bgm_loop,
            no_subs, encoder, crf, preset, fps, width, height, total_duration, log_path,
        )

    if ok:
        logutil.ok(f"✅ [render] Hoàn tất trong {time.time() - t_start:.0f}s. Log chi tiết tại: {log_path}")
    return ok


def _assemble_segmented(original_video, tts_segments, srt_path, output_video_path, bgm_path, bgm_volume, bgm_loop,
                         no_subs, encoder, crf, preset, fps, width, height, total_duration, log_path) -> bool:
    """Chế độ dự phòng (bản cũ, 3 giai đoạn) — xem docstring đầu file."""
    seg_dir = config.TEMP_DIR / "render_segments"
    if seg_dir.exists():
        shutil.rmtree(seg_dir, ignore_errors=True)
    seg_dir.mkdir(parents=True, exist_ok=True)

    try:
        seg_paths = _cut_all_segments_parallel(
            original_video, tts_segments, seg_dir, encoder, crf, preset, fps, width, height, log_path,
        )
        if not seg_paths:
            logutil.err("❌ [render] Không cắt được đoạn video nào, dừng render.")
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
