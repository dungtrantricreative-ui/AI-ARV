# Video Recap Tool

Công cụ dòng lệnh (CLI) giúp biến một video dài (phim, tập phim, livestream, podcast...) thành video **recap/tóm tắt** có giọng đọc AI (TTS), tự động đồng bộ theo mốc thời gian và đốt phụ đề vào video — theo mô hình **bán tự động**: AI lo phần nặng (phiên âm, chia cảnh, viết nháp kịch bản, đọc giọng, ghép video), còn bạn lo phần "linh hồn" — sửa lại lời thoại recap theo văn phong riêng trước khi render bản cuối.

Toàn bộ pipeline chạy local trên máy bạn (dùng `ffmpeg`), chỉ gọi ra ngoài để dùng API ASR (phiên âm) và LLM (sinh kịch bản) — cả hai đều **cấu hình được provider** (đổi nhà cung cấp mà không cần sửa code).

---

## Mục lục

- [Tính năng](#tính-năng)
- [Kiến trúc pipeline](#kiến-trúc-pipeline)
- [Yêu cầu hệ thống](#yêu-cầu-hệ-thống)
- [Cài đặt](#cài-đặt)
- [Cấu hình](#cấu-hình)
  - [config.toml đầy đủ](#configtoml-đầy-đủ)
  - [Biến môi trường / .env](#biến-môi-trường--env)
  - [Chọn provider ASR / LLM](#chọn-provider-asr--llm)
- [Sử dụng](#sử-dụng)
  - [1. (Tùy chọn) Tải video từ URL](#1-tùy-chọn-tải-video-từ-url)
  - [2. `prepare` — chia cảnh, phiên âm, sinh kịch bản nháp](#2-prepare--chia-cảnh-phiên-âm-sinh-kịch-bản-nháp)
  - [3. Checkpoint — chỉnh sửa kịch bản](#3-checkpoint--chỉnh-sửa-kịch-bản)
  - [4. `render` — TTS, đồng bộ, ghép video cuối](#4-render--tts-đồng-bộ-ghép-video-cuối)
- [Cấu trúc thư mục](#cấu-trúc-thư-mục)
- [Định dạng file trung gian](#định-dạng-file-trung-gian)
- [Chạy trên cloud (Modal.com)](#chạy-trên-cloud-modalcom)
- [Xử lý sự cố (Troubleshooting)](#xử-lý-sự-cố-troubleshooting)
- [Giới hạn hiện tại](#giới-hạn-hiện-tại)
- [Giấy phép](#giấy-phép)

---

## Tính năng

### Chia cảnh (Scene Detection) — 2 chế độ
- **Interval Slicing (mặc định)**: cắt video thành các đoạn có độ dài cố định (vd mỗi 5 giây) chỉ bằng cách đọc metadata qua `ffprobe`, **không decode video** → xử lý phim 2 tiếng trong dưới 30 giây, chạy tốt trên mọi phần cứng kể cả CPU yếu.
- **Content Detection**: dùng [PySceneDetect](https://www.scenedetect.com/) phân tích thay đổi khung hình để tách theo cảnh phim thật sự (chính xác hơn nhưng chậm hơn, cần decode toàn bộ video). Nếu PySceneDetect gặp lỗi hoặc chưa được cài, hệ thống tự động **fallback về Interval Slicing**.
- Xuất danh sách cảnh ra 3 định dạng: `json` (mặc định, dùng nội bộ), `xml` (Final Cut Pro XML), `edl` (Edit Decision List — tương thích Premiere/DaVinci Resolve).

### Phiên âm (ASR — Automatic Speech Recognition)
- Trích audio từ video trước khi gửi API (nén xuống mono 16kHz, 32kbps) để giảm dung lượng upload và tránh lỗi "file quá lớn".
- Hỗ trợ 2 provider: **Groq** (Whisper Large v3, tốc độ rất nhanh, có gói free) và **OpenAI-compatible** (bất kỳ API nào tương thích chuẩn OpenAI, gồm chính OpenAI Whisper).
- Tự động retry khi gặp lỗi rate limit (429) với backoff tăng dần.
- Cache audio đã trích theo (tên file + dung lượng + thời gian sửa đổi) — chạy lại không cần trích lại audio nếu video không đổi.

### Sinh kịch bản recap (LLM)
- Đưa transcript (có timestamp) + danh sách cảnh vào prompt, yêu cầu LLM viết lại thành kịch bản recap ngắn gọn bằng tiếng Việt, mỗi dòng gắn với một khoảng thời gian cụ thể trong video gốc (`ref_start` / `ref_end`).
- Hỗ trợ 3 provider: **Google Gemini**, **Groq**, **OpenAI-compatible** (dùng được với Cerebras, OpenRouter, hoặc bất kỳ endpoint nào tương thích chuẩn OpenAI Chat Completions).
- Transcript quá dài (>20.000 ký tự) tự động được rút gọn thông minh (giữ đầu + cuối, lược phần giữa) để không tràn context window.
- Trích JSON từ phản hồi LLM bằng regex, chịu lỗi tốt hơn so với parse JSON trực tiếp (LLM hay chèn thêm text giải thích dù đã dặn không làm vậy).

### Checkpoint chỉnh sửa thủ công
- Sau bước `prepare`, bạn có toàn quyền sửa lại nội dung lời thoại recap (`workdir/script_draft.json` → lưu thành `workdir/script_final.json`) trước khi render — đây là bước để bạn thêm "chất riêng" vào video, AI không tự ý quyết định lời thoại cuối cùng.

### Text-to-Speech (TTS) + neo mốc thời gian
- Dùng [edge-tts](https://github.com/rany2/edge-tts) (giọng đọc Microsoft Edge, miễn phí, nhiều giọng tiếng Việt).
- Mỗi dòng thoại được tổng hợp giọng nói **song song (async)** thay vì tuần tự, giảm đáng kể thời gian chờ khi có nhiều dòng.
- Sau khi tổng hợp, audio được **kéo dãn/nén (time-stretch)** bằng bộ lọc `atempo` của ffmpeg để khớp đúng với khoảng thời gian cảnh gốc (`ref_end - ref_start`), giữ nguyên cao độ giọng nói (không bị "chipmunk" hay "rùa bò").
- Tỉ lệ stretch được giới hạn trong khoảng cấu hình được (mặc định 0.5x–2.0x) để tránh giọng bị méo quá đà nếu bạn viết lời thoại quá dài/ngắn so với cảnh gốc.
- Tự động retry khi TTS lỗi (mạng chập chờn), có exponential backoff.

### Phụ đề & ghép video cuối
- Sinh file `.srt` khớp chính xác với timeline audio đã đồng bộ.
- Style phụ đề (cỡ chữ, màu chữ, màu viền, độ dày viền) cấu hình được trong `config.py`, áp dụng khi burn phụ đề vào video bằng filter `subtitles` của ffmpeg.
- Ghép nhiều track TTS đã có độ trễ (`adelay`) riêng theo từng mốc thời gian, mix lại thành 1 track audio duy nhất.
- Tùy chọn **giữ lại tiếng nền gốc** ở âm lượng nhỏ (20%) chạy song song với giọng đọc recap, hoặc tắt hẳn tiếng gốc.
- Tùy chọn **không burn phụ đề** — khi đó video được copy stream video gốc (không re-encode) nên render cực nhanh, chỉ ghép audio.
- Khi có lỗi ffmpeg, log đầy đủ được ghi ra `workdir/ffmpeg_assemble_error.log` (không bị cắt bớt) để dễ debug.

### Tải video từ URL (tùy chọn)
- Có thể tải trực tiếp từ URL (YouTube và các nền tảng [yt-dlp](https://github.com/yt-dlp/yt-dlp) hỗ trợ) thay vì phải có sẵn file local.

---

## Kiến trúc pipeline

```
0. (Tùy chọn) Tải video   yt-dlp, từ URL -> workdir/source.mp4
1. Nhận file video        Copy vào workdir/source.mp4
2. Chia cảnh               PySceneDetect HOẶC Interval Slicing (FFmpeg)
3. Phiên âm + timestamp    ASR provider (Groq / OpenAI-compatible)
4. Sinh kịch bản nháp      LLM provider (Google / Groq / OpenAI-compatible)
   ── CHECKPOINT: sửa workdir/script_draft.json -> lưu thành script_final.json ──
5. TTS + neo mốc           edge-tts + ffmpeg atempo (song song, có time-stretch)
6. Sinh phụ đề              .srt khớp audio đã đồng bộ
7. Ghép video cuối          ffmpeg (adelay + amix + burn phụ đề) -> output/recap_final.mp4
```

Toàn bộ pipeline được chia làm 2 lệnh CLI chính: `prepare` (bước 1–4) và `render` (bước 5–7), với một checkpoint thủ công ở giữa để bạn kiểm soát chất lượng nội dung.

---

## Yêu cầu hệ thống

- **Python** 3.9 trở lên (khuyến nghị 3.11+; nếu dùng Python < 3.11 cần thêm gói `tomli`, đã có sẵn trong `requirements.txt`).
- **ffmpeg** và **ffprobe** cài sẵn trong hệ thống và có trong `PATH`.
  - macOS: `brew install ffmpeg`
  - Ubuntu/Debian: `sudo apt install ffmpeg`
  - Windows: tải từ [ffmpeg.org](https://ffmpeg.org/download.html) rồi thêm thư mục `bin` vào biến môi trường `PATH`.
- (Tùy chọn) **yt-dlp** nếu muốn dùng lệnh `download` để tải video từ URL — đã có trong `requirements.txt`.
- API key của ít nhất 1 provider ASR và 1 provider LLM (xem phần [Cấu hình](#cấu-hình)). Có gói miễn phí ở cả Groq và Google Gemini nên có thể chạy toàn bộ pipeline mà không tốn phí.

---

## Cài đặt

```bash
# 1. Clone repo (hoặc giải nén nếu bạn tải file zip)
git clone <repo-url> video-recap-tool
cd video-recap-tool

# 2. (Khuyến nghị) Tạo virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Cài các gói Python
pip install -r requirements.txt

# 4. Cài ffmpeg hệ thống (xem phần Yêu cầu hệ thống ở trên nếu chưa có)

# 5. Tạo file cấu hình từ mẫu
cp config.toml.example config.toml
# Mở config.toml, điền api_key vào (xem phần Cấu hình bên dưới)
```

Kiểm tra cài đặt thành công:

```bash
python main.py
```

Lệnh này sẽ in ra hướng dẫn sử dụng (help) nếu mọi thứ ổn.

---

## Cấu hình

Công cụ đọc cấu hình theo thứ tự ưu tiên:

1. **`config.toml`** — nếu trường `api_key` trong file này có giá trị, nó luôn được dùng, bất kể biến môi trường là gì.
2. **Biến môi trường chung** — `ASR_API_KEY` / `LLM_API_KEY` (áp dụng cho service tương ứng, bất kể provider nào).
3. **Biến môi trường riêng theo provider** — vd `GROQ_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`. Chỉ được dùng nếu đúng provider đang chọn khớp với biến đó (để tránh lấy nhầm key của provider khác khi bạn có nhiều key trong máy).

Cách đơn giản nhất là **điền thẳng `api_key` vào `config.toml`** — không cần đụng tới `.env` hay biến môi trường gì cả. Cách dùng `.env` (biến môi trường) chỉ dành cho ai không muốn lưu key trực tiếp trong file cấu hình (vd khi commit code lên git công khai).

### config.toml đầy đủ

```toml
[asr_service]
provider = "groq"                          # "groq" | "openai"
base_url = "https://api.groq.com"          # đổi nếu dùng endpoint OpenAI-compatible khác
model = "whisper-large-v3"
api_key = ""                               # dán key thật vào đây, hoặc để trống dùng .env

[llm_service]
provider = "google"                        # "google" | "groq" | "openai"
base_url = "https://generativelanguage.googleapis.com"
model = "gemini-2.0-flash-exp"
api_key = ""

[tts_service]
provider = "edge"                          # hiện chỉ hỗ trợ "edge" (edge-tts)
voice_vi = "vi-VN-HoaiMyNeural"            # xem danh sách giọng: `edge-tts --list-voices`

[scene_detect]
method = "interval"                        # "content" | "interval"
threshold = 27.0                           # chỉ dùng khi method="content" (PySceneDetect)
min_duration = 1.5                         # giây, cảnh ngắn hơn sẽ bị gộp vào cảnh trước
interval_seconds = 5.0                     # chỉ dùng khi method="interval"
output_format = "json"                     # "json" | "xml" | "edl"
```

| Trường | Ý nghĩa |
|---|---|
| `asr_service.provider` | `groq` dùng SDK Groq chính thức; `openai` dùng SDK OpenAI (tương thích mọi endpoint theo chuẩn OpenAI Audio Transcriptions). |
| `asr_service.base_url` | Chỉ có tác dụng khi `provider = "openai"`. Đổi để trỏ tới endpoint tương thích khác. |
| `llm_service.provider` | `google` dùng SDK Gemini; `groq` dùng SDK Groq chat; `openai` dùng SDK OpenAI Chat Completions (tương thích Cerebras, OpenRouter, LM Studio local, v.v.). |
| `scene_detect.threshold` | Ngưỡng nhạy cảm phát hiện đổi cảnh của PySceneDetect — số càng thấp càng dễ tách cảnh (nhạy), càng cao càng ít cảnh hơn. |
| `scene_detect.min_duration` | Cảnh phát hiện được ngắn hơn giá trị này sẽ tự động gộp vào cảnh liền trước, tránh cảnh vụn vặt vài trăm mili-giây. |

Ngoài `config.toml`, một số hằng số nâng cao nằm trong `config.py` (ít khi cần đổi, đổi trực tiếp trong code nếu cần):

```python
MIN_TIME_STRETCH_RATIO = 0.5   # giọng TTS không bị nén nhanh hơn 2x
MAX_TIME_STRETCH_RATIO = 2.0   # giọng TTS không bị kéo chậm hơn 2x

SRT_FONT_SIZE = 16
SRT_PRIMARY_COLOR = "&H00FFFFFF"   # trắng, định dạng màu kiểu ASS/SSA (&HAABBGGRR)
SRT_OUTLINE_COLOR = "&H00000000"   # viền đen
SRT_OUTLINE_WIDTH = 2
```

### Biến môi trường / .env

Nếu không muốn ghi `api_key` trực tiếp vào `config.toml`, để trống `api_key = ""` và dùng file `.env`:

```bash
cp .env.example .env
```

Nội dung `.env.example`:

```dotenv
GROQ_API_KEY=
OPENAI_API_KEY=
GOOGLE_API_KEY=

# Ghi đè chung, áp dụng bất kể provider nào (ưu tiên cao hơn key theo provider ở trên)
ASR_API_KEY=
LLM_API_KEY=
```

Điền đúng biến tương ứng với provider bạn đã chọn trong `config.toml`. `.env` được đọc tự động khi chạy (qua `python-dotenv`), không cần export thủ công.

### Chọn provider ASR / LLM

| Provider | Dùng cho | Cần gì |
|---|---|---|
| Groq | ASR (Whisper) hoặc LLM (Llama/Mixtral...) | `GROQ_API_KEY` — lấy miễn phí tại [console.groq.com](https://console.groq.com) |
| Google Gemini | LLM | `GOOGLE_API_KEY` — lấy miễn phí tại [aistudio.google.com](https://aistudio.google.com) |
| OpenAI-compatible | ASR hoặc LLM | `OPENAI_API_KEY` + `base_url` phù hợp (OpenAI, Cerebras, OpenRouter, LM Studio local, v.v.) |

Có thể trộn tùy ý — vd dùng Groq cho ASR (nhanh, free) và Google Gemini cho LLM (chất lượng viết tốt), hoặc trỏ cả hai vào cùng 1 endpoint OpenAI-compatible.

---

## Sử dụng

### 1. (Tùy chọn) Tải video từ URL

```bash
python main.py download "https://www.youtube.com/watch?v=..."
```

Video được tải về `workdir/source.mp4` (ưu tiên mp4 chất lượng cao nhất có sẵn). Yêu cầu đã cài `yt-dlp` (`pip install yt-dlp`, có sẵn trong `requirements.txt`). Nếu đã có file video local, có thể bỏ qua bước này và dùng thẳng lệnh `prepare` với đường dẫn file.

### 2. `prepare` — chia cảnh, phiên âm, sinh kịch bản nháp

```bash
python main.py prepare "/đường/dẫn/tới/video.mp4"
```

Các bước diễn ra tự động:
1. Copy video vào `workdir/source.mp4`.
2. Chia cảnh theo `config.toml` (`interval` hoặc `content`).
3. Trích audio và gửi phiên âm qua ASR provider đã cấu hình.
4. Gửi transcript + danh sách cảnh cho LLM để sinh kịch bản recap nháp.

Kết quả: `workdir/script_draft.json`.

**Cờ (flags):**

| Cờ | Ý nghĩa |
|---|---|
| `--force` | Ghi đè `workdir/source.mp4` nếu đã tồn tại (mặc định: nếu đã có sẵn `source.mp4` trong workdir và bạn không truyền `--force`, công cụ sẽ dùng luôn file cũ thay vì copy đè, tiết kiệm thời gian copy file nặng). |

Ví dụ chạy lại `prepare` với video mới, ghi đè video cũ trong workdir:

```bash
python main.py prepare "/đường/dẫn/video_moi.mp4" --force
```

### 3. Checkpoint — chỉnh sửa kịch bản

Đây là bước **thủ công, quan trọng nhất** để video có "chất riêng" của bạn:

1. Mở `workdir/script_draft.json`.
2. Sửa nội dung trường `text` ở từng dòng theo văn phong bạn muốn (giữ nguyên `ref_start`/`ref_end` trừ khi muốn thay đổi mốc gắn thoại).
3. Lưu file thành `workdir/script_final.json` (đúng tên này, `render` sẽ tìm file này).

Định dạng mỗi dòng trong file JSON:

```json
{
  "ref_start": 0.0,
  "ref_end": 4.2,
  "text": "Mở đầu phim, chúng ta thấy một thành phố chìm trong bóng tối..."
}
```

- `ref_start` / `ref_end`: mốc thời gian (giây) trong **video gốc** mà dòng thoại này sẽ được gán vào — quyết định audio TTS sẽ bị kéo dãn/nén bao nhiêu để khớp khung thời gian này.
- `text`: nội dung lời đọc (tiếng Việt), sẽ được đưa thẳng vào TTS.

Có thể thêm/xóa/sắp xếp lại dòng tùy ý, miễn giữ đúng 3 trường bắt buộc trên — `render` sẽ validate và báo lỗi rõ ràng (kèm số dòng) nếu thiếu trường.

### 4. `render` — TTS, đồng bộ, ghép video cuối

```bash
python main.py render
```

Các bước diễn ra tự động:
5. Đọc `workdir/script_final.json`, tổng hợp giọng nói song song cho từng dòng (edge-tts).
6. Kéo dãn/nén từng đoạn audio để khớp khung thời gian, sinh phụ đề `.srt`.
7. Ghép audio TTS + (tùy chọn) tiếng nền gốc + (tùy chọn) burn phụ đề vào video, xuất ra `output/recap_final.mp4`.

**Cờ (flags):**

| Cờ | Ý nghĩa |
|---|---|
| `--no-subtitles` | Không burn phụ đề vào video. Khi bật cờ này, video được **copy stream** (không re-encode phần hình ảnh) nên render rất nhanh, chỉ tốn thời gian ghép audio. |
| `--keep-bg-audio` | Giữ lại tiếng nền gốc của video ở âm lượng nhỏ (20%), chạy song song với giọng đọc recap. Mặc định tiếng gốc bị tắt hoàn toàn, chỉ còn giọng recap. |
| `--force` | Ghi đè `output/recap_final.mp4` nếu file đã tồn tại. Mặc định, nếu output đã tồn tại, công cụ sẽ dừng lại và báo lỗi thay vì âm thầm ghi đè, để tránh mất video cũ. |

Ví dụ — render nhanh không phụ đề, giữ tiếng nền, ghi đè output cũ:

```bash
python main.py render --no-subtitles --keep-bg-audio --force
```

Video cuối nằm tại `output/recap_final.mp4`.

---

## Cấu trúc thư mục

```
video-recap-tool/
├── main.py                 # CLI: download / prepare / render
├── config.py                # Đọc config.toml + .env, định nghĩa đường dẫn & key
├── config.toml               # File cấu hình chính (provider/model/scene method/api_key) — không commit key thật lên git công khai
├── config.toml.example       # Mẫu cấu hình, copy thành config.toml
├── .env.example                # Mẫu biến môi trường (tùy chọn, thay thế cho api_key trong config.toml)
├── requirements.txt
├── download.py                 # Tải video bằng yt-dlp
├── scene_detect.py             # Chia cảnh: PySceneDetect + Interval Slicing + xuất JSON/XML/EDL
├── transcribe.py                # Phiên âm: Groq / OpenAI-compatible + trích audio
├── script_gen.py                 # Sinh kịch bản: Google / Groq / OpenAI-compatible + trích JSON an toàn
├── tts.py                          # Text-to-speech: edge-tts + time-stretch (atempo), chạy song song
├── subtitles.py                     # Sinh file .srt
├── sync_assemble.py                   # Ghép audio + video + burn phụ đề bằng ffmpeg
├── modal_app.py                        # Stub triển khai chạy trên Modal.com (cloud)
├── workdir/                             # Tự động tạo — chứa file trung gian (video gốc, transcript, script, phụ đề...)
├── output/                               # Tự động tạo — chứa video recap hoàn chỉnh
└── temp/                                  # Tự động tạo — cache audio trích xuất, audio TTS thô/đã chỉnh
```

`workdir/`, `output/`, `temp/` được tự động tạo lần đầu chạy công cụ (không cần tạo tay).

---

## Định dạng file trung gian

Tất cả nằm trong `workdir/` (trừ output cuối):

| File | Sinh ra ở bước | Nội dung |
|---|---|---|
| `source.mp4` | `prepare` | Bản copy của video gốc, dùng xuyên suốt pipeline |
| `scenes.json` / `.xml` / `.edl` | `prepare` | Danh sách cảnh đã chia, định dạng tùy `scene_detect.output_format` |
| `transcript.json` | `prepare` | Kết quả phiên âm, mỗi phần tử có `start`, `end`, `text` |
| `script_draft.json` | `prepare` | Kịch bản recap do LLM sinh ra — **cần bạn sửa lại** |
| `script_final.json` | Bạn tự tạo (đổi tên từ `script_draft.json` sau khi sửa) | Kịch bản cuối cùng đưa vào TTS |
| `tts_segments.json` | `render` | Danh sách audio TTS đã sinh, kèm đường dẫn file audio đã time-stretch |
| `recap.srt` | `render` | Phụ đề khớp với audio đã đồng bộ |
| `ffmpeg_assemble_error.log` | `render` (chỉ khi lỗi) | Log đầy đủ của ffmpeg khi bước ghép video cuối thất bại |

Output cuối cùng: `output/recap_final.mp4`.

---

## Chạy trên cloud (Modal.com)

`modal_app.py` là một stub cơ bản để triển khai lên [Modal.com](https://modal.com) — build sẵn image có `ffmpeg` và cài đặt từ `requirements.txt`. Hiện tại chỉ có 1 hàm `hello()` để kiểm tra image chạy được; cần tự implement thêm hàm gọi các bước `prepare`/`render` nếu muốn chạy toàn bộ pipeline trên cloud thay vì máy local.

```bash
pip install modal
modal setup            # đăng nhập/tạo token lần đầu
modal run modal_app.py
```

---

## Xử lý sự cố (Troubleshooting)

**Lỗi 401 / Unauthorized khi phiên âm hoặc sinh kịch bản**
→ Kiểm tra `api_key` trong `config.toml` (hoặc biến môi trường tương ứng trong `.env`) đúng với provider đang chọn ở `provider = "..."`. Key rỗng hoặc để đúng format placeholder sẽ luôn báo 401.

**`❌ LỖI NGHIÊM TRỌNG: Không tìm thấy lệnh 'ffmpeg'`**
→ Chưa cài ffmpeg hoặc chưa có trong PATH. Xem lại phần [Yêu cầu hệ thống](#yêu-cầu-hệ-thống).

**`❌ Không tìm thấy source.mp4 trong workdir. Chạy 'prepare' trước.`**
→ Phải chạy `python main.py prepare <video>` thành công trước khi chạy `render`.

**`Dòng N thiếu các trường: {...}`**
→ File `workdir/script_final.json` thiếu `ref_start`, `ref_end` hoặc `text` ở dòng N. Kiểm tra lại JSON, đảm bảo đúng 3 trường bắt buộc ở mọi phần tử.

**Giọng đọc nghe méo/nhanh/chậm bất thường**
→ Kịch bản của bạn viết quá dài hoặc quá ngắn so với khung thời gian cảnh gốc (`ref_end - ref_start`), khiến audio bị time-stretch chạm giới hạn (mặc định 0.5x–2.0x). Cân nhắc viết lại ngắn/dài hơn cho khớp, hoặc nới rộng `ref_start`/`ref_end` sang các cảnh liền kề.

**Lỗi ffmpeg khi ghép video cuối (bước `render`)**
→ Xem log đầy đủ tại `workdir/ffmpeg_assemble_error.log` — thường do đường dẫn file chứa ký tự đặc biệt, codec video gốc không tương thích, hoặc thiếu dung lượng ổ đĩa.

**`❌ output/recap_final.mp4 đã tồn tại. Dùng --force để ghi đè.`**
→ Chủ ý — công cụ không tự ghi đè output cũ. Thêm `--force` nếu chắc chắn muốn ghi đè.

**Video mới nhưng vẫn bị phiên âm/nội dung của video cũ**
→ Rất hiếm gặp sau khi cache audio đã được khóa theo (tên + dung lượng + thời gian sửa đổi file), nhưng nếu vẫn xảy ra, xóa thư mục `temp/` rồi chạy lại `prepare`.

**Muốn đổi giọng đọc tiếng Việt**
→ Xem danh sách giọng có sẵn: `edge-tts --list-voices | grep vi-VN`, rồi đổi `voice_vi` trong `config.toml`.

---

## Giới hạn hiện tại

- Chỉ hỗ trợ TTS qua `edge-tts` (chưa hỗ trợ ElevenLabs, Google TTS, v.v.).
- `download.py` chỉ tải về, không hỗ trợ cắt đoạn theo timestamp URL.
- `modal_app.py` chỉ là stub, chưa implement pipeline đầy đủ trên cloud.
- Chưa có giao diện đồ họa (GUI) — toàn bộ thao tác qua CLI và chỉnh sửa file JSON tay.
- Chưa hỗ trợ đa ngôn ngữ đầu ra (prompt LLM hiện cố định yêu cầu viết kịch bản bằng tiếng Việt).

---

## Giấy phép

Thêm license phù hợp với dự án của bạn tại đây (vd MIT, Apache-2.0...).
