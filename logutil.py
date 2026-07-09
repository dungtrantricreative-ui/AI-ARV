"""
logutil.py — In log có màu, DÙNG CHUNG cho toàn bộ pipeline, không phân biệt
nền tảng (Windows / Linux / macOS / Colab / server...).

Vì sao module riêng thay vì gọi print() trực tiếp:
- Muốn màu sắc NHẤT QUÁN (vàng = cảnh báo, đỏ = lỗi, xanh lá = thành công,
  xanh dương = tiến trình) trên mọi file, không phụ thuộc nền tảng cụ thể
  nào (không hardcode kiểu chỉ đẹp trên 1 máy/1 dịch vụ).
- Tự tắt màu khi không hợp lệ: khi stdout không phải terminal (ví dụ log bị
  redirect ra file, hoặc chạy trong môi trường CI/notebook không hỗ trợ mã
  ANSI), hoặc khi biến môi trường chuẩn NO_COLOR được set — để không in ra
  toàn những ký tự \\x1b[... khó đọc.
"""
import os
import sys

_RESET = "\033[0m"
_COLORS = {
    "warn": "\033[33m",    # vàng
    "err": "\033[31m",     # đỏ
    "ok": "\033[32m",      # xanh lá
    "stage": "\033[36m",   # xanh dương nhạt (cyan) — tiến trình/giai đoạn
    "mic": "\033[35m",     # tím — dòng TTS từng câu
    "bold": "\033[1m",
}


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("FORCE_COLOR") is not None:
        return True
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    return True


_COLOR_ENABLED = _supports_color()

if _COLOR_ENABLED and os.name == "nt":
    # Windows 10+ hỗ trợ ANSI nhưng cần "kích hoạt" chế độ xử lý mã màu cho
    # console trước; cách chuẩn không cần cài thêm thư viện gì (không phải
    # chỉ hoạt động trên 1 nền tảng — Linux/macOS/Colab vốn đã hỗ trợ sẵn).
    os.system("")


def _paint(kind: str, text: str) -> str:
    if not _COLOR_ENABLED:
        return text
    color = _COLORS.get(kind, "")
    return f"{color}{text}{_RESET}"


def warn(text: str):
    print(_paint("warn", text))


def err(text: str):
    print(_paint("err", text))


def ok(text: str):
    print(_paint("ok", text))


def stage(text: str):
    print(_paint("stage", text))


def mic(text: str):
    print(_paint("mic", text))


def bold(text: str):
    print(_paint("bold", text))
