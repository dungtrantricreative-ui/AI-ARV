"""
Bản chạy trên Modal.com (cloud).
Cài Modal CLI: pip install modal
Chạy: modal run modal_app.py
"""
import modal

image = (
    modal.Image.debian_slim()
    .apt_install("ffmpeg")
    .pip_install_from_requirements("requirements.txt")
)
app = modal.App("video-recap-tool", image=image)

@app.function()
def hello():
    return "Modal app ready. Hãy implement pipeline cloud tại đây nếu cần."
