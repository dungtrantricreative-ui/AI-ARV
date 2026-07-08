import os
import json
import subprocess
import config
from llm_client import call_text

class AIAgent:
    def __init__(self):
        self.history = []  # Lưu lịch sử hội thoại
        self.bgm_path = None
        self.bgm_volume = 0.2
        self.bgm_loop = True

    def chat(self, user_input):
        """Xử lý yêu cầu của người dùng bằng LLM để trích xuất ý định, bao gồm cả lệnh terminal."""
        
        # Xây dựng context từ lịch sử
        history_str = ""
        for msg in self.history[-5:]: # Lấy 5 câu gần nhất để giữ context
            history_str += f"{msg['role']}: {msg['content']}\n"

        prompt = f"""
Bạn là trợ lý thông minh của dự án AI-ARV (Dựng phim Recap). Bạn có quyền truy cập vào Terminal để hỗ trợ chủ nhân.
Lịch sử hội thoại gần đây:
{history_str}

Người dùng vừa nói: "{user_input}"

Hãy phân tích ý định của người dùng và trả về kết quả dưới dạng JSON:
{{
  "intent": "set_bgm" | "start_render" | "terminal_cmd" | "stop_program" | "process_video" | "chat" | "unknown",
  "params": {{
    "cmd": "lệnh shell nếu là intent terminal_cmd",
    "video_path": "đường dẫn file video hoặc link URL nếu người dùng cung cấp hoặc đã cung cấp trước đó",
    "file_path": "đường dẫn file nhạc nếu có",
    "volume": "âm lượng (0.0 đến 1.0) nếu có",
    "loop": "true/false nếu có"
  }},
  "response": "Câu trả lời thân thiện của bạn cho người dùng"
}}

Lưu ý quan trọng:
1. Nếu người dùng cung cấp đường dẫn video (ví dụ: /content/...) hoặc link video, hãy đặt intent là "process_video" và trích xuất đường dẫn vào "video_path".
2. Nếu người dùng hỏi "sẵn sàng chưa", "bắt đầu đi" hoặc muốn render khi đã có video rồi, hãy đặt intent là "start_render".
3. ĐỪNG trả lời "hãy cho tôi link video" nếu trong lịch sử hoặc trong câu nói hiện tại đã có đường dẫn video rồi.
4. Nếu là yêu cầu chạy lệnh máy tính, hãy đặt intent là "terminal_cmd".
5. Luôn trả về JSON hợp lệ.
"""
        try:
            response_text = call_text(
                prompt, 
                provider=config.LLM_PROVIDER, 
                model=config.LLM_MODEL, 
                api_key=config.LLM_API_KEY, 
                base_url=config.LLM_BASE_URL
            )
            
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            
            response_text = response_text.strip()
            data = json.loads(response_text)
            
            # Lưu vào lịch sử
            self.history.append({"role": "user", "content": user_input})
            self.history.append({"role": "assistant", "content": data["response"]})

            # Nếu là lệnh terminal, thực hiện ngay
            if data["intent"] == "terminal_cmd":
                cmd = data["params"].get("cmd")
                if cmd:
                    print(f"🤖 AI đang thực thi: {cmd}")
                    try:
                        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                        if result.returncode == 0:
                            output = result.stdout if result.stdout else "Lệnh đã thực thi thành công (không có output)."
                            data["response"] += f"\n\n[Kết quả Terminal]:\n{output}"
                        else:
                            data["response"] += f"\n\n[Lỗi Terminal]:\n{result.stderr}"
                    except subprocess.TimeoutExpired:
                        data["response"] += f"\n\n[Lỗi Terminal]: Lệnh thực thi quá thời gian quy định (30s)."
            
            self.handle_intent(data)
            return data
        except Exception as e:
            return {
                "intent": "error",
                "response": f"❌ Chủ nhân ơi, tôi gặp chút vấn đề khi xử lý yêu cầu: {str(e)}",
                "params": {}
            }

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
