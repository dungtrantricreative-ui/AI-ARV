"""
Bước 2: Chia video gốc thành danh sách cảnh (scene) theo thời gian.
Trả về list các đoạn [start_sec, end_sec] — dùng làm khung tham chiếu
để AI biết "đây là cảnh nào" khi sinh kịch bản, và để bước ghép cuối
biết nên cắt hình gốc ở đâu.
"""
import sys
import json
from pathlib import Path

from scenedetect import detect, ContentDetector

sys.path.append(str(Path(__file__).parent.parent))
from config import WORK_DIR, SCENE_DETECT_THRESHOLD, MIN_SCENE_LEN_SEC


def detect_scenes(video_path: Path) -> list[dict]:
    """
    Trả về list scene: [{"scene_id": 0, "start": 0.0, "end": 4.2}, ...]
    """
    print(f"[scene_detect] Đang phân tích: {video_path}")
    scene_list = detect(str(video_path), ContentDetector(threshold=SCENE_DETECT_THRESHOLD))

    scenes = []
    for i, (start, end) in enumerate(scene_list):
        start_sec = start.get_seconds()
        end_sec = end.get_seconds()
        if end_sec - start_sec < MIN_SCENE_LEN_SEC:
            # Gộp cảnh quá ngắn vào cảnh trước để tránh vụn
            if scenes:
                scenes[-1]["end"] = end_sec
                continue
        scenes.append({"scene_id": i, "start": round(start_sec, 3), "end": round(end_sec, 3)})

    out_path = WORK_DIR / "scenes.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(scenes, f, ensure_ascii=False, indent=2)

    print(f"[scene_detect] Tìm thấy {len(scenes)} cảnh -> {out_path}")
    return scenes


if __name__ == "__main__":
    video = sys.argv[1] if len(sys.argv) > 1 else str(WORK_DIR / "source.mp4")
    detect_scenes(Path(video))
