"""
Sinh file phụ đề .srt từ tts_segments.json — mỗi dòng phụ đề khớp đúng
với khoảng (start, end) tuyệt đối của audio đã sync ở bước TTS.
"""
import json
from pathlib import Path


def _srt_timestamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(segments: list[dict], out_path: Path) -> Path:
    lines = []
    for i, seg in enumerate(segments, start=1):
        lines.append(str(i))
        lines.append(f"{_srt_timestamp(seg['start'])} --> {_srt_timestamp(seg['end'])}")
        lines.append(seg["text"])
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


if __name__ == "__main__":
    import sys
    sys.path.append(str(Path(__file__).parent.parent))
    from config import WORK_DIR

    segments = json.load(open(WORK_DIR / "tts_segments.json", encoding="utf-8"))
    build_srt(segments, WORK_DIR / "recap.srt")
    print(f"[srt] -> {WORK_DIR / 'recap.srt'}")
