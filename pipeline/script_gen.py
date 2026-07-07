"""
Bước 4: Ghép transcript + scene list, đưa cho Gemini/Gemma sinh kịch bản recap.

QUAN TRỌNG: Mỗi dòng kịch bản output có kèm "ref_start" / "ref_end" —
đây chính là mốc thời gian GỐC trên video mà dòng đó đang kể lại.
Mốc này được giữ nguyên xuyên suốt các bước sau (kể cả khi bạn sửa text
ở bước 5) để bước ghép cuối neo đúng vị trí, không bị lệch cộng dồn.

Output: workdir/script_draft.json — bạn (con người) sẽ mở file này lên
sửa lại "text" theo gu riêng của mình TRƯỚC KHI chạy bước TTS.
"""
import sys
import json
from pathlib import Path

import google.generativeai as genai

sys.path.append(str(Path(__file__).parent.parent))
from config import WORK_DIR, GOOGLE_API_KEY, GEMINI_MODEL

PROMPT_TEMPLATE = """Bạn là biên kịch recap phim tiếng Việt. Dưới đây là transcript gốc
của phim kèm timestamp, và danh sách cảnh (scene) đã được chia sẵn.

Nhiệm vụ: viết lại thành kịch bản RECAP theo mạch thời gian, giọng kể chuyện
tự nhiên, súc tích, giữ đúng trình tự sự kiện. Với MỖI đoạn kịch bản, hãy gán
nó vào khoảng thời gian gốc (ref_start, ref_end) tương ứng với đoạn transcript/scene
mà nó đang tóm tắt — đây là mốc bắt buộc, không được bỏ.

Transcript gốc (start-end: nội dung):
{transcript_block}

Danh sách cảnh (scene_id: start-end):
{scenes_block}

CHỈ trả về JSON, không thêm markdown, không thêm lời dẫn, đúng định dạng:
[
  {{"scene_id": 0, "ref_start": 0.0, "ref_end": 4.2, "text": "..."}},
  ...
]
"""


def _format_transcript(segments: list[dict]) -> str:
    return "\n".join(f'{s["start"]}-{s["end"]}: {s["text"]}' for s in segments)


def _format_scenes(scenes: list[dict]) -> str:
    return "\n".join(f'{s["scene_id"]}: {s["start"]}-{s["end"]}' for s in scenes)


def generate_script(transcript: list[dict], scenes: list[dict]) -> list[dict]:
    if not GOOGLE_API_KEY:
        raise RuntimeError("Thiếu GOOGLE_API_KEY trong file .env")

    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)

    prompt = PROMPT_TEMPLATE.format(
        transcript_block=_format_transcript(transcript),
        scenes_block=_format_scenes(scenes),
    )

    print("[script_gen] Đang gọi model sinh kịch bản...")
    response = model.generate_content(prompt)
    raw = response.text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        script = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Model không trả JSON hợp lệ:\n{raw[:500]}") from e

    out_path = WORK_DIR / "script_draft.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    print(f"[script_gen] {len(script)} dòng kịch bản -> {out_path}")
    print("[script_gen] >>> MỞ FILE NÀY LÊN SỬA THEO GU RIÊNG TRƯỚC KHI CHẠY BƯỚC TTS <<<")
    return script


if __name__ == "__main__":
    transcript = json.load(open(WORK_DIR / "transcript.json", encoding="utf-8"))
    scenes = json.load(open(WORK_DIR / "scenes.json", encoding="utf-8"))
    generate_script(transcript, scenes)
