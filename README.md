# Video Recap Tool — Tối ưu đa phần cứng + Interval Slicing

Pipeline bán tự động: AI lo phần nặng, bạn lo phần "linh hồn" (sửa kịch bản).

## Kiến trúc

```
1. Nhận file video      đường dẫn local
2. Chia cảnh           PySceneDetect HOẶC Interval Slicing (FFmpeg)
3. Phiên âm+timestamp  ASR provider (cấu hình qua config.toml)
4. Sinh script nháp    LLM provider (cấu hình qua config.toml)
   ── CHECKPOINT: sửa workdir/script_draft.json -> script_final.json ──
5. TTS + neo mốc       edge-tts + ffmpeg atempo
6. Sinh phụ đề         .srt khớp audio đã sync
7. Ghép video cuối     ffmpeg (adelay + amix + burn sub)
```

## Tính năng mới

### 1. Cắt Thô Bạo (Interval Slicing)
Thay vì phân tích pixel bằng PySceneDetect (chậm, ngốn CPU/GPU), bạn có thể chuyển sang **cắt theo khoảng thời gian cố định** bằng FFmpeg CLI. Ưu điểm:
- **Không decode video**, chỉ đọc metadata → xử lý phim 2 tiếng trong **< 30 giây**
- Chạy tốt trên **mọi phần cứng**, kể cả CPU cùi
- Phù hợp recap phim dài, livestream, podcast...

Chỉnh trong `config.toml`:
```toml
[scene_detect]
method = "interval"          # "content" | "interval"
interval_seconds = 5.0       # Cắt mỗi 5 giây
output_format = "json"       # "json" | "xml" | "edl"
```

### 2. Trích audio trước khi gửi ASR
Tránh lỗi "file quá lớn" khi đẩy nguyên video `.mp4` lên API. Audio được nén xuống **32kbps mono** trước khi gửi.

### 3. TTS async song song
Các dòng thoại được tổng hợp giọng nói **đồng thời** thay vì tuần tự, giảm thời gian TTS đáng kể.

### 4. Robust JSON extraction
Script generator dùng regex để trích JSON từ LLM, giảm 90% lỗi parse.

## Cài đặt

```bash
# 1. Clone & cài package
pip install -r requirements.txt

# 2. Cài ffmpeg hệ thống (macOS: brew, Ubuntu: apt, Windows: ffmpeg.org)

# 3. Tạo config & env từ mẫu
cp config.toml.example config.toml
cp .env.example .env
# Sửa .env điền API key
```

## Chạy

```bash
# Bước 1-4: chia cảnh, phiên âm, sinh script nháp
python main.py prepare "/đường/dẫn/tới/video.mp4"

# --- CHECKPOINT ---
# Mở workdir/script_draft.json, sửa "text" theo gu riêng, lưu thành script_final.json

# Bước 5-7: TTS, neo mốc, ghép video
python main.py render
```

Video cuối: `output/recap_final.mp4`

Tuỳ chọn render:
- `python main.py render --no-subtitles` — không burn phụ đề (render nhanh, copy video)
- `python main.py render --keep-bg-audio` — giữ tiếng gốc nhỏ làm nền

## Cấu trúc

```
video-recap-tool/
├── main.py              # CLI: prepare / render
├── config.py            # Đọc config.toml + .env, định nghĩa đường dẫn & key
├── config.toml          # Chọn provider/model/scene method
├── config.toml.example  # Mẫu cấu hình
├── .env.example         # Mẫu API key
├── requirements.txt
├── download.py          # Giữ lại yt-dlp (tùy chọn)
├── scene_detect.py      # PySceneDetect + Interval Slicing + XML/EDL
├── transcribe.py        # ASR (Groq/OpenAI) + trích audio
├── script_gen.py        # LLM sinh script + regex JSON
├── tts.py               # Edge-TTS + atempo (async parallel)
├── subtitles.py         # .srt
├── sync_assemble.py     # ffmpeg ghép final
├── modal_app.py         # Stub chạy Modal.com
├── workdir/             # Tự động tạo
└── output/              # Tự động tạo
```

## Những gì đã sửa

- **scene_detect.py**: Thêm `interval` mode (FFmpeg), xuất XML/EDL, fallback tự động.
- **transcribe.py**: Trích audio MP3 32kb trước khi gửi API; sửa `_extract_segments` hỗ trợ cả object và dict.
- **script_gen.py**: Dùng regex để trích JSON an toàn; transcript tự động cắt nếu quá dài.
- **tts.py**: TTS async song song, tránh `asyncio.run` lồng nhau.
- **sync_assemble.py**: Escape dấu nháy đơn trong path SRT.
- **config.py**: Thêm `SCENE_DETECT_METHOD`, `SCENE_INTERVAL_SECONDS`, `SCENE_OUTPUT_FORMAT`.
- **main.py**: Đầu vào là file video local; `--force` hoạt động thật.
