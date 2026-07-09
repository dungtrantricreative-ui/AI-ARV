import os
import sys
from pathlib import Path

# Đọc .env nếu có
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# BASE_DIR nên là thư mục chứa file config.py này
BASE_DIR = Path(__file__).parent.resolve()

# Đảm bảo các thư mục quan trọng luôn nằm trong BASE_DIR
WORK_DIR = BASE_DIR / "workdir"
OUTPUT_DIR = BASE_DIR / "output"
TEMP_DIR = BASE_DIR / "temp"

for d in [WORK_DIR, OUTPUT_DIR, TEMP_DIR]:
    d.mkdir(parents=True, exist_ok=True)

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


def _resolve_api_key(section, generic_env, provider, provider_env_map):
    key = _get(section, "api_key", "")
    if key:
        return key
    key = os.getenv(generic_env, "")
    if key:
        return key
    env_name = provider_env_map.get(provider.lower())
    if env_name:
        return os.getenv(env_name, "")
    return ""


# ASR
ASR_PROVIDER = _get("asr_service", "provider", "groq")
ASR_BASE_URL = _get("asr_service", "base_url", "https://api.groq.com")
ASR_MODEL = _get("asr_service", "model", "whisper-large-v3")
ASR_API_KEY = _resolve_api_key(
    "asr_service", "ASR_API_KEY", ASR_PROVIDER,
    {"groq": "GROQ_API_KEY", "openai": "OPENAI_API_KEY"}
)

# LLM
LLM_PROVIDER = _get("llm_service", "provider", "google")
LLM_BASE_URL = _get("llm_service", "base_url", "https://generativelanguage.googleapis.com")
LLM_MODEL = _get("llm_service", "model", "gemini-2.0-flash-exp")
LLM_API_KEY = _resolve_api_key(
    "llm_service", "LLM_API_KEY", LLM_PROVIDER,
    {"google": "GOOGLE_API_KEY", "groq": "GROQ_API_KEY", "openai": "OPENAI_API_KEY"}
)

# TTS
TTS_PROVIDER = _get("tts_service", "provider", "edge")
DEFAULT_VOICE = _get("tts_service", "voice_vi", "vi-VN-HoaiMyNeural")
TTS_RATE = _get("tts_service", "rate", "+0%")

# Subtitle toggle (bật/tắt gắn phụ đề khi render)
SUBTITLE_ENABLED = bool(_get("subtitle", "enabled", True))

# Scene detect
SCENE_DETECT_METHOD = _get("scene_detect", "method", "interval")  # "content" | "interval"
SCENE_DETECT_THRESHOLD = float(_get("scene_detect", "threshold", 27.0))
MIN_SCENE_LEN_SEC = float(_get("scene_detect", "min_duration", 1.5))
MIN_SCENE_DURATION = MIN_SCENE_LEN_SEC
SCENE_INTERVAL_SECONDS = float(_get("scene_detect", "interval_seconds", 5.0))
SCENE_OUTPUT_FORMAT = _get("scene_detect", "output_format", "json")  # "json" | "xml" | "edl"

# --- Script polish (bước biên tập lại kịch bản cho mạch lạc, xem script_gen.py) ---
SCRIPT_POLISH_ENABLED = bool(_get("script", "polish_enabled", True))
# Thời lượng video đích (phút), dùng để tính ngân sách lời bình/block.
SCRIPT_TARGET_MINUTES = float(_get("script", "target_minutes", 20.0))

# --- Director ---
DIRECTOR_ENABLED = bool(_get("director", "enabled", True))
DIRECTOR_DENSITY_THRESHOLD = float(_get("director", "density_threshold", 3.0))
DIRECTOR_SILENCE_RATIO_THRESHOLD = float(_get("director", "silence_ratio_threshold", 0.6))
DIRECTOR_MAX_VISION_BLOCK_SEC = float(_get("director", "max_vision_block_seconds", 40.0))
DIRECTOR_MAX_TEXT_BLOCK_SEC = float(_get("director", "max_text_block_seconds", 300.0))
DIRECTOR_FRAMES_PER_BLOCK = int(_get("director", "frames_per_block", 3))
DIRECTOR_FRAME_MAX_WIDTH = int(_get("director", "frame_max_width", 512))
DIRECTOR_CONFIRM_WITH_LLM = bool(_get("director", "confirm_with_llm", True))
DIRECTOR_FORCE_VISION_FIRST_SCENE = bool(_get("director", "force_vision_first_scene", True))
DIRECTOR_MAX_VISION_RATIO = float(_get("director", "max_vision_ratio", 0.35))

# --- Vision service ---
_vision_provider = _get("vision_service", "provider", "")
VISION_PROVIDER = _vision_provider if _vision_provider else LLM_PROVIDER
_vision_base_url = _get("vision_service", "base_url", "")
VISION_BASE_URL = _vision_base_url if _vision_base_url else LLM_BASE_URL
_vision_model = _get("vision_service", "model", "")
VISION_MODEL = _vision_model if _vision_model else LLM_MODEL
_vision_api_key = _get("vision_service", "api_key", "")
if _vision_api_key:
    VISION_API_KEY = _vision_api_key
elif _vision_provider:
    VISION_API_KEY = _resolve_api_key(
        "vision_service", "VISION_API_KEY", VISION_PROVIDER,
        {"google": "GOOGLE_API_KEY", "groq": "GROQ_API_KEY", "openai": "OPENAI_API_KEY"}
    )
else:
    VISION_API_KEY = LLM_API_KEY

# TTS audio stretch limits
MIN_TIME_STRETCH_RATIO = 0.5
MAX_TIME_STRETCH_RATIO = 2.0

# Subtitle style
SRT_FONT_SIZE = 16
SRT_PRIMARY_COLOR = "&H00FFFFFF"
SRT_OUTLINE_COLOR = "&H00000000"
SRT_OUTLINE_WIDTH = 2

# --- Render / xuất video (xem sync_assemble.py) ---
# CRF thấp hơn = chất lượng cao hơn (file nặng hơn). 18-20 gần như lossless
# với mắt thường, phù hợp để đăng YouTube (YouTube sẽ nén lại lần nữa).
RENDER_CRF = int(_get("render", "crf", 20))
# Preset cho libx264 (bỏ qua nếu dùng GPU/NVENC): chậm hơn = nén hiệu quả
# hơn (chất lượng/dung lượng tốt hơn ở cùng crf), nhưng lâu hơn. Vì giờ các
# đoạn được cắt SONG SONG (đa luồng), có thể dùng preset chất lượng cao hơn
# ("medium"/"slow") mà vẫn không chậm hơn bản cũ chạy đơn luồng "fast".
RENDER_PRESET = _get("render", "preset", "medium")
# Số luồng cắt song song ở giai đoạn 1. 0 = tự động (bằng số nhân CPU, tối
# đa 32). Giảm số này nếu máy yếu/ít RAM và bị treo khi render.
RENDER_MAX_WORKERS = int(_get("render", "max_parallel_segments", 0))
# Ép cứng encoder thay vì tự dò GPU: "" (tự dò NVENC, fallback libx264),
# "libx264" (chỉ CPU), hoặc "h264_nvenc" (chỉ GPU NVIDIA).
RENDER_FORCE_ENCODER = _get("render", "force_encoder", "")
