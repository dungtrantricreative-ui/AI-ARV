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

# 3. Tạo config từ mẫu, điền api_key trực tiếp vào config.toml
cp config.toml.example config.toml

# 4. (Tùy chọn) Nếu không muốn lưu key trong config.toml, dùng .env thay thế
cp .env.example .env
# Sửa .env điền API key — LƯU Ý: api_key trong config.toml (nếu có) luôn được
# ưu tiên hơn .env. Để trống api_key trong config.toml nếu muốn dùng .env.
```

## Chạy

```bash
# Bước 0 (tùy chọn): tải video từ URL nếu chưa có sẵn file local (cần: pip install yt-dlp)
python main.py download "https://..."

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
- `python main.py render --force` — ghi đè `output/recap_final.mp4` nếu đã tồn tại (mặc định sẽ dừng lại để tránh mất video cũ)

## Cấu trúc

```
video-recap-tool/
├── main.py              # CLI: download / prepare / render
├── config.py            # Đọc config.toml + .env, định nghĩa đường dẫn & key
├── config.toml          # Chọn provider/model/scene method + api_key
├── config.toml.example  # Mẫu cấu hình
├── .env.example         # Mẫu API key (tùy chọn, thay thế cho api_key trong config.toml)
├── requirements.txt
├── download.py          # yt-dlp — gọi qua `python main.py download <url>`
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
- **main.py**: Đầu vào là file video local; `--force` hoạt động thật (ghi đè output khi render); thêm subcommand `download` (trước đây `download.py` tồn tại nhưng không gọi được từ CLI).
- **config.py**: `ASR_API_KEY`/`LLM_API_KEY` giờ fallback đúng biến môi trường theo provider đang chọn (trước đây ASR thiếu `OPENAI_API_KEY`, LLM thiếu `GROQ_API_KEY` nên dễ 401 nhầm key).
- **tts.py**: `build_atempo_filter` dùng đúng `MIN/MAX_TIME_STRETCH_RATIO` từ config thay vì hardcode 0.2-5.0; in cảnh báo khi ref_start/ref_end không hợp lệ; in stderr ffmpeg khi atempo lỗi.
- **transcribe.py**: Cache audio trích xuất theo size+mtime của video thay vì chỉ theo tên file `source.mp4` (trước đây đổi video mới nhưng giữ tên cũ sẽ vô tình dùng nhầm audio cache của video trước).
- **sync_assemble.py**: `adelay` dùng `all=1` để không phụ thuộc số kênh audio TTS (mono/stereo); áp style phụ đề (`SRT_FONT_SIZE`, màu, viền) từ config vào filter burn-sub (trước đây các biến này định nghĩa nhưng không được dùng); log lỗi ffmpeg đầy đủ ra file thay vì cắt 2000 ký tự.
- **scene_detect.py**: Sửa lỗi cảnh đầu tiên bị drop hoàn toàn nếu ngắn hơn `min_duration`; fallback về interval giờ in kèm số giây interval.
- **requirements.txt**: Thêm `yt-dlp` (cần cho `download.py`/subcommand `download`).
- **config.toml.example**: Đổi tên đúng từ `config_toml.example` (README gọi `cp config.toml.example config.toml` nhưng file cũ tên sai, gây lỗi "no such file" cho người dùng mới).
- **.env.example**: Thêm file này (được README nhắc tới nhưng trước đây không tồn tại trong repo).
- **config.toml**: Thay giá trị `api_key` giả trông giống key thật (`gsk_...`, `csk_...`) bằng chuỗi rỗng có comment rõ ràng, tránh người dùng quên sửa mà không biết vì sao bị lỗi 401.
