# Video Recap Tool — recap phim có gu riêng

Pipeline bán tự động: AI lo phần lao động nặng (tải, dịch, dựng), bạn lo phần
"linh hồn" (sửa kịch bản theo phong cách riêng). Có một checkpoint bắt buộc
giữa pipeline để bạn sửa script trước khi AI đọc và ghép — đây là bước quyết
định cả chất lượng lẫn khả năng sống sót về mặt chính sách/kiếm tiền.

## Kiến trúc

```
1. Tải video          yt-dlp
2. Chia cảnh           PySceneDetect
3. Phiên âm+timestamp  ASR provider cấu hình qua config.toml
4. Sinh script nháp    LLM provider cấu hình qua config.toml
   ── CHECKPOINT: bạn sửa script_draft.json -> script_final.json ──
5. TTS + neo mốc       edge-tts + ffmpeg atempo (mỗi dòng neo đúng vị trí gốc)
6. Sinh phụ đề         .srt khớp với audio đã sync
7. Ghép video cuối     ffmpeg (adelay + amix + burn sub)
```

### Vì sao "neo mốc tuyệt đối" quan trọng

TTS đọc không bao giờ khớp đúng độ dài đoạn video gốc. Nếu chỉ nối các đoạn
audio liên tiếp, sai số cộng dồn qua cả phim, càng về cuối càng lệch xa cảnh.
Giải pháp ở đây: mỗi dòng script giữ `ref_start`/`ref_end` — timestamp GỐC
của đoạn nó đang tóm tắt. TTS được time-stretch (`atempo`) để khớp đúng
khoảng đó, rồi đặt vào **vị trí tuyệt đối** trên timeline cuối (giống cách
phụ đề hoạt động), không nối chuỗi. Vì vậy sai số chỉ giới hạn trong phạm vi
từng dòng, không cộng dồn.

## Cài đặt (chạy local)

```bash
git clone <repo-url> && cd video-recap-tool
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Cần cài `ffmpeg` ở máy (không nằm trong requirements.txt vì là binary hệ
thống, không phải package Python):
- macOS: `brew install ffmpeg`
- Ubuntu/Debian: `sudo apt install ffmpeg`
- Windows: tải từ https://ffmpeg.org và thêm vào PATH

Tạo file `.env` để chứa API key. Có 2 cách đặt tên:
- Generic: `ASR_API_KEY`, `LLM_API_KEY`
- Hoặc theo provider: `GROQ_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`

Ví dụ:

```env
ASR_API_KEY=your_asr_key
LLM_API_KEY=your_llm_key
```

Một số nơi lấy key:
- Groq — https://console.groq.com/keys
- Google AI Studio — https://aistudio.google.com/apikey
- OpenAI — https://platform.openai.com/api-keys

## Cấu hình bằng `config.toml`

Project giờ đọc provider/model/base_url từ `config.toml`.

Ví dụ mặc định:

```toml
[asr_service]
provider = "groq"
base_url = "https://api.groq.com"
api_key = ""
model = "whisper-large-v3"

[llm_service]
provider = "google"
base_url = "https://generativelanguage.googleapis.com"
api_key = ""
model = "gemini-2.0-flash-exp"

[tts_service]
provider = "edge"
voice_vi = "vi-VN-NamMinhNeural"

[directories]
work_dir = "workdir"
output_dir = "output"
```

Ví dụ đổi sang OpenAI:

```toml
[asr_service]
provider = "openai"
base_url = "https://api.openai.com/v1"
api_key = ""
model = "whisper-1"

[llm_service]
provider = "openai"
base_url = "https://api.openai.com/v1"
api_key = ""
model = "gpt-4o-mini"
```

## Chạy (local)

```bash
# Bước 1-4: tải, chia cảnh, phiên âm, sinh script nháp
python main.py prepare "https://youtube.com/watch?v=..."

# --- CHECKPOINT ---
# Mở workdir/script_draft.json, sửa "text" theo gu riêng của bạn.
# Lưu thành workdir/script_final.json

# Bước 5-7: TTS, neo mốc, ghép video
python main.py render
```

Video cuối nằm ở `output/recap_final.mp4`.

Tuỳ chọn:
- `main.py render --no-subtitles` — không burn phụ đề (render nhanh hơn, giữ nguyên codec video)
- `main.py render --keep-bg-audio` — giữ tiếng gốc ở mức nhỏ làm nền thay vì tắt hẳn
- `--force` ở cả 2 lệnh để chạy lại bước dù đã có cache (mặc định resume để đỡ tốn API khi test)

## Cấu trúc project

```
video-recap-tool/
├── main.py                    # CLI local: prepare / render
├── modal_app.py               # Bản cloud (Modal.com)
├── config.toml                # Chọn provider/model/base_url
├── config.py                  # Parse config.toml + env
├── requirements.txt
├── .env.example
└── pipeline/
    ├── download.py             # bước 1: yt-dlp
    ├── scene_detect.py         # bước 2: PySceneDetect
    ├── transcribe.py           # bước 3: ASR đa provider
    ├── script_gen.py           # bước 4: sinh script + gán ref_start/ref_end
    ├── tts.py                  # bước 5: TTS + atempo neo mốc
    ├── subtitles.py            # sinh .srt
    └── sync_assemble.py        # bước 7: ghép video cuối
```

## Rủi ro cần biết về kiếm tiền

- YouTube 2026 siết chặt "reused content" và nội dung sản xuất hàng loạt
  (giọng AI + không bình luận thật + đăng tần suất cao).
- Phim có bản quyền gần như chắc chắn dính Content ID — doanh thu có thể
  chảy về hãng phim, không phải bạn.
- Sửa script thôi **chưa đủ** để an toàn. Cần thêm: phong cách dựng/overlay
  riêng, tần suất đăng vừa phải, gắn nhãn AI-generated đầy đủ, và chiều sâu
  phân tích thật (không chỉ đổi cách diễn đạt).
- Kết luận: kiếm tiền được, nhưng không "ổn định" kiểu cứ chạy máy là có
  tiền — nó sống nhờ bạn liên tục giữ yếu tố con người + tuân thủ chính sách.

## Giới hạn hiện tại / việc có thể làm thêm

- `script_gen.py` yêu cầu model trả JSON đúng định dạng — với phim dài,
  transcript lớn có thể vượt context window, cần thêm bước chia nhỏ theo
  từng chương/hồi rồi gộp lại.
- Timestamp hiện đang dùng granularities theo segment (câu/cụm), không phải
  từng từ. Nếu cần chính xác hơn, có thể thêm WhisperX align chạy trên GPU T4
  (Modal) như bước mở rộng.
- Chưa có bước tự động overlay/watermark phong cách riêng — nên thêm ở
  bước `sync_assemble.py` (ffmpeg `-vf overlay=...`) nếu muốn.
