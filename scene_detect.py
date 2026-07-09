import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from scenedetect import detect, ContentDetector
    SCENEDETECT_AVAILABLE = True
except ImportError:
    SCENEDETECT_AVAILABLE = False

import config
import logutil


def _get_video_duration(video_path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        out = result.stdout.strip()
        if not out:
            raise ValueError("ffprobe trả về kết quả rỗng (có thể file không phải video hoặc bị lỗi).")
        return float(out)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip() if e.stderr else "Không có thông tin lỗi từ stderr."
        logutil.err(f"❌ Lỗi ffprobe khi đọc duration: {stderr}")
        raise RuntimeError(f"Không thể đọc thông tin video. Hãy đảm bảo file tồn tại và là định dạng video hợp lệ.\nChi tiết: {stderr}")
    except Exception as e:
        logutil.err(f"❌ Lỗi không xác định khi lấy duration: {e}")
        raise


def _build_interval_scenes(video_path: Path, interval: float) -> list[dict]:
    duration = _get_video_duration(video_path)
    scenes = []
    start = 0.0
    scene_id = 0
    while start < duration:
        end = min(start + interval, duration)
        scenes.append({"scene_id": scene_id, "start": round(start, 3), "end": round(end, 3)})
        start = end
        scene_id += 1
    return scenes


def _build_content_scenes(video_path: Path) -> list[dict]:
    if not SCENEDETECT_AVAILABLE:
        raise ImportError("PySceneDetect chưa được cài. Fallback về interval slicing.")
    scene_list = detect(str(video_path), ContentDetector(threshold=config.SCENE_DETECT_THRESHOLD))
    scenes = []
    for start, end in scene_list:
        start_sec = start.get_seconds()
        end_sec = end.get_seconds()
        if end_sec - start_sec < config.MIN_SCENE_LEN_SEC:
            if scenes:
                # Gộp cảnh ngắn vào cảnh liền trước
                scenes[-1]["end"] = end_sec
                continue
        scenes.append({"scene_id": len(scenes), "start": round(start_sec, 3), "end": round(end_sec, 3)})
    return scenes


def _seconds_to_timecode(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    f = int((seconds % 1) * 30)
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def _export_scenes(scenes: list[dict], out_path: Path, fmt: str):
    if fmt == "xml":
        root = ET.Element("xmeml")
        sequence = ET.SubElement(root, "sequence")
        media = ET.SubElement(sequence, "media")
        video = ET.SubElement(media, "video")
        track = ET.SubElement(video, "track")
        for s in scenes:
            clipitem = ET.SubElement(track, "clipitem")
            ET.SubElement(clipitem, "start").text = str(int(s["start"] * 1000))
            ET.SubElement(clipitem, "end").text = str(int(s["end"] * 1000))
            ET.SubElement(clipitem, "name").text = f"Scene_{s['scene_id']}"
        tree = ET.ElementTree(root)
        tree.write(out_path, encoding="utf-8", xml_declaration=True)
    elif fmt == "edl":
        lines = ["TITLE: Generated Scenes", "FCM: NON-DROP FRAME"]
        for s in scenes:
            start_tc = _seconds_to_timecode(s["start"])
            end_tc = _seconds_to_timecode(s["end"])
            lines.append(
                f"{s['scene_id']+1:03d}  AX       V     C        {start_tc} {end_tc} {start_tc} {end_tc}"
            )
        out_path.write_text("\n".join(lines), encoding="utf-8")
    else:  # json
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(scenes, f, ensure_ascii=False, indent=2)


def detect_scenes(video_path: Path) -> list[dict]:
    logutil.stage(f"[scene_detect] Đang phân tích: {video_path}")
    method = config.SCENE_DETECT_METHOD.lower()

    if method == "interval":
        logutil.stage(f"[scene_detect] Mode: Interval Slicing ({config.SCENE_INTERVAL_SECONDS}s) — FFmpeg, không decode video")
        scenes = _build_interval_scenes(video_path, config.SCENE_INTERVAL_SECONDS)
    else:
        logutil.stage(f"[scene_detect] Mode: Content Detection (PySceneDetect)")
        try:
            scenes = _build_content_scenes(video_path)
        except Exception as e:
            logutil.warn(f"⚠️ PySceneDetect lỗi ({e}), fallback về Interval Slicing "
                  f"({config.SCENE_INTERVAL_SECONDS}s/cảnh)")
            scenes = _build_interval_scenes(video_path, config.SCENE_INTERVAL_SECONDS)

    fmt = config.SCENE_OUTPUT_FORMAT.lower()
    ext = {"xml": ".xml", "edl": ".edl"}.get(fmt, ".json")
    out_path = config.WORK_DIR / f"scenes{ext}"
    _export_scenes(scenes, out_path, fmt)
    logutil.stage(f"[scene_detect] Tìm thấy {len(scenes)} cảnh -> {out_path}")
    return scenes
