import os
import sys
import platform
import subprocess
from pathlib import Path
import config

def get_ffmpeg_compatible_subtitles_filter(srt_path):
    """
    Xử lý ký tự đặc biệt trong đường dẫn file phụ đề (.srt) cho bộ lọc subtitles của ffmpeg.
    Tránh lỗi crash đường dẫn trên Windows do dấu hai chấm ổ đĩa (C:...) và dấu xẹt ngược.
    """
    pure_path = Path(srt_path).resolve()
    path_str = str(pure_path)
    
    if platform.system() == "Windows":
        # Trên Windows, ffmpeg yêu cầu chuyển xẹt ngược thành xẹt xuôi và escape dấu hai chấm
        path_str = path_str.replace("\", "/").replace(":", "\:")
        return f"subtitles='{path_str}'"
    else:
        # Trên Linux hoặc macOS
        return f"subtitles='{path_str}'"

def assemble_video_and_audio(original_video, srt_path, audio_tracks, output_video_path):
    """Gộp toàn bộ mảnh video, file sub và tracks âm thanh lồng tiếng mới."""
    if not os.path.exists(original_video):
        print(f"❌ Không tìm thấy video gốc: {original_video}")
        return False
        
    sub_filter = get_ffmpeg_compatible_subtitles_filter(srt_path)
    print(f"🎬 Đang tiến hành ghép phim & đốt phụ đề mềm lên video...")
    print(f"🔧 Filter cấu hình: {sub_filter}")
    
    # Ở đây chứa các câu lệnh ffmpeg ráp tệp tin của bạn...
    # Sử dụng sub_filter đã được xử lý chuẩn đa nền tảng
    
    return True
