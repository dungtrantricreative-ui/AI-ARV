import os
import config

def _format_transcript(transcript, max_characters=20000):
    """
    Nén và giới hạn số ký tự của transcript thô trước khi nạp vào LLM.
    Đảm bảo 100% không bao giờ gặp lỗi tràn Context Window của API (Gemini/Groq).
    """
    text_block = ""
    for entry in transcript:
        # Định dạng chuẩn gọn gàng
        text_block += f"[{entry.get('start', 0.0):.1f}-{entry.get('end', 0.0):.1f}]: {entry.get('text', '')}
"
    
    if len(text_block) > max_characters:
        print(f"⚠️ Transcript quá dài ({len(text_block)} ký tự). Đang tiến hành rút gọn thông minh...")
        # Lấy phần đầu và phần cuối quan trọng, lược bỏ phần giữa
        half_limit = max_characters // 2
        text_block = text_block[:half_limit] + "
...[NỘI DUNG LƯỢC BỎ ĐỂ TRÁNH TRÀN BỘ NHỚ KHÔNG GIAN NGỮ CẢNH LLM]...
" + text_block[-half_limit:]
        
    return text_block

def format_scenes_block(scenes):
    """Định dạng gọn nhẹ các mốc phân cảnh video."""
    scenes_block = ""
    for idx, scene in enumerate(scenes):
        scenes_block += f"Cảnh {idx+1}: {scene[0]:.1f}s -> {scene[1]:.1f}s\n"
    return scenes_block
