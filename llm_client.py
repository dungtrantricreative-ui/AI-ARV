"""
llm_client.py — Lớp gọi LLM dùng chung cho toàn bộ pipeline (text + vision).

Trước đây script_gen.py tự cài đặt riêng _call_google/_call_groq/_call_openai
chỉ cho việc sinh kịch bản từ transcript. File này tổng quát hoá lại để cả
script_gen.py (text) và director.py (xác nhận + vision) đều dùng chung 1 nơi,
tránh lặp code và đảm bảo cùng 1 cơ chế retry/backoff cho mọi lời gọi API.
"""
import base64
import json
import mimetypes
import re
import time


def extract_json(text: str):
    """Trích JSON array từ phản hồi LLM, chịu lỗi tốt hơn parse trực tiếp
    (LLM hay chèn thêm text giải thích dù đã dặn không làm vậy)."""
    match = re.search(r'\[\s*\{.*\}\s*\]', text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        return [json.loads(match.group(0))]
    raise ValueError("Không tìm thấy JSON trong phản hồi LLM.")


def extract_json_object(text: str) -> dict:
    """Trích 1 JSON object (không phải array) từ phản hồi LLM."""
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        raise ValueError("Không tìm thấy JSON object trong phản hồi LLM.")
    return json.loads(match.group(0))


def call_with_retry(fn, max_retries=3, base_wait=5, label="llm"):
    last_err = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            transient = any(k in msg for k in ("429", "rate limit", "quota", "overloaded", "503", "timeout"))
            if transient and attempt < max_retries - 1:
                wait = base_wait * (attempt + 1)
                print(f"⚠️ [{label}] Lỗi tạm thời, chờ {wait}s rồi thử lại ({attempt + 1}/{max_retries})...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError(f"[{label}] API từ chối sau {max_retries} lần thử: {last_err}")


# ------------------------- TEXT -------------------------

def call_text(prompt, provider, model, api_key, base_url=None, temperature=0.7, label="llm-text"):
    provider = (provider or "").lower()
    if provider == "google":
        return _call_google_text(prompt, model, api_key, label)
    elif provider == "groq":
        return _call_groq_text(prompt, model, api_key, temperature, label)
    elif provider == "openai":
        return _call_openai_text(prompt, model, api_key, base_url, temperature, label)
    raise ValueError(f"LLM provider không hỗ trợ: {provider}")


def _call_google_text(prompt, model, api_key, label):
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    m = genai.GenerativeModel(model)

    def _do():
        return m.generate_content(prompt).text
    return call_with_retry(_do, label=label)


def _call_groq_text(prompt, model, api_key, temperature, label):
    from groq import Groq
    client = Groq(api_key=api_key)

    def _do():
        resp = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}], temperature=temperature
        )
        return resp.choices[0].message.content
    return call_with_retry(_do, label=label)


def _call_openai_text(prompt, model, api_key, base_url, temperature, label):
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)

    def _do():
        resp = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}], temperature=temperature
        )
        return resp.choices[0].message.content
    return call_with_retry(_do, label=label)


# ------------------------- VISION -------------------------

def _image_to_data_uri(path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def call_vision(prompt, image_paths, provider, model, api_key, base_url=None, temperature=0.5, label="llm-vision"):
    """Gọi model đa phương thức (ảnh + text). Hỗ trợ:
    - provider = "openai" (chuẩn OpenAI Chat Completions image_url data-URI —
      dùng được với Cerebras/gemma-4-31b, OpenAI GPT-4o/GPT-4.1, OpenRouter...)
    - provider = "google" (Gemini/Gemma qua google-generativeai, nhận PIL.Image)
    """
    provider = (provider or "").lower()
    if provider == "openai":
        return _call_openai_vision(prompt, image_paths, model, api_key, base_url, temperature, label)
    elif provider == "google":
        return _call_google_vision(prompt, image_paths, model, api_key, label)
    raise ValueError(
        f"Vision provider chưa hỗ trợ: {provider} "
        f"(hiện hỗ trợ 'openai'-compatible như Cerebras, hoặc 'google')."
    )


def _call_openai_vision(prompt, image_paths, model, api_key, base_url, temperature, label):
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)
    content = [{"type": "text", "text": prompt}]
    for p in image_paths:
        content.append({"type": "image_url", "image_url": {"url": _image_to_data_uri(p)}})

    def _do():
        resp = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": content}], temperature=temperature
        )
        return resp.choices[0].message.content
    return call_with_retry(_do, label=label)


def _call_google_vision(prompt, image_paths, model, api_key, label):
    import google.generativeai as genai
    from PIL import Image
    genai.configure(api_key=api_key)
    m = genai.GenerativeModel(model)
    parts = [prompt] + [Image.open(p) for p in image_paths]

    def _do():
        return m.generate_content(parts).text
    return call_with_retry(_do, label=label)
