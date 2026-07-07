import json
import re
from pathlib import Path
import config


def _format_transcript(transcript, max_characters=20000):
    text_block = ""
    for entry in transcript:
        text_block += f"[{entry.get('start', 0.0):.1f}-{entry.get('end', 0.0):.1f}]: {entry.get('text', '')}\n"
    if len(text_block) > max_characters:
        print(f"⚠️ Transcript quá dài ({len(text_block)} ký tự). Rút gọn thông minh...")
        half = max_characters // 2
        text_block = text_block[:half] + "\n...[LƯỢC BỎ ĐỂ TRÁNH TRÀN CONTEXT]...\n" + text_block[-half:]
    return text_block


def format_scenes_block(scenes):
    scenes_block = ""
    for idx, scene in enumerate(scenes):
        scenes_block += f"Cảnh {idx+1}: {scene['start']:.1f}s -> {scene['end']:.1f}s\n"
    return scenes_block


def generate_script(transcript, scenes, out_path: Path):
    print("[script_gen] Đang sinh kịch bản nháp...")
    prompt = _build_prompt(transcript, scenes)
    provider = config.LLM_PROVIDER.lower()

    if provider == "google":
        script = _call_google(prompt)
    elif provider == "groq":
        script = _call_groq(prompt)
    elif provider == "openai":
        script = _call_openai(prompt)
    else:
        raise ValueError(f"LLM provider không hỗ trợ: {provider}")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)
    print(f"[script_gen] Xong: {out_path}")
    return script


def _build_prompt(transcript, scenes):
    t_block = _format_transcript(transcript)
    s_block = format_scenes_block(scenes)
    prompt = f"""Bạn là biên kịch tóm tắt phim. Dựa vào transcript và danh sách cảnh dưới đây, hãy viết lại thành kịch bản recap ngắn gọn, hấp dẫn, bằng tiếng Việt.

Transcript:
{t_block}

Danh sách cảnh:
{s_block}

Yêu cầu:
- Trả về JSON array, mỗi phần tử có: ref_start (float), ref_end (float), text (string).
- ref_start/ref_end phải nằm trong khoảng thời gian của một cảnh cụ thể.
- text là lời thoại recap cho cảnh đó, ngắn gọn, có cảm xúc.
- Không giải thích gì thêm, chỉ trả về JSON thuần.

Ví dụ:
[
  {{"ref_start": 0.0, "ref_end": 4.2, "text": "Mở đầu phim, chúng ta thấy một thành phố chìm trong bóng tối..."}}
]
"""
    return prompt


def _extract_json(text):
    # Thử tìm JSON array trước
    match = re.search(r'\[\s*\{.*\}\s*\]', text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    # Thử tìm object đơn
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        return [json.loads(match.group(0))]
    raise ValueError("Không tìm thấy JSON trong phản hồi LLM.")


def _call_google(prompt):
    import google.generativeai as genai
    genai.configure(api_key=config.LLM_API_KEY)
    model = genai.GenerativeModel(config.LLM_MODEL)
    resp = model.generate_content(prompt)
    return _extract_json(resp.text)


def _call_groq(prompt):
    from groq import Groq
    client = Groq(api_key=config.LLM_API_KEY)
    resp = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    return _extract_json(resp.choices[0].message.content)


def _call_openai(prompt):
    from openai import OpenAI
    client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
    resp = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    return _extract_json(resp.choices[0].message.content)
