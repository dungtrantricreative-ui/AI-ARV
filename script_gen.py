import json
import re
import shutil
import time
from pathlib import Path

import config
import logutil
import director
import frame_extract
import llm_client

# Model doi khi lo tay viet luon nhan importance vao ben trong field text
# (thay vi de rieng o field "importance" nhu da yeu cau), vi du:
#   "...anh ta chay tron. importance: 4"
#   "...anh ta chay tron. (Importance: 4)"
# TTS sau do doc y nguyen field text nay len -> lo ra "importance x" khi nghe.
# Regex duoi day don sach moi bien the cua nhan nay o cuoi cau.
_IMPORTANCE_LEAK_RE = re.compile(
    r"[\.\s]*\(?\s*importance\s*[:\-]?\s*[1-5]\s*\)?\s*\.?\s*$", re.IGNORECASE
)


def _strip_importance_leak(text: str) -> str:
    return _IMPORTANCE_LEAK_RE.sub("", text or "").strip()


def _sanitize_script(script):
    for line in script:
        if "text" in line:
            line["text"] = _strip_importance_leak(line["text"])
    return script

# Độ trễ (giây) chèn sau MỖI block kịch bản (dù thành công hay lỗi) để giữ
# nhịp độ gọi API trong giới hạn tier hiện tại, tránh bị Cerebras/Gemma (hoặc
# provider LLM/vision khác) khoá tạm thời do gọi quá nhanh (lỗi 429).
# Giờ đọc từ config ([script] block_throttle_seconds trong config.toml) để
# chỉnh "tốc độ gửi block" mà không cần sửa code — xem config.py.
API_THROTTLE_SEC = config.SCRIPT_BLOCK_THROTTLE_SEC

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

BẮT BUỘC câu dẫn khi ĐỔI TUYẾN NHÂN VẬT: khi đoạn bạn đang viết chuyển sang một nhân vật/tuyến truyện
khác với đoạn ngay trước đó (không phải tiếp tục cùng một cảnh/nhân vật), câu đầu tiên của đoạn PHẢI
có một cụm dẫn dắt ngắn để người xem biết mạch truyện vừa chuyển hướng — ví dụ "Trong khi đó, ở...",
"Cùng lúc này, [tên nhân vật]...", "Về phía [tên nhân vật]...", "Quay lại với...". KHÔNG được nhảy
thẳng vào hành động của nhân vật mới mà không có câu dẫn, vì người xem sẽ bị hụt hẫng không hiểu vì
sao đang xem cảnh này lại nhảy sang cảnh khác.

BẮT BUỘC dựng bối cảnh cho khán giả chưa biết phim: nếu đây là những câu ĐẦU TIÊN của cả kịch bản
(mở đầu phim), hoặc là lần đầu một nhân vật/địa điểm quan trọng xuất hiện, phải giới thiệu ngắn gọn
đó là ai/ở đâu/bối cảnh gì trước khi kể hành động — đừng giả định người xem đã biết. Một kịch bản
recap tốt phải khiến người xem chưa từng xem phim vẫn hiểu được ngay từ phút đầu tiên.

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


# ============================================================
#  3 CHẾ ĐỘ RECAP — mỗi mode có "phụ lục" riêng nối vào STYLE_GUIDE, cộng
#  với các tham số điều khiển thuật toán khác nhau (kích thước block, ngưỡng
#  bảo vệ khi cắt, có bật bước GỘP DÒNG hay không). Đây là phần cốt lõi để
#  cùng 1 pipeline sinh ra 3 "gu biên tập" khác hẳn nhau từ CÙNG một nguồn
#  transcript/scene, thay vì chỉ đổi mỗi con số target_minutes.
# ============================================================

_FAST_STYLE_ADDENDUM = """
--- PHỤ LỤC CHẾ ĐỘ "RECAP NHANH" (đang bật) ---
Đây là bản recap SIÊU TÓM TẮT, mục tiêu DUY NHẤT là giúp người xem NẮM ĐƯỢC CỐT TRUYỆN CHÍNH trong
thời gian ngắn nhất, KHÔNG phải kể lại đầy đủ mọi chi tiết. Vì vậy:
- BẮT BUỘC GỘP: nếu 2, 3 hoặc nhiều diễn biến/hành động nhỏ liên tiếp cùng phục vụ MỘT mục đích/MỘT
  bước trong mạch truyện (vd: nhân vật chuẩn bị -> di chuyển -> đến nơi -> gặp người kia), hãy viết
  GỘP thành đúng 1 câu duy nhất tóm tắt cả chuỗi đó, thay vì mỗi hành động một câu riêng.
- CHỈ viết một dòng lời bình MỚI khi có một trong các mốc sau: đổi mục tiêu nhân vật, xuất hiện mâu
  thuẫn mới, có hành động/quyết định làm thay đổi cục diện, hoặc một bước ngoặt/twist.
- Bỏ hẳn (không viết dòng nào) cho: các phản ứng cảm xúc nhỏ không đổi hướng truyện, các đoạn hội
  thoại giải thích lại điều khán giả đã biết, các cảnh sinh hoạt/di chuyển không mang thông tin mới.
- Khi chấm "importance", hãy chấm NGHIÊM KHẮC hơn bình thường — chỉ chấm 4-5 cho đúng những gì thực
  sự là xương sống cốt truyện, vì kịch bản này sẽ bị nén rất mạnh ở bước biên tập cuối.
- Văn phong: câu ngắn, đi thẳng vào hành động và hệ quả, không dừng lại để mô tả không khí/cảm xúc dài
  dòng — nhưng vẫn phải là câu chuyện mạch lạc, không phải liệt kê khô khan.
"""

_DETAILED_STYLE_ADDENDUM = """
--- PHỤ LỤC CHẾ ĐỘ "RECAP CHI TIẾT" (đang bật) ---
Đây là bản recap CHI TIẾT VỪA PHẢI: giữ lại đầy đủ các nút thắt của tuyến truyện chính VÀ các tuyến
phụ quan trọng (không chỉ khung xương), kể cả những đoạn xây dựng động cơ/tâm lý nhân vật miễn là nó
thực sự phục vụ việc hiểu chuyện. Không cần gộp nhiều diễn biến vào 1 câu như chế độ nhanh — mỗi diễn
biến đáng kể nên có câu lời bình riêng, nhưng vẫn phải bỏ hẳn các đoạn thuần tuý chuyển cảnh/lấp chỗ
trống không mang thông tin gì mới.
"""

_ULTRA_STYLE_ADDENDUM = """
--- PHỤ LỤC CHẾ ĐỘ "RECAP SIÊU CHI TIẾT" (đang bật) ---
Đây là bản recap ĐẦY ĐỦ NHẤT có thể trong khi vẫn là lời bình (không phải dịch thoại nguyên văn): hãy
kể lại GẦN NHƯ MỌI diễn biến có ý nghĩa, kể cả các tuyến phụ, các đoạn xây dựng nhân vật/cảm xúc, các
chi tiết nhỏ giúp hiểu sâu hơn động cơ và mối quan hệ giữa các nhân vật — đừng tự ý lược bỏ một diễn
biến chỉ vì nó "không phải bước ngoặt lớn". CHỈ bỏ qua những gì THỰC SỰ trống rỗng về thông tin (cảnh
chuyển thuần tuý, khoảnh khắc lặp lại không thêm gì mới). Vì kể chi tiết hơn, hãy chấm "importance"
RỘNG RÃI hơn bình thường (ưu tiên 3-4 cho phần lớn diễn biến có thật) để bước biên tập cuối gần như
không cắt gì — bản recap này ưu tiên ĐỘ ĐẦY ĐỦ hơn là ĐỘ NGẮN GỌN.
"""

RECAP_MODE_PRESETS = {
    "fast": {
        "label": "NHANH",
        "style_addendum": _FAST_STYLE_ADDENDUM,
        "ratio_attr": "SCRIPT_FAST_TARGET_RATIO",
        # Block lớn hơn bình thường -> ép LLM nén nhiều nội dung/lần gọi hơn.
        "text_block_scale": 1.8,
        "vision_block_scale": 1.3,
        # Chỉ các dòng importance >= 4 mới được BẢO VỆ tuyệt đối khỏi bị cắt.
        "min_importance_protect": 4,
        # Bật bước GỘP DÒNG chuyên biệt sau khi có bản nháp (xem _merge_script_fast).
        "enable_merge_pass": True,
        "merge_group_seconds": 75.0,
    },
    "detailed": {
        "label": "CHI TIẾT",
        "style_addendum": _DETAILED_STYLE_ADDENDUM,
        "ratio_attr": "SCRIPT_DETAILED_TARGET_RATIO",
        "text_block_scale": 1.0,
        "vision_block_scale": 1.0,
        "min_importance_protect": 4,
        "enable_merge_pass": False,
        "merge_group_seconds": 0.0,
    },
    "ultra": {
        "label": "SIÊU CHI TIẾT",
        "style_addendum": _ULTRA_STYLE_ADDENDUM,
        "ratio_attr": "SCRIPT_ULTRA_TARGET_RATIO",
        # Block nhỏ hơn -> LLM xử lý từng đoạn ngắn hơn -> giữ nhiều chi tiết hơn.
        "text_block_scale": 0.55,
        "vision_block_scale": 0.7,
        # Chỉ cắt những dòng "gần như vô nghĩa" (importance == 1), gần như
        # không đụng vào phần còn lại.
        "min_importance_protect": 2,
        "enable_merge_pass": False,
        "merge_group_seconds": 0.0,
    },
}

# Preset đang active trong lần gọi generate_script() hiện tại. Pipeline sinh
# kịch bản chạy tuần tự (không đa luồng) nên dùng biến module-level đơn giản
# thay vì phải truyền preset xuyên suốt qua rất nhiều hàm nội bộ.
_active_preset = RECAP_MODE_PRESETS["fast"]


def _get_recap_preset():
    mode = str(getattr(config, "SCRIPT_RECAP_MODE", "fast") or "fast").strip().lower()
    preset = RECAP_MODE_PRESETS.get(mode)
    if preset is None:
        logutil.warn(f"⚠️ [script_gen] recap_mode '{mode}' không hợp lệ (chỉ nhận fast/detailed/ultra). "
                      f"Dùng mặc định 'fast'.")
        mode, preset = "fast", RECAP_MODE_PRESETS["fast"]
    return mode, preset


def _active_style_guide() -> str:
    return STYLE_GUIDE + "\n" + _active_preset.get("style_addendum", "")


def _selectivity_reminder() -> str:
    """Nhắc nhở NHẸ, không ép số từ/giây cụ thể (khác bản cũ dùng ngân sách cứng
    theo % thời lượng block — cách đó dễ cắt cụt những đoạn thực sự quan trọng
    chỉ vì chúng rơi vào 1 block dài). Việc "nén" video giờ được xử lý ở bước
    biên tập TOÀN CỤC sau khi có đủ ngữ cảnh cả câu chuyện, dựa trên điểm
    "importance" — xem _trim_script_to_target."""
    return ("Nhắc lại: đừng kể lể mọi chi tiết nhỏ, chỉ giữ những gì thật sự cần cho mạch truyện. "
            "Đừng quên chấm điểm \"importance\" (1-5) trung thực cho mỗi dòng.")


def _trim_script_to_target(script, target_minutes: float, tolerance: float = 1.15,
                            min_importance_protect: int = 4):
    """Bước biên tập TOÀN CỤC cuối cùng: nếu tổng thời lượng ước tính vượt quá
    (target_minutes * tolerance), cắt bớt các dòng ÍT QUAN TRỌNG NHẤT trước
    (importance thấp nhất, và trong cùng mức importance thì cắt dòng dài/tốn
    thời gian hơn trước) cho tới khi về dưới ngưỡng. KHÔNG BAO GIỜ cắt dòng có
    importance >= min_importance_protect dù có vượt target, vì thà video hơi
    dài hơn dự kiến còn hơn mất mạch truyện. Nếu target_minutes <= 0 (tắt
    tính năng) thì giữ nguyên toàn bộ.

    min_importance_protect: ngưỡng "bất khả xâm phạm" — do TỪNG CHẾ ĐỘ RECAP
    quyết định (xem RECAP_MODE_PRESETS). Chế độ "fast"/"detailed" dùng 4 (chỉ
    bảo vệ bước ngoặt/thông tin cốt lõi, sẵn sàng cắt phần còn lại để đạt thời
    lượng ngắn). Chế độ "ultra" dùng 2 (gần như chỉ cắt những dòng "gần như
    vô nghĩa" ở mức 1, vì mục tiêu của chế độ này là ĐẦY ĐỦ chứ không phải
    NGẮN GỌN).

    LƯU Ý: không còn cơ chế "bảo vệ N phút đầu" riêng — mọi dòng, kể cả ở
    đầu kịch bản, đều được xét cắt bình đẳng theo đúng điểm importance như
    mọi dòng khác trong toàn bộ kịch bản.
    """
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

    min_protect = int(min_importance_protect)

    # Sắp theo importance tăng dần, cùng importance thì ước lượng thời lượng
    # giảm dần trước (ưu tiên cắt câu vừa ít quan trọng vừa dài, hiệu quả hơn).
    removable_idx = sorted(
        (i for i, l in enumerate(script) if int(l.get("importance", 3) or 3) < min_protect),
        key=lambda i: (int(script[i].get("importance", 3) or 3), -est_duration(script[i])),
    )
    to_drop = set()
    for i in removable_idx:
        if total <= cap_sec:
            break
        total -= est_duration(script[i])
        to_drop.add(i)

    kept = [l for i, l in enumerate(script) if i not in to_drop]
    logutil.stage(f"[script_gen] Biên tập toàn cục: kịch bản ước tính ~{ (total + sum(est_duration(script[i]) for i in to_drop)) / 60:.1f} phút "
          f"> mục tiêu {target_minutes:.0f} phút -> cắt {len(to_drop)}/{len(script)} dòng ít quan trọng nhất "
          f"(giữ nguyên mọi dòng importance>={min_protect}). Còn lại ước tính ~{total / 60:.1f} phút.")
    return kept


def _probe_source_duration_seconds(video_path) -> float:
    """Đo thời lượng phim gốc (giây) qua ffprobe, dùng để TỰ ĐỘNG tính thời
    lượng đích (target_minutes) theo tỉ lệ của từng chế độ recap khi người
    dùng không ép cứng target_minutes trong config.toml. Trả về 0.0 nếu
    không đo được (sẽ có fallback khác ở nơi gọi)."""
    if not video_path:
        return 0.0
    import subprocess
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout.strip()
        return float(out) if out else 0.0
    except Exception:
        return 0.0


def _resolve_target_minutes(mode: str, preset: dict, scenes, video_path) -> float:
    """Quyết định thời lượng đích (phút) cho kịch bản cuối cùng.

    Ưu tiên: SCRIPT_TARGET_MINUTES trong config (nếu > 0) LUÔN thắng, coi như
    người dùng ép cứng số phút họ muốn, bỏ qua chế độ recap. Nếu không, tự
    tính = thời lượng phim gốc (phút) * tỉ lệ của mode đang chọn, kẹp trong
    [SCRIPT_MIN_TARGET_MINUTES, SCRIPT_MAX_TARGET_MINUTES] để tránh phim quá
    ngắn/dài cho ra kết quả phi lý (vd phim 4 phút không nên bị ép xuống dưới
    2 phút, phim 4 tiếng không nên bị kéo lên vô hạn)."""
    manual = float(getattr(config, "SCRIPT_TARGET_MINUTES", 0.0) or 0.0)
    if manual > 0:
        return manual

    ratio = float(getattr(config, preset["ratio_attr"], 0.2))
    source_sec = _probe_source_duration_seconds(video_path)
    if source_sec <= 0 and scenes:
        # Không đọc được video (vd đang chạy lại từ transcript có sẵn) -> ước
        # lượng thời lượng phim gốc từ mốc kết thúc cảnh cuối cùng.
        source_sec = scenes[-1].get("end", 0.0)
    if source_sec <= 0:
        # Không có cách nào ước lượng -> dùng số phút mặc định an toàn theo mode.
        fallback = {"fast": 15.0, "detailed": 35.0, "ultra": 65.0}
        return fallback.get(mode, 20.0)

    lo = float(getattr(config, "SCRIPT_MIN_TARGET_MINUTES", 3.0))
    hi = float(getattr(config, "SCRIPT_MAX_TARGET_MINUTES", 120.0))
    target = (source_sec / 60.0) * ratio
    return max(lo, min(hi, target))


def generate_script(transcript, scenes, out_path: Path, video_path: Path = None):
    global _active_preset
    mode, preset = _get_recap_preset()
    _active_preset = preset
    print(f"[script_gen] Đang sinh kịch bản nháp — chế độ recap: {preset['label']} ({mode})...")

    if not config.DIRECTOR_ENABLED or not scenes:
        script = _generate_script_legacy(transcript, scenes)
    else:
        script = _generate_script_directed(transcript, scenes, video_path, preset)

    script.sort(key=lambda x: x.get("ref_start", 0.0))
    script = _sanitize_script(script)

    if getattr(config, "SCRIPT_POLISH_ENABLED", True) and script:
        script = _polish_script(script)
        script = _sanitize_script(script)

    # Chế độ "fast" có thêm bước GỘP DÒNG chuyên biệt: nén nhiều dòng liền kề
    # thành 1 dòng duy nhất (khác bước polish ở trên — polish chỉ chỉnh câu
    # chữ, KHÔNG đổi số lượng dòng). Chạy SAU polish để câu chữ đầu vào đã
    # mạch lạc, giúp bước gộp cho kết quả tốt hơn.
    if preset.get("enable_merge_pass") and script:
        script = _merge_script_fast(script, preset.get("merge_group_seconds", 75.0))
        script = _sanitize_script(script)

    target_minutes = _resolve_target_minutes(mode, preset, scenes, video_path)
    if target_minutes and script:
        min_importance_protect = preset.get("min_importance_protect", 4)
        script = _trim_script_to_target(
            script, target_minutes,
            min_importance_protect=min_importance_protect,
        )

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)
    logutil.stage(f"[script_gen] Xong ({preset['label']}): {len(script)} dòng thoại, "
                  f"mục tiêu ~{target_minutes:.1f} phút -> {out_path}")
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

def _generate_script_directed(transcript, scenes, video_path: Path, preset: dict = None):
    preset = preset or _active_preset
    text_scale = float(preset.get("text_block_scale", 1.0))
    vision_scale = float(preset.get("vision_block_scale", 1.0))
    max_text_block_sec = config.DIRECTOR_MAX_TEXT_BLOCK_SEC * text_scale
    max_vision_block_sec = config.DIRECTOR_MAX_VISION_BLOCK_SEC * vision_scale
    blocks = director.plan_scenes(
        scenes, transcript,
        max_text_block_sec=max_text_block_sec,
        max_vision_block_sec=max_vision_block_sec,
    )
    if not blocks:
        return _generate_script_legacy(transcript, scenes)

    frames_dir = config.TEMP_DIR / "director_frames"
    all_lines = []
    story_so_far = ""
    n_blocks = len(blocks)
    for i, block in enumerate(blocks, 1):
        tag = f"{block['start']:.1f}"
        logutil.stage(f"[script_gen] Block {i}/{n_blocks}: {block['start']:.1f}s-{block['end']:.1f}s ({block['mode']})")
        try:
            if block["mode"] == "vision" and video_path is not None:
                lines = _generate_vision_block(block, transcript, video_path, frames_dir, tag, story_so_far)
            else:
                lines = _generate_text_block(block, transcript, story_so_far)
        except Exception as e:
            logutil.warn(f"⚠️ [script_gen] Lỗi ở block {block['start']:.1f}-{block['end']:.1f}s ({e}). "
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
        logutil.warn("⚠️ [script_gen] Không sinh được dòng thoại nào theo director. Dùng lại cách cũ (1 lần gọi toàn bộ transcript).")
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
    prompt = f"""{_active_style_guide()}

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
        logutil.warn(f"⚠️ [script_gen] Không trích được khung hình nào cho block {tag}s -> lùi về text-only.")
        return _generate_text_block(block, transcript, story_so_far)

    t_block = _format_transcript_range(transcript, block["start"], block["end"])
    prompt = f"""{_active_style_guide()}

{_story_context_block(story_so_far)}

Bạn được xem {len(frames)} khung hình đại diện, lấy CÀNG XA NHAU CÀNG TỐT về thời điểm trong đoạn phim
ÍT/KHÔNG CÓ THOẠI này (khung đầu gần lúc {block['start']:.1f}s, khung cuối gần lúc {block['end']:.1f}s
— so với video gốc), theo ĐÚNG THỨ TỰ THỜI GIAN. Đây KHÔNG phải 1 tấm ảnh tĩnh — hãy SO SÁNH khung đầu
với khung cuối để suy ra ĐÃ CÓ CHUYỆN GÌ XẢY RA GIỮA 2 THỜI ĐIỂM ĐÓ (ai vừa xuất hiện/biến mất, tư thế/
vị trí/biểu cảm/bối cảnh thay đổi ra sao, có hành động/di chuyển gì không) — đó chính là diễn biến cần
kể, không phải mô tả từng khung riêng lẻ. Hãy nhìn để HIỂU chuyện gì đang xảy ra — nhân vật nào, đang
làm gì, cảm xúc/mục đích là gì — rồi kể lại đúng tinh thần của STYLE GUIDE ở trên. TUYỆT ĐỐI không liệt
kê những gì nhìn thấy trong ảnh (không mô tả bối cảnh, ánh sáng, bố cục, màu sắc, góc máy) — chỉ dùng
hình ảnh để suy ra diễn biến rồi kể lại bằng lời văn tự nhiên.

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
    logutil.stage(f"[script_gen] Biên tập lại kịch bản cho mạch lạc hơn ({len(script)} dòng)...")
    polished = []
    story_so_far = ""
    for start in range(0, len(script), POLISH_CHUNK_SIZE):
        chunk = script[start:start + POLISH_CHUNK_SIZE]
        try:
            new_texts = _polish_chunk(chunk, story_so_far)
        except Exception as e:
            logutil.warn(f"⚠️ [script_gen] Bước biên tập lỗi ở cụm dòng {start}-{start + len(chunk)} ({e}). "
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
                logutil.warn(f"⚠️ [script_gen] Bước biên tập trả sai số dòng ({len(new_texts)} thay vì {len(chunk)}) "
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
    prompt = f"""{_active_style_guide()}

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
#  BƯỚC GỘP DÒNG (merge pass) — CHỈ chạy ở chế độ recap "fast".
#
#  Khác bước polish ở trên (chỉnh câu chữ nhưng GIỮ NGUYÊN số dòng), bước
#  này chủ động GIẢM số dòng: gom các dòng nháp liền kề trong cùng 1 "cụm
#  thời gian" (mặc định ~75 giây liên tục trên timeline gốc — xem
#  merge_group_seconds trong RECAP_MODE_PRESETS) rồi nhờ LLM viết lại thành
#  ĐÚNG 1 câu duy nhất tóm tắt cả cụm, thay vì mỗi diễn biến nhỏ một câu.
#  Đây chính là thuật toán "hiểu kịch bản gốc rồi gộp nhiều dòng thành một"
#  mà chế độ recap nhanh cần, để một phim 2 tiếng còn lại khoảng 15 phút mà
#  vẫn mạch lạc thay vì chỉ cắt trụi các câu importance thấp.
#
#  Mốc thời gian (ref_start/ref_end) của dòng gộp = [start cụm, end cụm] —
#  KHÔNG bịa mốc mới, để bước render sau vẫn chọn đúng đoạn hình gốc tương
#  ứng cho TTS đọc lên (không phá đồng bộ audio/hình).
#
#  An toàn: cụm nào LLM gộp lỗi/parse hỏng thì GIỮ NGUYÊN các dòng gốc của
#  cụm đó (không gộp), thà kịch bản hơi dài hơn còn hơn mất nội dung.
# ============================================================

def _cluster_script_by_time(script, group_seconds: float):
    """Chia script (đã sort theo ref_start) thành các cụm liên tiếp, mỗi cụm
    trải dài tối đa `group_seconds` giây trên timeline gốc. Một cụm luôn có
    ÍT NHẤT 1 dòng; cụm chỉ có 1 dòng thì merge pass sẽ tự bỏ qua (không có
    gì để gộp)."""
    if group_seconds <= 0:
        return [script]
    clusters = []
    cur = []
    cur_start = None
    for line in script:
        start = float(line.get("ref_start", 0.0))
        if cur and (start - cur_start) > group_seconds:
            clusters.append(cur)
            cur = []
        if not cur:
            cur_start = start
        cur.append(line)
    if cur:
        clusters.append(cur)
    return clusters


def _merge_cluster(cluster, story_so_far: str):
    """Gọi LLM 1 lần để nén N dòng của 1 cụm thành ĐÚNG 1 câu lời bình duy
    nhất. Trả về (text, importance) hoặc None nếu lỗi/parse hỏng."""
    numbered = "\n".join(f"{idx}: {l.get('text', '')}" for idx, l in enumerate(cluster))
    prompt = f"""{_active_style_guide()}

{_story_context_block(story_so_far)}

Dưới đây là {len(cluster)} câu lời bình NHÁP liên tiếp (đánh số 0..{len(cluster) - 1}, đúng thứ tự kể),
tất cả đều nằm trong cùng một khoảng thời gian ngắn của phim và cùng phục vụ một chuỗi diễn biến:
{numbered}

Nhiệm vụ: viết lại thành ĐÚNG 1 CÂU (hoặc 1 đoạn ngắn 2-3 câu nếu thực sự cần) tóm tắt LẠI TOÀN BỘ
{len(cluster)} câu trên theo đúng tinh thần "RECAP NHANH" ở phụ lục STYLE GUIDE — giữ đúng trình tự
nhân quả, bỏ hết chi tiết phụ, chỉ giữ điều gì thực sự thay đổi mạch truyện.

Trả về CHÍNH XÁC 1 JSON object dạng:
{{"text": "câu đã gộp", "importance": <int 1-5, lấy mức quan trọng cao nhất phù hợp với nội dung đã gộp>}}
Không giải thích gì thêm, chỉ trả JSON thuần, không kèm markdown/code fence.
"""
    raw = llm_client.call_text(
        prompt, config.LLM_PROVIDER, config.LLM_MODEL, config.LLM_API_KEY, config.LLM_BASE_URL,
        temperature=0.4, label="script-merge",
    )
    data = llm_client.extract_json_object(raw)
    text = str(data.get("text", "")).strip()
    if not text:
        return None
    try:
        importance = int(data.get("importance", 3) or 3)
    except (TypeError, ValueError):
        importance = 3
    importance = max(1, min(5, importance))
    return text, importance


def _merge_script_fast(script, group_seconds: float):
    clusters = _cluster_script_by_time(script, group_seconds)
    logutil.stage(f"[script_gen] Gộp dòng (chế độ NHANH): {len(script)} dòng nháp -> {len(clusters)} cụm "
                  f"(~{group_seconds:.0f}s/cụm)...")
    merged = []
    story_so_far = ""
    n_clusters = len(clusters)
    for i, cluster in enumerate(clusters, 1):
        if len(cluster) <= 1:
            # Không có gì để gộp -> giữ nguyên dòng đơn lẻ.
            merged.extend(cluster)
            story_so_far = _update_story_context(story_so_far, cluster)
            continue
        try:
            result = _merge_cluster(cluster, story_so_far)
        except Exception as e:
            logutil.warn(f"⚠️ [script_gen] Gộp cụm {i}/{n_clusters} lỗi ({e}). Giữ nguyên {len(cluster)} dòng gốc.")
            result = None

        if result is None:
            merged.extend(cluster)
            story_so_far = _update_story_context(story_so_far, cluster)
        else:
            text, importance = result
            merged_line = {
                "ref_start": cluster[0].get("ref_start", 0.0),
                "ref_end": cluster[-1].get("ref_end", cluster[0].get("ref_start", 0.0)),
                "text": text,
                "importance": importance,
            }
            merged.append(merged_line)
            story_so_far = _update_story_context(story_so_far, [merged_line])

        if i < n_clusters:
            time.sleep(API_THROTTLE_SEC)

    logutil.stage(f"[script_gen] Gộp dòng xong: {len(script)} -> {len(merged)} dòng.")
    return merged


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
        logutil.warn(f"⚠️ Transcript quá dài ({len(text_block)} ký tự). Rút gọn thông minh...")
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
    prompt = f"""{_active_style_guide()}

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
