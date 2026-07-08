import os
import json
import subprocess
import config
from llm_client import call_text

class AIAgent:
    def __init__(self):
        self.context = []
        self.bgm_path = None
        self.bgm_volume = 0.2
        self.bgm_loop = True

    def chat(self, user_input):
        """Xử lý yêu cầu của người dùng bằng LLM để trích xuất ý định, bao gồm cả lệnh terminal."""
        prompt = f"""
Bạn là trợ lý thông minh của dự án AI-ARV (Dựng phim Recap). Bạn có quyền truy cập vào Terminal để hỗ trợ chủ nhân.
Người dùng vừa nói: "{user_input}"

Hãy phân tích ý định của người dùng và trả về kết quả dưới dạng JSON:
{{
  "intent": "set_bgm" | "start_render" | "terminal_cmd" | "unknown",
  "params": {{
    "cmd": "lệnh shell nếu là intent terminal_cmd",
    "file_path": "đường dẫn file nhạc nếu có",
    "volume": "âm lượng (0.0 đến 1.0) nếu có",
    "loop": "true/false nếu có"
  }},
  "response": "Câu trả lời thân thiện của bạn cho người dùng"
}}
"""
        try:
            # Dùng cấu hình từ config.py
            response_text = call_text(
                prompt, 
                provider=config.LLM_PROVIDER, 
                model=config.LLM_MODEL, 
                api_key=config.LLM_API_KEY, 
                base_url=config.LLM_BASE_URL
            )
            
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            
            # Làm sạch chuỗi JSON nếu cần
            response_text = response_text.strip()
            data = json.loads(response_text)
            
            # Nếu là lệnh terminal, thực hiện ngay
            if data["intent"] == "terminal_cmd":
                cmd = data["params"].get("cmd")
                if cmd:
                    print(f"🤖 AI đang thực thi: {cmd}")
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                    if result.returncode == 0:
                        data["response"] += f"\n\n[Kết quả Terminal]:\n{result.stdout}"
                    else:
                        data["response"] += f"\n\n[Lỗi Terminal]:\n{result.stderr}"
            
            self.handle_intent(data)
            return data["response"]
        except Exception as e:
            return f"❌ Chủ nhân ơi, tôi gặp chút vấn đề khi xử lý yêu cầu: {str(e)}"

    def handle_intent(self, data):
        if data["intent"] == "set_bgm":
            params = data.get("params", {})
            if params.get("file_path"): self.bgm_path = params["file_path"]
            if params.get("volume") is not None: 
                try:
                    self.bgm_volume = float(params["volume"])
                except:
                    pass
            if params.get("loop") is not None: self.bgm_loop = str(params["loop"]).lower() == "true"

    def report_error(self, error_code, detail):
        prompt = f"Người dùng gặp lỗi {error_code}: {detail}. Hãy giải thích lỗi này một cách thân thiện và đưa ra 1-2 hướng khắc phục."
        return call_text(
            prompt, 
            provider=config.LLM_PROVIDER, 
            model=config.LLM_MODEL, 
            api_key=config.LLM_API_KEY, 
            base_url=config.LLM_BASE_URL
        )

agent = AIAgent()
