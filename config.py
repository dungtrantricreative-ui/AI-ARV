"""
Cấu hình tập trung từ config.toml.
Cho phép đổi provider/model/base_url mà không cần sửa code pipeline.

Ưu tiên đọc API key theo thứ tự:
1. Biến môi trường generic: ASR_API_KEY / LLM_API_KEY
2. Biến môi trường theo provider: GROQ_API_KEY / OPENAI_API_KEY / GOOGLE_API_KEY
3. Giá trị khai báo trong config.toml
"""
import os
from pathlib import Path

from dotenv import load_dotenv

try:
    import tomllib
except ImportError:  # Python < 3.11
    import tomli as tomllib

load_dotenv()

ROOT_DIR = Path(__file__).parent
CONFIG_FILE = ROOT_DIR / "config.toml"

if not CONFIG_FILE.exists():
    raise FileNotFoundError(
        f"Không tìm thấy {CONFIG_FILE}. Hãy tạo file config.toml trước khi chạy."
    )

with open(CONFIG_FILE, "rb") as f:
    CONFIG = tomllib.load(f)


def _section(name: str) -> dict:
    if name not in CONFIG:
        raise KeyError(f"Thiếu section [{name}] trong config.toml")
    return CONFIG[name]


def _provider_env_candidates(provider: str) -> list[str]:
    provider = (provider or "").strip().lower()
    mapping = {
        "groq": ["GROQ_API_KEY"],
        "openai": ["OPENAI_API_KEY"],
        "google": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
    }
    return mapping.get(provider, [])


def _resolve_api_key(service_name: str, provider: str, config_value: str = "") -> str:
    generic_env = f"{service_name.upper()}_API_KEY"
    for env_name in [generic_env, *_provider_env_candidates(provider)]:
        value = os.getenv(env_name)
        if value:
            return value
    return config_value or ""


# ===== ASR SERVICE =====
_ASR = _section("asr_service")
ASR_PROVIDER = _ASR["provider"]
ASR_BASE_URL = _ASR.get("base_url", "")
ASR_MODEL = _ASR["model"]
ASR_API_KEY = _resolve_api_key("asr", ASR_PROVIDER, _ASR.get("api_key", ""))

# ===== LLM SERVICE =====
_LLM = _section("llm_service")
LLM_PROVIDER = _LLM["provider"]
LLM_BASE_URL = _LLM.get("base_url", "")
LLM_MODEL = _LLM["model"]
LLM_API_KEY = _resolve_api_key("llm", LLM_PROVIDER, _LLM.get("api_key", ""))

# ===== TTS SERVICE =====
_TTS = _section("tts_service")
TTS_PROVIDER = _TTS.get("provider", "edge")
TTS_VOICE_VI = _TTS["voice_vi"]

# ===== DIRECTORIES =====
_DIRS = _section("directories")
WORK_DIR = ROOT_DIR / _DIRS.get("work_dir", "workdir")
OUTPUT_DIR = ROOT_DIR / _DIRS.get("output_dir", "output")
WORK_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# ===== PROCESSING =====
_PROCESSING = CONFIG.get("processing", {})
SCENE_DETECT_THRESHOLD = float(_PROCESSING.get("scene_detect_threshold", 27.0))
MIN_SCENE_LEN_SEC = float(_PROCESSING.get("min_scene_len_sec", 2.0))
MAX_TIME_STRETCH_RATIO = float(_PROCESSING.get("max_time_stretch_ratio", 1.5))
MIN_TIME_STRETCH_RATIO = float(_PROCESSING.get("min_time_stretch_ratio", 0.7))
