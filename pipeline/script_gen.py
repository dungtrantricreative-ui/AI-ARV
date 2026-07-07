"""
Bước 4: Sinh kịch bản recap dùng LLM.
Hỗ trợ nhiều dịch vụ (Google Gemini, OpenAI, Groq).
"""
import sys
import json
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from config import WORK_DIR, LLM_PROVIDER, LLM_API_KEY, LLM_MODEL, LLM_BASE_URL

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
    if not LLM_API_KEY:
        raise RuntimeError(f"Thiếu API key cho {LLM_PROVIDER} LLM - hãy đặt LLM_API_KEY hoặc key theo provider trong .env")

    print(f"[script_gen] Dùng {LLM_PROVIDER} LLM, model: {LLM_MODEL}")
    if LLM_BASE_URL:
        print(f"[script_gen] Base URL: {LLM_BASE_URL}")

    prompt = PROMPT_TEMPLATE.format(
        transcript_block=_format_transcript(transcript),
        scenes_block=_format_scenes(scenes),
    )

    provider = LLM_PROVIDER.strip().lower()
    if provider == "google":
        raw = _call_google_llm(prompt)
    elif provider == "openai":
        raw = _call_openai_llm(prompt)
    elif provider == "groq":
        raw = _call_groq_llm(prompt)
    else:
        raise ValueError(f"Không hỗ trợ LLM provider: {LLM_PROVIDER}")

    raw = raw.strip().replace("```json", "").replace("```", "").strip()
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


def _call_google_llm(prompt: str) -> str:
    import google.generativeai as genai

    genai.configure(api_key=LLM_API_KEY)
    model = genai.GenerativeModel(LLM_MODEL)
    response = model.generate_content(prompt)
    return response.text


def _call_openai_llm(prompt: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL or None)
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""


def _call_groq_llm(prompt: str) -> str:
    from groq import Groq

    client = Groq(api_key=LLM_API_KEY)
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""


if __name__ == "__main__":
    transcript = json.load(open(WORK_DIR / "transcript.json", encoding="utf-8"))
    scenes = json.load(open(WORK_DIR / "scenes.json", encoding="utf-8"))
    generate_script(transcript, scenes)
