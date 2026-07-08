# 🤖 AI-ARV AGENT: HỆ THỐNG DỰNG PHIM RECAP THÔNG MINH (V5 - FINAL)

**AI-ARV** là một trợ lý AI toàn diện giúp bạn tự động hóa quy trình dựng video recap từ các nguồn video dài (phim, livestream, vlog). Hệ thống tích hợp AI để phân tích cảnh quay, phiên âm, soạn kịch bản và tự động dựng phim với giọng đọc (TTS), phụ đề và nhạc nền.

---

## 🌟 Tính năng nổi bật

- **Agent Hội Thoại Thông Minh**: Giao tiếp trực tiếp với AI để điều khiển quy trình dựng phim.
- **Xử Lý Đa Nền Tảng**: Chạy mượt mà trên **Windows, Linux và Google Colab**.
- **Nhận Diện Video Tự Động**: Hỗ trợ link YouTube hoặc đường dẫn file cục bộ.
- **Phân Tích Cảnh Quay (Scene Detection)**: Tự động chia nhỏ video thành các phân đoạn logic.
- **Biên Soạn Kịch Bản AI**: Tự động viết lời bình dựa trên nội dung video và bối cảnh.
- **Dựng Phim Tự Động (Auto-Assemble)**: Ghép nối video, giọng đọc AI, phụ đề SRT và nhạc nền chỉ với một lệnh `render`.
- **Hỗ trợ Terminal**: AI có thể thực thi các lệnh hệ thống (như kiểm tra file, dọn dẹp thư mục) ngay trong cửa sổ chat.

---

## 🛠 Hướng dẫn cài đặt chi tiết

### 1. Cài đặt FFmpeg (Bắt buộc)
FFmpeg là "trái tim" xử lý video của hệ thống. Bạn phải cài đặt nó trước khi chạy chương trình.

#### **Trên Windows:**
1.  Truy cập [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) và tải bản `ffmpeg-git-full.7z`.
2.  Giải nén vào một thư mục (ví dụ: `C:\ffmpeg`).
3.  Thêm đường dẫn đến thư mục `bin` (ví dụ: `C:\ffmpeg\bin`) vào **Environment Variables (PATH)** của hệ thống.
4.  Mở Command Prompt và gõ `ffmpeg -version` để kiểm tra.

#### **Trên Linux / Google Colab:**
```bash
sudo apt update && sudo apt install ffmpeg -y
```

### 2. Cài đặt thư viện Python
Yêu cầu Python 3.9 trở lên. Chạy lệnh sau tại thư mục dự án:
```bash
pip install -r requirements.txt
```

### 3. Cấu hình API Key
1.  Tìm file `config.toml.example` trong thư mục gốc.
2.  Đổi tên nó thành `config.toml`.
3.  Mở file và điền API Key của bạn:
    - `google`: Sử dụng Gemini (Khuyên dùng vì có bản miễn phí chất lượng cao).
    - `groq`: Sử dụng cho tốc độ phiên âm (Whisper) cực nhanh.
    - `openai`: Sử dụng cho GPT-4 hoặc Whisper.

---

## 🚀 Quy trình sử dụng (Workflow)

Để bắt đầu, hãy chạy lệnh:
```bash
python main.py
```

### Bước 1: Cung cấp Video
Khi AI chào bạn, hãy dán đường dẫn video:
- **Link YouTube**: `https://www.youtube.com/watch?v=...`
- **File cục bộ**: `C:\Videos\my_movie.mp4` (Windows) hoặc `/content/video.mp4` (Colab).

AI sẽ tự động tải/copy và chạy bước **Prepare** (Phân tích cảnh, phiên âm và soạn kịch bản nháp).

### Bước 2: Kiểm tra Kịch bản (Tùy chọn)
Kịch bản nháp sẽ được lưu tại `workdir/script_draft.json`. Bạn có thể mở file này để chỉnh sửa nội dung lời bình nếu muốn. Sau khi sửa, hãy lưu thành `workdir/script_final.json`.

### Bước 3: Ra lệnh Render
Chỉ cần gõ vào cửa sổ chat:
> `render` hoặc `render now` hoặc `bắt đầu đi`

AI sẽ tự động làm tất cả các bước còn lại và xuất video tại thư mục `output/recap_final.mp4`.

---

## 📂 Cấu trúc thư mục dự án

- `main.py`: Điểm khởi đầu của chương trình, quản lý vòng lặp Agent.
- `agent_manager.py`: Bộ não của AI, xử lý ngôn ngữ tự nhiên và lệnh terminal.
- `config.py`: Quản lý cấu hình và đường dẫn hệ thống.
- `scene_detect.py`: Xử lý phân tách cảnh quay.
- `transcribe.py`: Chuyển đổi âm thanh video thành văn bản.
- `script_gen.py`: AI soạn kịch bản dựa trên hình ảnh và văn bản.
- `tts.py`: Tạo giọng đọc từ kịch bản.
- `sync_assemble.py`: Ghép nối tất cả thành phần thành video hoàn chỉnh.
- `workdir/`: Thư mục chứa các file trung gian (kịch bản, audio trích xuất).
- `output/`: Thư mục chứa video kết quả cuối cùng.

---

## ⚠️ Lưu ý quan trọng

- **Lỗi moov atom**: Nếu AI báo lỗi này, file video của bạn bị hỏng hoặc chưa tải xong. Hãy tải lại file.
- **Tốc độ xử lý**: Phụ thuộc vào độ dài video và cấu hình máy tính của bạn (đặc biệt là bước Scene Detection).
- **Quyền Terminal**: AI có thể thực thi lệnh terminal, hãy cẩn thận khi yêu cầu nó xóa file hoặc thực hiện các lệnh can thiệp hệ thống sâu.

---
*Phát triển bởi Manus AI - Chúc bạn tạo ra những video Recap ấn tượng!*
