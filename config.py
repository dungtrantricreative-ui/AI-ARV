"""
Cấu hình trung tâm cho pipeline.
Tạo file .env ở thư mục gốc với nội dung:

    GROQ_API_KEY=xxxx
    GOOGLE_API_KEY=xxxx

Lấy key free tại:
- Groq: https://console.groq.com/keys
- Google AI Studio: https://aistudio.google.com/apikey
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# --- API keys ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# --- Thư mục làm việc ---
ROOT_DIR = Path(__file__).parent
WORK_DIR = ROOT_DIR / "workdir"      # file tạm: video gốc, audio, cảnh
OUTPUT_DIR = ROOT_DIR / "output"     # video recap hoàn chỉnh

WORK_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# --- Model / giọng đọc ---
GROQ_ASR_MODEL = "whisper-large-v3"      # ASR có timestamp theo câu
GEMINI_MODEL = "gemini-2.0-flash-exp"    # đổi thành model Gemma khi có sẵn qua AI Studio
TTS_VOICE_VI = "vi-VN-NamMinhNeural"     # giọng nam VN (edge-tts). Nữ: vi-VN-HoaiMyNeural

# --- Tham số xử lý ---
SCENE_DETECT_THRESHOLD = 27.0   # PySceneDetect ContentDetector threshold
MIN_SCENE_LEN_SEC = 2.0
MAX_TIME_STRETCH_RATIO = 1.5    # atempo giới hạn tự nhiên (0.67x - 1.5x là nghe ổn)
MIN_TIME_STRETCH_RATIO = 0.7
