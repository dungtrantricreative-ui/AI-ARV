# Video Recap Tool — recap phim có gu riêng

Pipeline bán tự động: AI lo phần lao động nặng (tải, dịch, dựng), bạn lo phần
"linh hồn" (sửa kịch bản theo phong cách riêng). Có một checkpoint bắt buộc
giữa pipeline để bạn sửa script trước khi AI đọc và ghép — đây là bước quyết
định cả chất lượng lẫn khả năng sống sót về mặt chính sách/kiếm tiền.

## Kiến trúc

```
1. Tải video          yt-dlp
2. Chia cảnh           PySceneDetect
3. Phiên âm+timestamp  Groq Whisper API (free)
4. Sinh script nháp    Gemini/Gemma qua Google AI Studio (free)
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

Copy `.env.example` thành `.env`, điền API key (đều free):
- `GROQ_API_KEY` — https://console.groq.com/keys
- `GOOGLE_API_KEY` — https://aistudio.google.com/apikey

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

## Chạy trên cloud (Modal.com)

Dùng khi không muốn bật máy cá nhân, hoặc chạy hàng loạt. Máy bạn chỉ gửi
lệnh, mọi xử lý nặng nằm trên Modal (free ~$30 credit/tháng, không cần thẻ).

```bash
pip install modal
modal setup
modal secret create my-api-keys GROQ_API_KEY=xxx GOOGLE_API_KEY=xxx

modal run modal_app.py --url "https://youtube.com/..." --step prepare
# sửa script: modal volume get video-recap-workdir workdir/script_draft.json .
# rồi:        modal volume put video-recap-workdir script_final.json workdir/script_final.json
modal run modal_app.py --step render
# tải video: modal volume get video-recap-workdir output/recap_final.mp4 .
```

Không cần GPU — ASR (Groq) và sinh script (Google AI Studio) đều là API
cloud, phần còn lại (tải video, ffmpeg) chỉ cần CPU.

## Cấu trúc project

```
video-recap-tool/
├── main.py                    # CLI local: prepare / render
├── modal_app.py               # Bản cloud (Modal.com)
├── config.py                  # API key, đường dẫn, tham số
├── requirements.txt
├── .env.example
└── pipeline/
    ├── download.py             # bước 1: yt-dlp
    ├── scene_detect.py         # bước 2: PySceneDetect
    ├── transcribe.py           # bước 3: Groq Whisper API
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
- Timestamp từ Groq là theo segment (câu/cụm), không phải từng từ. Nếu cần
  chính xác hơn, có thể thêm WhisperX align chạy trên GPU T4 (Modal) như
  bước mở rộng.
- Chưa có bước tự động overlay/watermark phong cách riêng — nên thêm ở
  bước `sync_assemble.py` (ffmpeg `-vf overlay=...`) nếu muốn.
