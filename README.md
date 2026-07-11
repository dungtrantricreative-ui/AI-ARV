# 🤖 AI-ARV AGENT: HỆ THỐNG DỰNG PHIM RECAP THÔNG MINH

**AI-ARV** là một trợ lý AI trò chuyện giúp tự động hoá toàn bộ quy trình dựng video recap từ
video dài (phim, livestream, vlog...): phân tích cảnh quay, phiên âm, soạn kịch bản lời bình,
đọc giọng AI (TTS), ghép phụ đề và render ra video hoàn chỉnh — chỉ bằng vài câu chat tiếng Việt
tự nhiên với AI, không cần nhớ lệnh.

Chạy được trên **Windows, Linux, macOS** và các máy ảo/notebook cloud (Colab, Kaggle, RunPod...).
Không phụ thuộc vào bất kỳ nền tảng cụ thể nào — mọi phần "nặng" (phiên âm, viết kịch bản, đọc
giọng) đều gọi qua API cloud, máy của bạn chỉ cần chạy Python + FFmpeg.

---

## 🌟 Tính năng nổi bật

- **Agent hội thoại tự nhiên**: không cần lệnh cố định, chỉ cần nói "đây là phim cần làm", "lên
  phim thôi", "xem trong thư mục có gì"... AI tự hiểu ý định và thực thi.
- **Nhận video tự động**: dán link YouTube (tự tải bằng `yt-dlp`) hoặc đường dẫn file cục bộ.
- **Scene detection**: chia video thành các đoạn nhỏ, hỗ trợ 2 chế độ — `interval` (cắt đều theo
  giây, cực nhanh, không decode video) hoặc `content` (PySceneDetect, chính xác hơn theo thay đổi
  hình ảnh thật, chậm hơn).
- **"AI trưởng nhóm" (director)**: tự quyết định đoạn nào chỉ cần đọc transcript (rẻ, nhanh) và
  đoạn nào cần "xem" thêm vài khung hình đại diện qua model vision (đắt hơn nhưng cần thiết cho
  đoạn ít/không thoại). Có van an toàn tự nới ngưỡng nếu tỉ lệ vision vượt quá cấu hình, tránh đội
  chi phí khi gặp phim hành động ít thoại. Mỗi lần gọi vision gửi 1 đoạn text (thoại nghe được) +
  mặc định 2 khung hình lấy CÀNG CÁCH XA NHAU CÀNG TỐT về thời điểm (1 khung gần đầu, 1 khung gần
  cuối đoạn — chỉnh qua `frame_edge_margin`), để model SO SÁNH được thay đổi giữa 2 thời điểm thay
  vì suy đoán từ 1 ảnh tĩnh, giúp hiểu đúng diễn biến/ngữ cảnh hơn.
- **Biên kịch AI theo phong cách "kể chuyện"**: không dịch/liệt kê từng câu thoại hay mô tả góc
  máy — yêu cầu model hiểu chuyện rồi kể lại như một biên tập viên recap thật sự (nhân vật – mục
  tiêu – mâu thuẫn – hành động – hậu quả – bước ngoặt).
- **Tự cân bằng độ dài video theo nội dung**: mỗi câu lời bình được AI tự chấm điểm mức độ quan
  trọng (`importance` 1-5). Sau khi có toàn bộ kịch bản, nếu tổng thời lượng vượt quá mục tiêu
  (`target_minutes` trong config, mặc định 20 phút) thì mới cắt bớt — và **chỉ cắt những câu ít
  quan trọng nhất trước**, không bao giờ đụng đến các câu chứa bước ngoặt/thông tin cốt lõi. Đặt
  `target_minutes = 0` để tắt hẳn, giữ nguyên kịch bản dài bao nhiêu tuỳ nội dung.
- **TTS giọng Việt miễn phí**: dùng Edge TTS (Microsoft, miễn phí, ổn định), có thể chỉnh tốc độ
  đọc nhanh/chậm qua config mà không cần sửa code.
- **Render single-pass kiểu Premiere (mặc định)**: 1 tiến trình ffmpeg DUY NHẤT chạy tuần tự hết
  timeline — trim từng đoạn khớp lời bình, ghép, trộn audio TTS/nhạc nền, và burn phụ đề (nếu bật)
  TRONG CÙNG 1 LẦN CHẠY, source video chỉ decode/encode đúng 1 lần. Nhẹ CPU/RAM hơn nhiều cho máy
  yếu so với việc mở song song nhiều tiến trình ffmpeg, và nhanh hơn vì bỏ được 1 lượt re-encode.
  Nếu lỗi (vd video nguồn hỏng giữa file), tự động lùi về chế độ `segmented` (cắt song song đa
  luồng → ghép bằng concat demuxer → trộn audio/phụ đề) — có thể bật thẳng chế độ này qua
  `[render] mode = "segmented"` nếu máy nhiều nhân CPU muốn tận dụng tối đa song song hoá. Tự dùng
  GPU NVIDIA qua NVENC nếu máy có. Log tiến trình % + ETA theo thời gian thực, có màu để dễ theo dõi.
- **Tự phục hồi lỗi**: đoạn video cắt lỗi sẽ tự thử lại, nếu vẫn lỗi thì chèn khung hình đen đúng
  thời lượng thay vì bỏ đoạn, để audio và hình không bị trôi lệch nhau ở các đoạn phía sau. Vision
  API lỗi thì tự lùi về text-only cho đúng đoạn đó, không làm chết cả pipeline.
- **Log có màu**: vàng = cảnh báo, đỏ = lỗi, xanh lá = thành công, cyan = tiến trình, tím = từng
  dòng TTS — tự tắt màu nếu log bị redirect ra file hoặc set biến môi trường `NO_COLOR`.

---

## 🛠 Cài đặt

### 1. FFmpeg (bắt buộc)

**Windows:**
1. Tải `ffmpeg-git-full.7z` tại [gyan.dev](https://www.gyan.dev/ffmpeg/builds/).
2. Giải nén (ví dụ `C:\ffmpeg`), thêm thư mục `bin` vào **Environment Variables (PATH)**.
3. Kiểm tra bằng `ffmpeg -version` trong Command Prompt.

**Linux / macOS / cloud notebook:**
```bash
sudo apt update && sudo apt install ffmpeg -y   # Debian/Ubuntu
# hoặc: brew install ffmpeg                      # macOS
```

### 2. Thư viện Python

Yêu cầu Python ≥ 3.9.
```bash
pip install -r requirements.txt
```

### 3. Cấu hình API key

1. Copy `config.toml.example` thành `config.toml`.
2. Điền API key của bạn vào các mục cần dùng:
   - `asr_service` — phiên âm giọng nói (khuyên dùng Groq Whisper: rẻ/miễn phí, cực nhanh).
   - `llm_service` — soạn kịch bản (Gemini có tier miễn phí hào phóng; Cerebras/Groq/OpenAI cũng
     dùng được, chỉ cần tương thích chuẩn OpenAI API).
   - `vision_service` — model xem ảnh, dùng cho các đoạn ít/không thoại. Có thể để trống để dùng
     chung config với `llm_service` nếu model đó đã hỗ trợ vision (ví dụ Cerebras Gemma).
   - `tts_service` — mặc định dùng Edge TTS (miễn phí, không cần key).

> ⚠️ **Không commit `config.toml` chứa key thật lên kho công khai (GitHub, Zalo, Drive share...).**
> Nếu key từng bị lộ, hãy thu hồi (revoke) và tạo key mới ngay trên dashboard của nhà cung cấp.

### 4. (Tuỳ chọn) Chạy trên máy/cloud có GPU

Không bắt buộc — pipeline chạy tốt trên CPU thuần, chỉ là bước render sẽ chậm hơn với phim dài.
Nếu môi trường của bạn có GPU NVIDIA (vật lý hoặc cloud), hệ thống **tự dò và dùng NVENC** để tăng
tốc encode mà không cần cấu hình gì thêm — chỉ cần đảm bảo GPU đã được bật/chọn trong cấu hình môi
trường tương ứng của nền tảng bạn đang chạy.

---

## 🚀 Cách dùng

### Chế độ Agent hội thoại (khuyên dùng)
```bash
python main.py
```
AI sẽ chào bạn và chờ bạn dán video. Quy trình:

1. **Đưa video**: dán link YouTube hoặc đường dẫn file cục bộ (`.mp4`/`.mkv`/`.avi`/`.mov`). AI tự
   tải/copy video rồi chạy tuần tự: tách cảnh → phiên âm → soạn kịch bản nháp tại
   `workdir/script_draft.json`.
2. **(Tuỳ chọn) Sửa kịch bản**: mở `workdir/script_draft.json`, chỉnh nội dung lời bình nếu muốn,
   lưu thành `workdir/script_final.json`. Nếu bỏ qua bước này, hệ thống sẽ tự copy bản nháp làm
   bản final khi render.
3. **Ra lệnh render**: gõ `render`, `render now`, `lên phim thôi`, hoặc bất kỳ câu nào có ý đó — AI
   tự nhận diện ý định, không cần đúng từ khoá. Video hoàn chỉnh xuất ra tại
   `output/recap_final.mp4`.

AI cũng có thể chạy lệnh terminal đơn giản hộ bạn (kiểm tra file, dọn thư mục...) ngay trong khung
chat — **cẩn thận khi để AI tự thực thi lệnh can thiệp hệ thống sâu** (xoá file, format...).

### Chế độ dòng lệnh (không qua chat)
```bash
python main.py render
```
Render trực tiếp từ `workdir/script_final.json` (hoặc `script_draft.json` nếu chưa có bản final)
đã có sẵn từ lần chạy trước — dùng khi bạn chỉ muốn render lại mà không cần chat lại từ đầu.

> Chế độ Agent (chat) hoặc subcommand `render` là 2 cách hoạt động chính thức hiện tại của `main.py`.

---

## ⚙️ Các cấu hình đáng chú ý trong `config.toml`

| Mục | Ý nghĩa |
|---|---|
| `[script] target_minutes` | Trần mềm cho thời lượng video đích (phút). Không ép cứng từng đoạn — chỉ cắt câu ít quan trọng nhất ở bước biên tập cuối nếu vượt. `0` = tắt. |
| `[script] block_throttle_seconds` | "Tốc độ gửi block": độ trễ (giây) giữa mỗi lần gọi API khi soạn kịch bản theo block. Giảm để soạn nhanh hơn (dễ dính 429 hơn), tăng nếu hay bị rate-limit. |
| `[director] max_text_block_seconds` | Gộp bao nhiêu giây transcript liền kề vào 1 lần gọi LLM. Tăng lên → ít lần gọi API hơn (nhanh hơn), nhưng cần model chịu được ngữ cảnh dài hơn. |
| `[director] max_vision_ratio` | Trần tỉ lệ thời lượng phim được xử lý bằng vision (đắt hơn text). Tự nới ngưỡng tối đa 3 lần nếu phim quá ít thoại. |
| `[director] frames_per_block` | Số khung hình gửi kèm mỗi block vision (mặc định `2`). |
| `[director] frame_edge_margin` | Tỉ lệ lùi vào từ 2 mép block khi chọn vị trí khung hình (mặc định `0.15` = 15%-85%, tức khung đầu/cuối cách xa nhau tối đa để dễ so sánh thay đổi). |
| `[tts_service] rate` | Tốc độ đọc, ví dụ `"+5%"` nhanh hơn 5%, `"-10%"` chậm hơn 10%. |
| `[render] mode` | `"single_pass"` (mặc định, khuyến nghị cho máy yếu — 1 tiến trình ffmpeg kiểu Premiere) hoặc `"segmented"` (bản cũ, cắt song song đa luồng — dùng cho máy nhiều nhân CPU, cũng là phương án dự phòng tự động). |
| `[render] preset` / `crf` | Preset x264 càng nhanh (`ultrafast` → `veryslow`) thì render càng nhanh nhưng nén kém hơn ở cùng `crf`; bù lại bằng giảm `crf` 1-2 đơn vị nếu cần giữ chất lượng. |
| `[render] force_encoder` | Để trống để tự dò GPU NVENC/CPU libx264; ép `"libx264"` hoặc `"h264_nvenc"` nếu muốn chỉ định cứng. |
| `[render] max_parallel_segments` | Chỉ áp dụng khi `mode = "segmented"`. Số luồng cắt song song, `0` = tự động theo số nhân CPU. |
| `[subtitle] enabled` | Bật/tắt gắn phụ đề SRT khi render. |
| `[scene_detect] method` | `"interval"` (nhanh, mặc định) hoặc `"content"` (PySceneDetect, chính xác hơn nhưng chậm hơn). |

---

## 📂 Cấu trúc dự án

```
main.py               Điểm khởi động: vòng lặp Agent hội thoại + lệnh render CLI
agent_manager.py       "Bộ não" hội thoại — nhận diện ý định người dùng bằng LLM, chạy lệnh terminal
config.py              Đọc config.toml, quản lý đường dẫn (workdir/, temp/, output/)
logutil.py              Log có màu dùng chung cho toàn bộ pipeline
download.py             Tải video từ URL bằng yt-dlp
scene_detect.py         Tách cảnh (interval FFmpeg hoặc PySceneDetect)
transcribe.py           Phiên âm audio -> transcript (ASR, tự cắt đoạn dài thành chunk)
director.py             "AI trưởng nhóm": phân loại đoạn nào cần text-only / cần vision
frame_extract.py        Trích khung hình đại diện cho các đoạn cần vision
script_gen.py            Soạn kịch bản lời bình (theo block, có story context xuyên suốt + polish pass)
llm_client.py            Lớp gọi LLM dùng chung (text + vision), tự retry/backoff
tts.py                   Sinh giọng đọc AI (Edge TTS) cho từng dòng kịch bản
subtitles.py             Xuất file phụ đề .srt từ các đoạn TTS
sync_assemble.py          Ghép video + audio + phụ đề + nhạc nền thành file cuối (single-pass mặc định,
                          tự lùi về chế độ segmented 3 giai đoạn nếu single-pass lỗi)
config.toml.example       File mẫu để copy thành config.toml
workdir/                   File trung gian: source.mp4, scenes.json, transcript.json, script_*.json, recap.srt
temp/                       File tạm trong lúc xử lý (audio chunk, khung hình trích, đoạn video cắt dở)
output/                     Video kết quả cuối cùng (recap_final.mp4)
```

---

## ⚠️ Lưu ý quan trọng

- **Lỗi "moov atom"**: video bị hỏng hoặc tải chưa xong — tải lại file gốc.
- **Tốc độ xử lý** phụ thuộc độ dài video, tốc độ mạng (gọi API cloud), và cấu hình máy — đặc biệt
  bước render (re-encode từng đoạn) là phần tốn thời gian nhất nếu không có GPU.
- **Bảo mật API key**: đừng chia sẻ `config.toml` chứa key thật; dùng biến môi trường hoặc `.env`
  (được hỗ trợ sẵn qua `python-dotenv`) nếu cần tách key ra khỏi file cấu hình.
- **Quyền terminal của Agent**: AI có thể chạy lệnh shell khi bạn yêu cầu kiểm tra hệ thống — kiểm
  soát cẩn thận nếu chạy trên máy có dữ liệu nhạy cảm.
- **Rate limit API free tier**: các provider miễn phí (Groq, Cerebras...) có giới hạn số lần gọi;
  hệ thống đã có retry/backoff tự động nhưng vẫn có thể gặp lỗi 429 nếu dùng key free tier cho phim
  quá dài — cân nhắc tăng `max_text_block_seconds` để giảm số lần gọi, hoặc dùng key trả phí.
