import time
import os

def call_api_with_retry(api_func, *args, **kwargs):
    """
    Hàm trợ lý gọi API (Groq/OpenAI/Gemini) chống dính Rate Limit (HTTP 429) hoặc Timeout.
    Tự động chờ đợi lâu hơn và thử lại 3 lần liên tiếp.
    """
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return api_func(*args, **kwargs)
        except Exception as e:
            err_msg = str(e).lower()
            if "429" in err_msg or "rate limit" in err_msg or "quota" in err_msg:
                wait_time = 5 * (attempt + 1)
                print(f"⚠️ Gặp lỗi quá tải API (Rate Limit). Tự động chờ {wait_time}s rồi thực hiện lại...")
                time.sleep(wait_time)
            else:
                # Nếu là các lỗi cú pháp hoặc API key không tồn tại -> Báo lỗi lập tức
                print(f"❌ Gặp lỗi API nghiêm trọng: {e}")
                raise e
                
    raise RuntimeError("❌ Đã thử lại 3 lần nhưng API vẫn tiếp tục từ chối phản hồi.")
