import os

# CẤU HÌNH THƯ MỤC LÀM VIỆC AN TOÀN
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# Đảm bảo các thư mục luôn luôn tồn tại
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# THÔNG SỐ XỬ LÝ VIDEO & SCENE DETECTION
SCENE_DETECT_THRESHOLD = 27.0
MIN_SCENE_DURATION = 1.5

# THÔNG SỐ TTS (AUDIO TIME STRETCH)
MIN_TIME_STRETCH_RATIO = 0.5
MAX_TIME_STRETCH_RATIO = 2.0
DEFAULT_VOICE = "vi-VN-HoaiMyNeural" # Giọng đọc chất lượng cao ổn định của Edge TTS

# CẤU HÌNH PHỤ ĐỀ (SUBTITLE STYLE)
SRT_FONT_SIZE = 16
SRT_PRIMARY_COLOR = "&H00FFFFFF" # Màu trắng
SRT_OUTLINE_COLOR = "&H00000000" # Viền đen
SRT_OUTLINE_WIDTH = 2
