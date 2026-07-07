import os
import sys
import json
import shutil
from pathlib import Path
import config

def check_dependencies():
    """Kiểm tra sự tồn tại của ffmpeg và ffprobe trên hệ thống trước khi vận hành."""
    for binary in ["ffmpeg", "ffprobe"]:
        if not shutil.which(binary):
            print(f"❌ LỖI NGHIÊM TRỌNG: Không tìm thấy lệnh '{binary}' trong hệ thống của bạn!")
            print("👉 Vui lòng cài đặt ffmpeg và thêm thư mục chứa binary của nó vào biến PATH.")
            print("👉 Trên Windows: Bạn có thể tải từ gyan.dev và cấu hình Environment Variables.")
            print("👉 Trên Linux: Chạy 'sudo apt install ffmpeg'.")
            sys.exit(1)
    print("✅ Kiểm tra hệ thống: Đầy đủ dependencies (ffmpeg, ffprobe).")

def validate_and_load_script(path):
    """Đọc dữ liệu kịch bản JSON và xác minh cấu trúc để tránh lỗi KeyError khi chạy tts."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Không tìm thấy tệp kịch bản tại đường dẫn: {path}")
        
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Tệp JSON kịch bản bị hỏng cấu trúc: {e}")
        
    if not isinstance(data, list):
        raise ValueError("Lỗi cấu trúc: Kịch bản phải là một danh sách các dòng thoại (JSON Array).")
        
    required_keys = {"ref_start", "ref_end", "text"}
    for idx, item in enumerate(data):
        missing = required_keys - item.keys()
        if missing:
            raise KeyError(f"Dòng kịch bản thứ {idx+1} (chỉ số {idx}) bị thiếu các trường thông tin bắt buộc: {missing}")
            
    return data

def main():
    print("=== BẮT ĐẦU PIPELINE AI VIDEO RECAP ===")
    check_dependencies()
    
    script_final_path = os.path.join(config.BASE_DIR, "script_final.json")
    
    try:
        script = validate_and_load_script(script_final_path)
        print(f"✅ Đọc và kiểm định thành công kịch bản JSON! Tổng cộng {len(script)} phân cảnh cần lồng tiếng.")
    except Exception as e:
        print(f"❌ LỖI KHỞI ĐỘNG KỊCH BẢN: {e}")
        sys.exit(1)
        
    # Tiếp tục quá trình pipeline của bạn (transcribe, scene_detect, tts, assemble...)
    print("Môi trường của bạn đã sẵn sàng chạy trơn tru!")

if __name__ == "__main__":
    main()
