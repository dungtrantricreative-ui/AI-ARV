import json
import shutil
import time
from pathlib import Path

import config
import director
import frame_extract
import llm_client

# Độ trễ (giây) chèn sau MỖI block kịch bản (dù thành công hay lỗi) để giữ
# nhịp độ gọi API trong giới hạn tier hiện tại, tránh bị Cerebras/Gemma (hoặc
# provider LLM/vision khác) khoá tạm thời do gọi quá nhanh (lỗi 429).
API_THROTTLE_SEC = 2.5

# Số ký tự tối đa giữ lại làm "bối cảnh truyện đã kể" truyền sang block kế
# tiếp. Đây là phần cốt lõi để sửa lỗi AI quên mạch truyện giữa các block.
STORY_CONTEXT_MAX_CHARS = 900

# Số dòng thoại gộp mỗi lần gọi LLM ở bước "biên tập lại" (polish pass) cuối
# cùng. Gộp thành từng cụm nhỏ để LLM có đủ ngữ cảnh liền mạch nhưng vẫn
# tránh vượt giới hạn token / để lỗi 1 cụm không làm hỏng toàn bộ kịch bản.
POLISH_CHUNK_SIZE = 14

# Tốc độ nói trung bình khi đọc lời bình tiếng Việt (từ/giây). Dùng để quy
# đổi "ngân sách thời lượng" của 1 block sang "ngân sách số từ" trong prompt,
# giúp LLM tự ước lượng nên viết dài bao nhiêu thay vì kể lể hết mọi chi tiết.
# Giá trị này ước tính từ tốc độ đọc tự nhiên (~150 từ/phút) + rate TTS.
WORDS_PER_SECOND = 2.5


# ============================================================
#  "KIM CHỈ NAM" biên kịch — phần quan trọng nhất của cả file.
#  Toàn bộ lỗi "tả logo, tả góc máy, tả từng câu thoại vô nghĩa"
#  đến từ việc prompt cũ yêu cầu model MÔ TẢ những gì nhìn/nghe thấy.
#  Ở đây ta yêu cầu model HIỂU CHUYỆN rồi KỂ LẠI, giống một biên kịch
#  recap thật sự chứ không phải một cái máy caption.
# ============================================================
STYLE_GUIDE = """Bạn là biên kịch lời bình (voice-over) cho một kênh RECAP PHIM chuyên nghiệp trên YouTube.
Nhiệm vụ của bạn không phải là mô tả những gì xuất hiện trên màn hình, mà là KỂ LẠI CÂU CHUYỆN cho
người xem chưa từng xem phim này, sao cho họ hiểu chuyện gì đang xảy ra và muốn xem tiếp.

TUYỆT ĐỐI KHÔNG được:
- Mô tả logo hãng phim, nhạc hiệu mở đầu, credit, watermark, hiệu ứng chuyển cảnh, hiệu ứng ánh sáng.
- Mô tả góc máy hoặc kỹ thuật quay (toàn cảnh, cận cảnh, máy lia, zoom, tông màu phim...). Người xem
  không quan tâm camera đặt ở đâu, chỉ quan tâm chuyện gì đang xảy ra với nhân vật.
- Dịch/diễn giải máy móc từng câu thoại một cách rời rạc khi chưa hiểu bối cảnh của cả đoạn.
- Viết câu chung chung, sáo rỗng, không có thông tin thật: ví dụ "hai bên thương lượng", "một cuộc đối
  thoại hỗn loạn", "không khí trở nên căng thẳng" mà không nói rõ AI đang làm gì, VÌ SAO, và chuyện đó
  DẪN ĐẾN điều gì. Một câu đọc xong mà người xem vẫn không biết chuyện gì xảy ra là câu hỏng, phải bỏ.
- Kể lể các cảnh chuyển tiếp không ảnh hưởng cốt truyện (xe chạy trên đường, người đi bộ, cảnh thành
  phố về đêm chỉ để chuyển cảnh...). Nếu một đoạn không quan trọng, hãy tóm tắt cực ngắn hoặc bỏ hẳn.

BẮT BUỘC mỗi câu/đoạn lời bình phải ngầm trả lời được 3 câu hỏi:
1. Ai đang làm gì? (nêu đích danh nhân vật + hành động cụ thể, không mô tả ngoại hình/trang phục trừ
   khi thực sự cần để phân biệt nhân vật)
2. Vì sao việc đó quan trọng? (mục tiêu của nhân vật, mâu thuẫn, cảm xúc thật sự đằng sau hành động)
3. Nó dẫn tới điều gì tiếp theo? (hậu quả, nghi vấn, bước ngoặt — thứ khiến người xem muốn xem tiếp)

Chỉ tập trung vào 6 yếu tố: NHÂN VẬT — MỤC TIÊU — MÂU THUẪN — HÀNH ĐỘNG — HẬU QUẢ — BƯỚC NGOẶT.
Văn phong: kể chuyện tự nhiên, mạch lạc, hấp dẫn, như đang kể lại cho một người bạn nghe — không phải
liệt kê hình ảnh, không phải phụ đề dịch thoại.

CHẤM ĐIỂM ĐỘ QUAN TRỌNG: mỗi dòng lời bình bạn viết ra PHẢI kèm một trường "importance" từ 1 đến 5,
do CHÍNH BẠN đánh giá dựa trên nội dung — không có công thức cố định, hãy dùng phán đoán biên kịch:
  5 = bước ngoặt cốt truyện, twist, quyết định thay đổi số phận nhân vật — thiếu câu này khán giả
      SẼ không hiểu mạch phim.
  4 = thông tin quan trọng để hiểu động cơ/nhân vật/mâu thuẫn, nhưng không phải bước ngoặt.
  3 = bổ trợ hữu ích (bối cảnh, cảm xúc) nhưng có thể suy ra được nếu thiếu.
  2 = chi tiết phụ, có cũng hay nhưng cắt cũng không ảnh hưởng mạch hiểu.
  1 = gần như chỉ để chuyển cảnh/lấp chỗ trống, có thể cắt an toàn.
Điểm này sẽ được dùng ở bước biên tập CUỐI CÙNG để cắt bớt video nếu quá dài — bạn KHÔNG cần tự giới
hạn độ dài ở bước này, cứ viết đủ những gì cần để câu chuyện mạch lạc, nhưng hãy chấm điểm trung thực
(đừng chấm mọi câu đều 5) để bước biên tập sau cắt đúng chỗ ít quan trọng nhất, không cắt nhầm cao trào.
"""


def _selectivity_reminder() -> str:
    """Nhắc nhở NHẸ, không ép số từ/giây cụ thể (khác bản cũ dùng ngân sách cứng
    theo % thời lượng block — cách đó dễ cắt cụt những đoạn thực sự quan trọng
    chỉ vì chúng rơi vào 1 block dài). Việc "nén" video giờ được xử lý ở bước
    biên tập TOÀN CỤC sau khi có đủ ngữ cảnh cả câu chuyện, dựa trên điểm
    "importance" — xem _trim_script_to_target."""
    return ("Nhắc lại: đừng kể lể mọi chi tiết nhỏ, chỉ giữ những gì thật sự cần cho mạch truyện. "
            "Đừng quên chấm điểm \"importance\" (1-5) trung thực cho mỗi dòng.")


def _trim_script_to_target(script, target_minutes: float, tolerance: float = 1.15):
    """Bước biên tập TOÀN CỤC cuối cùng: nếu tổng thời lượng ước tính vượt quá
    (target_minutes * tolerance), cắt bớt các dòng ÍT QUAN TRỌNG NHẤT trước
    (importance thấp nhất, và trong cùng mức importance thì cắt dòng dài/tốn
    thời gian hơn trước) cho tới khi về dưới ngưỡng. KHÔNG BAO GIỜ cắt dòng có
    importance >= 4 (bước ngoặt / thông tin cốt lõi) dù có vượt target, vì thà
    video hơi dài hơn dự kiến còn hơn mất mạch truyện. Nếu target_minutes <= 0
    (tắt tính năng) thì giữ nguyên toàn bộ."""
    if not target_minutes or target_minutes <= 0 or not script:
        return script

    def est_duration(line):
        return max(1.0, len(line.get("text", "")) / (WORDS_PER_SECOND * 5.0))
        # ~5 ký tự/từ tiếng Việt trung bình -> chars / (words/s * chars/word) = giây

    target_sec = target_minutes * 60.0
    cap_sec = target_sec * tolerance
    total = sum(est_duration(l) for l in script)
    if total <= cap_sec:
        return script

    # Sắp theo importance tăng dần, cùng importance thì ước lượng thời lượng
    # giảm dần trước (ưu tiên cắt câu vừa ít quan trọng vừa dài, hiệu quả hơn).
    removable_idx = sorted(
        (i for i, l in enumerate(script) if int(l.get("importance", 3) or 3) < 4),
        key=lambda i: (int(script[i].get("importance", 3) or 3), -est_duration(script[i])),
    )
    to_drop = set()
    for i in removable_idx:
        if total <= cap_sec:
            break
        total -= est_duration(script[i])
        to_drop.add(i)

    kept = [l for i, l in enumerate(script) if i not in to_drop]
    print(f"[script_gen] Biên tập toàn cục: kịch bản ước tính ~{ (total + sum(est_duration(script[i]) for i in to_drop)) / 60:.1f} phút "
          f"> mục tiêu {target_minutes:.0f} phút -> cắt {len(to_drop)}/{len(script)} dòng ít quan trọng nhất "
          f"(giữ nguyên mọi dòng importance>=4). Còn lại ước tính ~{total / 60:.1f} phút.")
    return kept


def generate_script(transcript, scenes, out_path: Path, video_path: Path = None):
    print("[script_gen] Đang sinh kịch bản nháp...")

    if not config.DIRECTOR_ENABLED or not scenes:
        script = _generate_script_legacy(transcript, scenes)
    else:
        script = _generate_script_directed(transcript, scenes, video_path)

    script.sort(key=lambda x: x.get("ref_start", 0.0))

    if getattr(config, "SCRIPT_POLISH_ENABLED", True) and script:
        script = _polish_script(script)

    target_minutes = getattr(config, "SCRIPT_TARGET_MINUTES", 0.0)
    if target_minutes and script:
        script = _trim_script_to_target(script, target_minutes)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)
    print(f"[script_gen] Xong: {len(script)} dòng thoại -> {out_path}")
    return script


# ============================================================
#  ĐƯỜNG CHÍNH (director bật): sinh kịch bản theo từng block,
#  block ít thoại -> gửi kèm khung hình cho model vision.
#
#  Điểm sửa quan trọng so với bản cũ: mỗi block giờ nhận thêm
#  `story_so_far` — tóm tắt các diễn biến đã kể ở những block trước —
#  để model không "hiểu nhầm" từng đoạn một cách rời rạc, và giữ được
#  mạch truyện xuyên suốt cả video thay vì chỉ dịch từng khúc transcript.
# ============================================================

def _generate_script_directed(transcript, scenes, video_path: Path):
    blocks = director.plan_scenes(scenes, transcript)
    if not blocks:
        return _generate_script_legacy(transcript, scenes)

    frames_dir = config.TEMP_DIR / "director_frames"
    all_lines = []
    story_so_far = ""
    n_blocks = len(blocks)
    for i, block in enumerate(blocks, 1):
        tag = f"{block['start']:.1f}"
        print(f"[script_gen] Block {i}/{n_blocks}: {block['start']:.1f}s-{block['end']:.1f}s ({block['mode']})")
        try:
            if block["mode"] == "vision" and video_path is not None:
                lines = _generate_vision_block(block, transcript, video_path, frames_dir, tag, story_so_far)
            else:
                lines = _generate_text_block(block, transcript, story_so_far)
        except Exception as e:
            print(f"⚠️ [script_gen] Lỗi ở block {block['start']:.1f}-{block['end']:.1f}s ({e}). "
                  f"Bỏ qua block này (thoại/hình các block khác không bị ảnh hưởng).")
            lines = []
        all_lines.extend(lines)
        story_so_far = _update_story_context(story_so_far, lines)

        # Throttling: chờ giữa các block để không vượt rate limit (429) của
        # provider LLM/vision hiện tại. Chèn kể cả khi block vừa rồi lỗi,
        # vì lỗi đó rất có thể chính là do gọi API quá nhanh.
        if i < n_blocks:
            time.sleep(API_THROTTLE_SEC)

    if frames_dir.exists():
        shutil.rmtree(frames_dir, ignore_errors=True)

    if not all_lines:
        print("⚠️ [script_gen] Không sinh được dòng thoại nào theo director. Dùng lại cách cũ (1 lần gọi toàn bộ transcript).")
        return _generate_script_legacy(transcript, scenes)

    return all_lines


def _update_story_context(story_so_far: str, new_lines, max_chars: int = STORY_CONTEXT_MAX_CHARS) -> str:
    """Nối các câu recap vừa sinh vào phần tóm tắt truyện, cắt bớt phần đầu
    nếu quá dài. Đây là bộ nhớ ngắn hạn giúp block sau biết block trước đã
    kể đến đâu, tránh lặp lại hoặc hiểu sai bối cảnh."""
    added = " ".join(l.get("text", "").strip() for l in new_lines if l.get("text", "").strip())
    if not added:
        return story_so_far
    combined = (story_so_far + " " + added).strip() if story_so_far else added
    if len(combined) > max_chars:
        combined = "...[đầu truyện đã lược bớt]... " + combined[-max_chars:]
    return combined


def _story_context_block(story_so_far: str) -> str:
    if not story_so_far.strip():
        return "(Đây là đoạn đầu tiên, chưa có diễn biến nào được kể trước đó.)"
    return f"Tóm tắt những gì đã xảy ra TRƯỚC đoạn này (để bạn hiểu bối cảnh, không lặp lại):\n{story_so_far}"


def _generate_text_block(block, transcript, story_so_far: str = ""):
    t_block = _format_transcript_range(transcript, block["start"], block["end"])
    prompt = f"""{STYLE_GUIDE}

{_story_context_block(story_so_far)}

Bây giờ hãy viết tiếp lời bình cho đoạn phim từ giây {block['start']:.1f} đến {block['end']:.1f}
(so với video gốc). Dưới đây là thoại nghe được trong đoạn này (transcript thô, CHỈ để bạn hiểu
chuyện gì xảy ra — không được dịch/liệt kê lại từng câu):
{t_block if t_block.strip() else "(không có thoại đáng kể trong đoạn này — có thể đoạn này không quan trọng, hãy cân nhắc tóm tắt cực ngắn hoặc bỏ qua)"}

{_selectivity_reminder()}

Yêu cầu định dạng:
- Trả về JSON array, mỗi phần tử có: ref_start (float), ref_end (float), text (string), importance (int 1-5).
- ref_start >= {block['start']:.1f} và ref_end <= {block['end']:.1f} (phải nằm trong đoạn này).
- Nếu đoạn này không có gì quan trọng với cốt truyện, có thể trả về mảng rỗng [] — đừng cố bịa chuyện.
- Không giải thích gì thêm, chỉ trả về JSON thuần, không kèm markdown/code fence.

Ví dụ định dạng (nội dung chỉ minh hoạ):
[{{"ref_start": {block['start']:.1f}, "ref_end": {min(block['start'] + 4, block['end']):.1f}, "text": "...", "importance": 3}}]
"""
    raw = llm_client.call_text(
        prompt, config.LLM_PROVIDER, config.LLM_MODEL, config.LLM_API_KEY, config.LLM_BASE_URL,
        label="script-text",
    )
    return llm_client.extract_json(raw)


def _generate_vision_block(block, transcript, video_path, frames_dir, tag, story_so_far: str = ""):
    frames = frame_extract.extract_frames(
        video_path, block["start"], block["end"], config.DIRECTOR_FRAMES_PER_BLOCK, frames_dir, tag,
    )
    if not frames:
        print(f"⚠️ [script_gen] Không trích được khung hình nào cho block {tag}s -> lùi về text-only.")
        return _generate_text_block(block, transcript, story_so_far)

    t_block = _format_transcript_range(transcript, block["start"], block["end"])
    prompt = f"""{STYLE_GUIDE}

{_story_context_block(story_so_far)}

Bạn được xem {len(frames)} khung hình đại diện, trích đều nhau từ đoạn phim ÍT/KHÔNG CÓ THOẠI, từ giây
{block['start']:.1f} đến {block['end']:.1f} (so với video gốc). Hãy nhìn các khung hình để HIỂU chuyện
gì đang xảy ra — nhân vật nào, đang làm gì, cảm xúc/mục đích là gì — rồi kể lại đúng tinh thần của
STYLE GUIDE ở trên. TUYỆT ĐỐI không liệt kê những gì nhìn thấy trong ảnh (không mô tả bối cảnh, ánh
sáng, bố cục, màu sắc, góc máy) — chỉ dùng hình ảnh để suy ra diễn biến rồi kể lại bằng lời văn tự nhiên.

Thoại nghe được trong đoạn này (nếu có, có thể rất ít hoặc không có):
{t_block if t_block.strip() else "(không có thoại)"}

{_selectivity_reminder()}

Yêu cầu định dạng:
- Trả về JSON array, mỗi phần tử có: ref_start (float), ref_end (float), text (string), importance (int 1-5).
- ref_start >= {block['start']:.1f} và ref_end <= {block['end']:.1f} (phải nằm trong đoạn này).
- Nếu đoạn này chỉ là cảnh chuyển/không quan trọng, trả về mảng rỗng [] thay vì mô tả cho có.
- Không giải thích gì thêm, chỉ trả về JSON thuần, không kèm markdown/code fence.
"""
    raw = llm_client.call_vision(
        prompt, frames, config.VISION_PROVIDER, config.VISION_MODEL, config.VISION_API_KEY, config.VISION_BASE_URL,
        label="script-vision",
    )
    return llm_client.extract_json(raw)


def _format_transcript_range(transcript, start, end, max_characters=4000):
    text_block = ""
    for entry in transcript:
        e_start, e_end = entry.get("start", 0.0), entry.get("end", 0.0)
        if e_end < start or e_start > end:
            continue
        text_block += f"[{e_start:.1f}-{e_end:.1f}]: {entry.get('text', '')}\n"
    if len(text_block) > max_characters:
        text_block = text_block[:max_characters] + "\n...[LƯỢC BỚT]...\n"
    return text_block


# ============================================================
#  BƯỚC BIÊN TẬP LẠI (polish pass) — chạy SAU khi đã có toàn bộ
#  kịch bản nháp (dù sinh theo director hay theo cách legacy).
#
#  Vì kịch bản được sinh theo từng block riêng lẻ (để kiểm soát chi phí
#  API), câu văn ở ranh giới giữa các block đôi khi vẫn hơi rời rạc, và
#  model đôi khi vẫn lọt vài câu sáo rỗng dù đã có STYLE_GUIDE. Bước này
#  gộp các dòng thành từng cụm liền mạch và nhờ LLM biên tập lại câu chữ
#  cho trôi chảy, cắt bỏ mọi câu chung chung không mang thông tin, mà
#  KHÔNG đổi số lượng dòng hay mốc thời gian ref_start/ref_end (để không
#  làm lệch đồng bộ audio/phụ đề khi render).
#
#  An toàn: nếu bước này lỗi hoặc LLM trả về sai số dòng, GIỮ NGUYÊN cụm
#  gốc thay vì làm hỏng/làm lệch kịch bản.
# ============================================================

def _polish_script(script):
    print(f"[script_gen] Biên tập lại kịch bản cho mạch lạc hơn ({len(script)} dòng)...")
    polished = []
    story_so_far = ""
    for start in range(0, len(script), POLISH_CHUNK_SIZE):
        chunk = script[start:start + POLISH_CHUNK_SIZE]
        try:
            new_texts = _polish_chunk(chunk, story_so_far)
        except Exception as e:
            print(f"⚠️ [script_gen] Bước biên tập lỗi ở cụm dòng {start}-{start + len(chunk)} ({e}). "
                  f"Giữ nguyên cụm gốc.")
            new_texts = None

        if new_texts is not None and len(new_texts) == len(chunk):
            for line, new_text in zip(chunk, new_texts):
                line = dict(line)
                if new_text.strip():
                    line["text"] = new_text.strip()
                polished.append(line)
        else:
            if new_texts is not None:
                print(f"⚠️ [script_gen] Bước biên tập trả sai số dòng ({len(new_texts)} thay vì {len(chunk)}) "
                      f"ở cụm {start}-{start + len(chunk)}. Giữ nguyên cụm gốc.")
            polished.extend(chunk)

        story_so_far = _update_story_context(story_so_far, polished[-len(chunk):])
        if start + POLISH_CHUNK_SIZE < len(script):
            time.sleep(API_THROTTLE_SEC)

    # Bỏ các dòng bị biên tập thành rỗng (LLM đánh giá là câu thừa/sáo rỗng)
    polished = [l for l in polished if l.get("text", "").strip()]
    return polished


def _polish_chunk(chunk, story_so_far: str):
    numbered = "\n".join(f"{idx}: {l.get('text', '')}" for idx, l in enumerate(chunk))
    prompt = f"""{STYLE_GUIDE}

{_story_context_block(story_so_far)}

Dưới đây là {len(chunk)} câu lời bình recap đang ở dạng NHÁP, được đánh số thứ tự 0..{len(chunk) - 1},
theo đúng thứ tự sẽ đọc lên (KHÔNG được đổi thứ tự, không được gộp/tách câu):
{numbered}

Hãy biên tập lại CHÍNH XÁC {len(chunk)} câu này cho mạch lạc, hấp dẫn, đúng tinh thần STYLE GUIDE ở
trên: xoá bỏ câu sáo rỗng/chung chung không mang thông tin, nối câu cho trôi chảy với bối cảnh đã kể
trước đó, đảm bảo mỗi câu đều rõ AI-làm gì-vì sao-dẫn đến gì. Nếu một câu thực sự thừa/không cần thiết
(chỉ là cảnh chuyển, không ảnh hưởng cốt truyện), hãy trả về chuỗi rỗng "" cho câu đó thay vì xoá hẳn
khỏi danh sách — số lượng phần tử trả về PHẢI đúng bằng {len(chunk)}.

Trả về CHÍNH XÁC 1 JSON array gồm {len(chunk)} chuỗi (string), theo đúng thứ tự 0..{len(chunk) - 1}.
Không giải thích gì thêm, chỉ trả JSON thuần, không kèm markdown/code fence.
Ví dụ định dạng: ["câu đã biên tập 0", "câu đã biên tập 1", ...]
"""
    raw = llm_client.call_text(
        prompt, config.LLM_PROVIDER, config.LLM_MODEL, config.LLM_API_KEY, config.LLM_BASE_URL,
        temperature=0.5, label="script-polish",
    )
    return llm_client.extract_json_array_of_strings(raw)


# ============================================================
#  ĐƯỜNG LÙI (legacy, director tắt hoặc thất bại hoàn toàn):
#  y hệt hành vi cũ — 1 lần gọi LLM cho toàn bộ transcript, nhưng vẫn
#  dùng chung STYLE_GUIDE để chất lượng không bị tụt so với đường chính.
# ============================================================

def _format_transcript(transcript, max_characters=20000):
    text_block = ""
    for entry in transcript:
        text_block += f"[{entry.get('start', 0.0):.1f}-{entry.get('end', 0.0):.1f}]: {entry.get('text', '')}\n"
    if len(text_block) > max_characters:
        print(f"⚠️ Transcript quá dài ({len(text_block)} ký tự). Rút gọn thông minh...")
        half = max_characters // 2
        text_block = text_block[:half] + "\n...[LƯỢC BỎ ĐỂ TRÁNH TRÀN CONTEXT]...\n" + text_block[-half:]
    return text_block


def format_scenes_block(scenes):
    scenes_block = ""
    for idx, scene in enumerate(scenes):
        scenes_block += f"Cảnh {idx + 1}: {scene['start']:.1f}s -> {scene['end']:.1f}s\n"
    return scenes_block


def _build_prompt(transcript, scenes):
    t_block = _format_transcript(transcript)
    s_block = format_scenes_block(scenes)
    prompt = f"""{STYLE_GUIDE}

Dưới đây là transcript và danh sách cảnh của toàn bộ video. Hãy kể lại thành kịch bản recap theo đúng
tinh thần STYLE GUIDE ở trên — hiểu cốt truyện rồi kể lại, không dịch/mô tả từng câu/từng cảnh rời rạc.

Transcript:
{t_block}

Danh sách cảnh:
{s_block}

Yêu cầu định dạng:
- Trả về JSON array, mỗi phần tử có: ref_start (float), ref_end (float), text (string).
- ref_start/ref_end phải nằm trong khoảng thời gian của một cảnh cụ thể.
- Bỏ qua hoàn toàn các cảnh chuyển/không quan trọng — không cần một dòng thoại cho mỗi cảnh.
- Không giải thích gì thêm, chỉ trả về JSON thuần, không kèm markdown/code fence.

Ví dụ định dạng (nội dung chỉ minh hoạ):
[
  {{"ref_start": 0.0, "ref_end": 4.2, "text": "..."}}
]
"""
    return prompt


def _generate_script_legacy(transcript, scenes):
    prompt = _build_prompt(transcript, scenes)
    raw = llm_client.call_text(
        prompt, config.LLM_PROVIDER, config.LLM_MODEL, config.LLM_API_KEY, config.LLM_BASE_URL,
        label="script-legacy",
    )
    return llm_client.extract_json(raw)
