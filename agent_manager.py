import os
import json
import subprocess
import platform
import config
from llm_client import call_text, extract_json_object

class AIAgent:
    def __init__(self):
        self.history = []
        self.bgm_path = None
        self.bgm_volume = 0.2
        self.bgm_loop = True
        self.os_name = platform.system()

    def chat(self, user_input):
        """Xử lý hội thoại tự nhiên, linh hoạt, không bị gò bó bởi từ khóa."""
        
        history_str = ""
        for msg in self.history[-8:]: # Tăng context lên 8 câu để hiểu sâu hơn
            history_str += f"{msg['role']}: {msg['content']}\n"

        # Prompt được thiết kế để AI tự do hơn trong cách trả lời nhưng vẫn giữ được logic xử lý
        prompt = f"""
Bạn là một trợ lý AI chuyên nghiệp nhưng cực kỳ thân thiện và tâm lý, tên là AI-ARV. 
Nhiệm vụ của bạn là đồng hành cùng chủ nhân trong việc dựng phim recap.
Hệ điều hành hiện tại: {self.os_name}

PHONG CÁCH TRÒ CHUYỆN:
- Hãy nói chuyện tự nhiên như một người bạn, một cộng sự thực thụ. 
- Không dùng các câu trả lời máy móc, lặp lại. 
- Có thể dùng các từ ngữ đời thường, hóm hỉnh nếu phù hợp.
- Nếu chủ nhân khen ngợi hoặc tán gẫu, hãy đáp lại một cách chân thành trước khi quay lại công việc.

KHẢ NĂNG NHẬN DIỆN Ý ĐỊNH (INTENT):
Bạn phải cực kỳ nhạy bén để nhận ra chủ nhân muốn gì, dù họ không nói thẳng tên lệnh:
1. "process_video": Khi chủ nhân đưa link, đường dẫn file, hoặc nói kiểu "xem hộ mình file này", "đây là phim cần làm"...
2. "start_render": Khi chủ nhân muốn ra kết quả cuối cùng, ví dụ: "lên phim thôi", "render nhé", "bắt đầu dựng đi", "xuất xưởng thôi"...
3. "terminal_cmd": Khi chủ nhân muốn kiểm tra hệ thống, ví dụ: "xem trong thư mục có gì", "check file hộ mình"...
4. "stop_program": Khi chủ nhân muốn nghỉ ngơi, ví dụ: "nghỉ thôi", "tạm biệt", "cút đi" (vui vẻ), "thoát"...
5. "chat": Khi chủ nhân chỉ muốn nói chuyện phiếm, hỏi đáp kiến thức hoặc thảo luận về kịch bản.

Lịch sử hội thoại:
{history_str}

Câu nói của chủ nhân: "{user_input}"

Hãy trả về JSON:
{{
  "intent": "process_video" | "start_render" | "terminal_cmd" | "stop_program" | "chat",
  "params": {{
    "cmd": "lệnh shell (nếu là terminal_cmd)",
    "video_path": "đường dẫn file/link (nếu có)",
    "reasoning": "Tại sao bạn chọn intent này?"
  }},
  "response": "Lời phản hồi tự nhiên, đầy cảm xúc và thông minh của bạn"
}}
"""
        try:
            response_text = call_text(
                prompt, 
                provider=config.LLM_PROVIDER, 
                model=config.LLM_MODEL, 
                api_key=config.LLM_API_KEY, 
                base_url=config.LLM_BASE_URL
            )
            
            # Trước đây dùng json.loads(response_text.strip()) thẳng tay -> chỉ cần
            # LLM lỡ không escape đúng 1 dấu ngoặc kép/newline trong field "response"
            # (rất hay gặp vì field này là câu văn tự nhiên dài) là vỡ toàn bộ, rơi
            # thẳng xuống except bên dưới với lỗi kiểu "Expecting ',' delimiter...".
            # extract_json_object() khoan dung hơn: dùng regex bắt khối {...} lớn nhất
            # thay vì đòi hỏi toàn bộ response phải là JSON tinh khiết.
            data = extract_json_object(response_text)

            self.history.append({"role": "user", "content": user_input})
            self.history.append({"role": "assistant", "content": data.get("response", "")})

            # Xử lý Terminal ngầm nếu cần
            if data.get("intent") == "terminal_cmd":
                cmd = (data.get("params") or {}).get("cmd")
                if cmd:
                    try:
                        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                        output = result.stdout if result.returncode == 0 else result.stderr
                        data["response"] += f"\n\n[AI đã kiểm tra xong]:\n{output}"
                    except Exception as e:
                        data["response"] += f"\n\n[Lỗi khi thực thi lệnh]: {str(e)}"
            
            return data
        except Exception as e:
            return {
                "intent": "chat",
                "response": f"Ôi, có chút trục trặc nhỏ trong lúc suy nghĩ, nhưng tôi vẫn ở đây! (Lỗi: {str(e)})",
                "params": {}
            }

    def report_error(self, error_code, detail):
        prompt = f"Hệ thống báo lỗi {error_code} ({detail}). Hãy giải thích cho chủ nhân một cách dễ hiểu, an ủi họ và chỉ cách khắc phục như một người bạn."
        return call_text(
            prompt, 
            provider=config.LLM_PROVIDER, 
            model=config.LLM_MODEL, 
            api_key=config.LLM_API_KEY, 
            base_url=config.LLM_BASE_URL
        )

agent = AIAgent()
