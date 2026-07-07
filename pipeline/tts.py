import os
import subprocess
import asyncio
import sys
from pathlib import Path
import config

def get_audio_duration(file_path):
    """Lấy thời lượng âm thanh bằng ffprobe. Có bọc chống crash cực kỳ an toàn."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
        return float(out) if out else 0.0
    except (subprocess.CalledProcessError, ValueError) as e:
        print(f"⚠️ Cảnh báo: Không thể phân tích thời lượng file âm thanh {file_path}. Lỗi: {e}")
        return 0.0

def build_atempo_filter(ratio):
    """
    Xây dựng bộ lọc atempo của ffmpeg.
    Giải quyết triệt để vấn đề: atempo chỉ hỗ trợ co giãn trong khoảng [0.5, 2.0].
    Hàm này tự động nối tầng bộ lọc để đạt tỷ lệ không giới hạn (ví dụ: 0.2 hoặc 4.0).
    """
    ratio = max(0.2, min(5.0, ratio)) # Giới hạn tối thiểu 0.2x và tối đa 5.0x để giữ chất lượng tiếng
    
    filters = []
    # Xử lý khi tăng tốc độ > 2.0
    while ratio > 2.0:
        filters.append("atempo=2.0")
        ratio /= 2.0
    # Xử lý khi giảm tốc độ < 0.5
    while ratio < 0.5:
        filters.append("atempo=0.5")
        ratio /= 0.5
    # Thêm tỉ lệ thừa còn lại
    filters.append(f"atempo={ratio:.2f}")
    
    return ",".join(filters)

async def _synth(text, output_path, voice=config.DEFAULT_VOICE):
    """Thực hiện kết nối với dịch vụ Edge-TTS để sinh giọng nói."""
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)

async def safe_synth_with_retry(text, raw_path, max_retries=3):
    """
    Bọc an toàn cho edge-tts tránh lỗi mạng sập ngầm.
    Tự động kích hoạt thử lại theo cấp số nhân (Exponential Backoff).
    """
    for attempt in range(max_retries):
        try:
            await _synth(text, raw_path)
            if os.path.exists(raw_path) and os.path.getsize(raw_path) > 0:
                return # Thành công mỹ mãn
        except Exception as e:
            print(f"⚠️ Cảnh báo: Lỗi kết nối TTS lần {attempt + 1}: {e}")
            if attempt == max_retries - 1:
                raise e # Sập cả 3 lần thì mới báo lỗi
            await asyncio.sleep(2 ** attempt) # Nghỉ 1s, 2s, 4s... trước khi kết nối lại

def process_tts_line(line, idx):
    """Xử lý lồng tiếng và khớp tốc độ cho từng dòng thoại."""
    raw_path = os.path.join(config.TEMP_DIR, f"tts_{idx}_raw.mp3")
    final_path = os.path.join(config.TEMP_DIR, f"tts_{idx}_fit.mp3")
    
    # 1. Sinh file audio thô từ Edge-TTS
    try:
        asyncio.run(safe_synth_with_retry(line["text"], raw_path))
    except Exception as e:
        print(f"❌ Không thể tạo giọng nói cho dòng thoại {idx}: '{line['text']}'. Lỗi: {e}")
        return None

    # 2. Tính toán thời lượng khớp video gốc
    target_duration = line["ref_end"] - line["ref_start"]
    if target_duration <= 0:
        print(f"⚠️ Dòng thoại {idx} có thời lượng yêu cầu không hợp lệ ({target_duration}s). Sử dụng mặc định 2.0s.")
        target_duration = 2.0
        
    actual_duration = get_audio_duration(raw_path)
    if actual_duration == 0:
        actual_duration = 2.0 # Fallback an toàn phòng khi ffprobe lỗi
        
    ratio = actual_duration / target_duration
    print(f"🎤 Line {idx} -> Thời lượng thô: {actual_duration:.2f}s | Đích: {target_duration:.2f}s | Tỷ lệ co giãn: {ratio:.2f}x")
    
    # 3. Tiến hành co giãn âm thanh bằng ffmpeg bộ lọc nối tầng
    atempo_filter = build_atempo_filter(ratio)
    cmd = [
        "ffmpeg", "-y", "-i", raw_path,
        "-filter:a", atempo_filter,
        final_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"⚠️ Lỗi co giãn âm thanh ở dòng thoại {idx}. Chuyển sang dùng âm thanh thô làm dự phòng. Chi tiết: {e.stderr}")
        shutil.copy(raw_path, final_path)
        
    return final_path
