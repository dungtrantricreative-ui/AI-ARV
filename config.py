import os
import sys
from pathlib import Path

# Đọc .env nếu có
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).parent.resolve()
WORK_DIR = BASE_DIR / "workdir"
OUTPUT_DIR = BASE_DIR / "output"
TEMP_DIR = BASE_DIR / "temp"

for d in [WORK_DIR, OUTPUT_DIR, TEMP_DIR]:
    d.mkdir(exist_ok=True)

# Đọc config.toml
CONFIG_PATH = BASE_DIR / "config.toml"
config_toml = {}
if CONFIG_PATH.exists():
    if sys.version_info < (3, 11):
        import tomli as tomllib
    else:
        import tomllib
    with open(CONFIG_PATH, "rb") as f:
        config_toml = tomllib.load(f)

def _get(section, key, default):
    return config_toml.get(section, {}).get(key, default)

# ASR
ASR_PROVIDER = _get("asr_service", "provider", "groq")
ASR_BASE_URL = _get("asr_service", "base_url", "https://api.groq.com")
ASR_MODEL = _get("asr_service", "model", "whisper-large-v3")
ASR_API_KEY = _get("asr_service", "api_key", "") or os.getenv("ASR_API_KEY") or os.getenv("GROQ_API_KEY", "")

# LLM
LLM_PROVIDER = _get("llm_service", "provider", "google")
LLM_BASE_URL = _get("llm_service", "base_url", "https://generativelanguage.googleapis.com")
LLM_MODEL = _get("llm_service", "model", "gemini-2.0-flash-exp")
LLM_API_KEY = _get("llm_service", "api_key", "") or os.getenv("LLM_API_KEY") or os.getenv("GOOGLE_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")

# TTS
TTS_PROVIDER = _get("tts_service", "provider", "edge")
DEFAULT_VOICE = _get("tts_service", "voice_vi", "vi-VN-HoaiMyNeural")

# Scene detect
SCENE_DETECT_METHOD = _get("scene_detect", "method", "interval")  # "content" | "interval"
SCENE_DETECT_THRESHOLD = float(_get("scene_detect", "threshold", 27.0))
MIN_SCENE_LEN_SEC = float(_get("scene_detect", "min_duration", 1.5))
MIN_SCENE_DURATION = MIN_SCENE_LEN_SEC
SCENE_INTERVAL_SECONDS = float(_get("scene_detect", "interval_seconds", 5.0))
SCENE_OUTPUT_FORMAT = _get("scene_detect", "output_format", "json")  # "json" | "xml" | "edl"

# TTS audio stretch limits
MIN_TIME_STRETCH_RATIO = 0.5
MAX_TIME_STRETCH_RATIO = 2.0

# Subtitle style
SRT_FONT_SIZE = 16
SRT_PRIMARY_COLOR = "&H00FFFFFF"
SRT_OUTLINE_COLOR = "&H00000000"
SRT_OUTLINE_WIDTH = 2
