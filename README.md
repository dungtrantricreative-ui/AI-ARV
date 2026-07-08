# AI-ARV AGENT: TRỢ LÝ DỰNG PHIM THÔNG MINH (Universal Edition)

Công cụ này giúp bạn tự động hóa quy trình dựng video Recap từ phim, livestream hoặc video dài. Phiên bản này đã được tối ưu hóa để chạy trên **Windows, Linux và Google Colab**.

---

## 🚀 Hướng dẫn cài đặt nhanh

### 1. Yêu cầu bắt buộc (Cài đặt một lần duy nhất)
Dù bạn dùng Windows hay Linux, bạn **PHẢI** cài đặt `ffmpeg` để xử lý video:

*   **Windows**: 
    1. Tải ffmpeg từ [gyan.dev](https://www.gyan.dev/ffmpeg/builds/).
    2. Giải nén và thêm thư mục `bin` vào **Environment Variables (PATH)**.
    3. Mở Terminal gõ `ffmpeg -version` để kiểm tra.
*   **Linux/Colab**: 
    ```bash
    sudo apt update && sudo apt install ffmpeg -y
    ```

### 2. Cài đặt thư viện Python
Mở Terminal tại thư mục dự án và chạy:
```bash
pip install -r requirements.txt
```

### 3. Cấu hình API
Đổi tên file `config.toml.example` thành `config.toml` và điền API Key của bạn (Google Gemini, Groq, hoặc OpenAI).

---

## 🤖 Cách sử dụng Agent thông minh

Chỉ cần chạy lệnh sau để bắt đầu trò chuyện với AI:
```bash
python main.py
```

### Các tính năng "Vạn năng":
1.  **Tự động nhận diện Video**: Bạn dán link YouTube hoặc đường dẫn file (ví dụ: `C:\Videos\film.mp4` trên Windows hoặc `/content/film.mp4` trên Colab), AI sẽ tự động tải/copy và phân tích.
2.  **Hỗ trợ Terminal đa nền tảng**: AI tự biết bạn đang dùng Windows hay Linux để thực hiện các lệnh như kiểm tra file, dọn dẹp thư mục.
3.  **Hội thoại liên tục**: Bạn có thể chat, yêu cầu thêm nhạc nền, chỉnh âm lượng trước khi gõ `render` để xuất video cuối cùng.

---

## 🛠 Xử lý sự cố thường gặp

*   **Lỗi `moov atom not found`**: File video bị hỏng hoặc tải chưa xong. Hãy tải lại video.
*   **Lỗi `ffmpeg not found`**: Bạn chưa cài ffmpeg hoặc chưa thêm vào PATH (Windows).
*   **Lỗi API**: Kiểm tra lại số dư tài khoản và API Key trong `config.toml`.

---
*Chúc bạn có những trải nghiệm tuyệt vời với AI-ARV!*
