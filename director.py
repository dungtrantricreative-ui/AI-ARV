"""
director.py — "AI trưởng nhóm" điều phối pipeline sinh kịch bản recap.

VẤN ĐỀ CẦN GIẢI QUYẾT
----------------------
- Model text (LLM đọc transcript) không "xem" phim -> bỏ lỡ hành động không
  lời thoại (rượt đuổi, đánh nhau, cảnh thiên nhiên, twist im lặng...).
- Model vision (Gemma 4 31B qua Cerebras) xem được ẢNH (không phải video —
  hiện là image input, private preview, tối đa ~280-1120 token/ảnh), và chi
  phí/độ trễ cao hơn nhiều so với model text. Xem hết 1 phim 2 tiếng bằng
  ảnh là bất khả thi về chi phí lẫn cửa sổ ngữ cảnh.
- Giải pháp: chỉ dùng vision cho ĐÚNG những đoạn transcript không đủ để hiểu
  chuyện gì đang xảy ra, còn lại dùng text-only như cũ.

CÔNG THỨC ĐIỀU PHỐI (routing formula)
--------------------------------------
Với mỗi cảnh (scene) đã có transcript chồng lên nó, tính:

    speech_chars   = tổng số ký tự thoại nằm trong [scene.start, scene.end]
                      (phân bổ theo tỉ lệ overlap nếu 1 đoạn transcript chỉ
                      chồng lấn một phần lên cảnh)
    density        = speech_chars / duration            (ký tự thoại / giây)
    covered        = tổng thời lượng transcript chồng lên cảnh
    silence_ratio  = 1 - covered / duration              (0 = nói liên tục,
                      1 = im lặng hoàn toàn)

Một cảnh được đánh dấu CẦN VISION nếu:
    density < DIRECTOR_DENSITY_THRESHOLD          (thoại quá thưa)
    HOẶC silence_ratio > DIRECTOR_SILENCE_RATIO_THRESHOLD  (phần lớn im lặng)
    HOẶC là cảnh đầu tiên của phim (thiết lập bối cảnh, nếu bật
         DIRECTOR_FORCE_VISION_FIRST_SCENE)

Ngược lại -> TEXT_ONLY.

GỘP BLOCK (giảm số lần gọi API)
---------------------------------
Các cảnh liền kề cùng nhãn được gộp thành 1 "block":
    - Block vision: tối đa DIRECTOR_MAX_VISION_BLOCK_SEC giây (mặc định 40s)
      — đủ ngắn để vài khung hình đại diện là đủ mô tả, đủ để không tốn quá
      nhiều ảnh/tiền cho 1 lần gọi.
    - Block text: tối đa DIRECTOR_MAX_TEXT_BLOCK_SEC giây (mặc định 300s)
      — gộp nhiều cảnh lại để giảm số lần gọi LLM, prompt vẫn đủ ngắn.

VAN AN TOÀN CHI PHÍ (cost safety valve)
------------------------------------------
Nếu tổng-thời-lượng-vision / tổng-thời-lượng-phim > DIRECTOR_MAX_VISION_RATIO
(mặc định 35%), hệ thống tự nới lỏng ngưỡng (giảm density_threshold,
tăng silence_threshold) và phân loại lại — tối đa 3 lần — để một bộ phim
hành động ít thoại không đẩy chi phí vision vượt tầm kiểm soát.

BƯỚC XÁC NHẬN PHỤ (tuỳ chọn — DIRECTOR_CONFIRM_WITH_LLM)
------------------------------------------------------------
Rule-based có thể false-positive (vd nhạc nền dài nhưng thực ra chỉ là 2
người ngồi nói chuyện chậm, không cần xem hình). Trước khi tốn tiền gọi
vision, hệ thống gộp toàn bộ danh sách block "candidate vision" thành ĐÚNG
1 lần gọi LLM text-only (rẻ, không có ảnh) để hỏi lại xem có thực sự cần
xem hình không. Bước này giảm số lần gọi vision không cần thiết mà chỉ tốn
thêm 1 lời gọi text rẻ cho cả phim.

FALLBACK AN TOÀN (ưu tiên "ít lỗi lầm nhất")
-----------------------------------------------
- Vision API lỗi (mạng, quá tải, model từ chối ảnh...) -> tự động lùi về
  text-only cho đúng block đó, chỉ log cảnh báo, KHÔNG làm chết pipeline.
- Bước xác nhận LLM lỗi/parse JSON lỗi -> giữ nguyên kết quả rule-based
  (an toàn hơn là crash).
- ffmpeg trích khung hình lỗi -> nếu trích được ít nhất 1 khung thì vẫn
  chạy tiếp; nếu trích được 0 khung thì tự lùi block đó về text-only.
"""
import json
import re

import config
import llm_client


def _overlap(a_start, a_end, b_start, b_end) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _scene_stats(scene, transcript):
    start, end = scene["start"], scene["end"]
    duration = max(end - start, 0.001)
    speech_chars = 0.0
    covered = 0.0
    for seg in transcript:
        seg_start, seg_end = seg.get("start", 0.0), seg.get("end", 0.0)
        ov = _overlap(start, end, seg_start, seg_end)
        if ov <= 0:
            continue
        covered += ov
        seg_dur = max(seg_end - seg_start, 0.001)
        speech_chars += len(seg.get("text", "")) * (ov / seg_dur)
    density = speech_chars / duration
    silence_ratio = 1.0 - min(covered / duration, 1.0)
    return density, silence_ratio


def _classify_scenes(scenes, transcript, density_threshold, silence_threshold):
    labeled = []
    for i, sc in enumerate(scenes):
        density, silence_ratio = _scene_stats(sc, transcript)
        needs_vision = density < density_threshold or silence_ratio > silence_threshold
        if i == 0 and config.DIRECTOR_FORCE_VISION_FIRST_SCENE:
            needs_vision = True
        labeled.append({
            "start": sc["start"], "end": sc["end"],
            "scene_id": sc.get("scene_id", i),
            "density": round(density, 2), "silence_ratio": round(silence_ratio, 2),
            "mode": "vision" if needs_vision else "text",
        })
    return labeled


def _merge_adjacent(labeled, max_dur_for_mode):
    blocks = []
    cur = None
    for sc in labeled:
        max_dur = max_dur_for_mode(sc["mode"])
        if cur and cur["mode"] == sc["mode"] and (sc["end"] - cur["start"]) <= max_dur:
            cur["end"] = sc["end"]
            cur["scene_ids"].append(sc["scene_id"])
        else:
            if cur:
                blocks.append(cur)
            cur = {"start": sc["start"], "end": sc["end"], "mode": sc["mode"], "scene_ids": [sc["scene_id"]]}
    if cur:
        blocks.append(cur)
    return blocks


def _remerge_blocks(blocks):
    """Gộp lại các block liền kề cùng mode sau khi bước xác nhận đổi mode
    của một vài block (vd vision -> text), không giới hạn thời lượng nữa
    vì đây chỉ là dọn dẹp, không phải phân loại lần đầu."""
    merged = []
    for b in blocks:
        if merged and merged[-1]["mode"] == b["mode"] and abs(merged[-1]["end"] - b["start"]) < 1e-6:
            merged[-1]["end"] = b["end"]
            merged[-1]["scene_ids"].extend(b["scene_ids"])
        else:
            merged.append(dict(b))
    return merged


def _max_dur_for_mode(mode):
    return config.DIRECTOR_MAX_VISION_BLOCK_SEC if mode == "vision" else config.DIRECTOR_MAX_TEXT_BLOCK_SEC


def plan_scenes(scenes, transcript):
    """Trả về danh sách block đã gộp: [{start, end, mode, scene_ids}]"""
    if not scenes:
        return []
    total_duration = scenes[-1]["end"]
    density_threshold = config.DIRECTOR_DENSITY_THRESHOLD
    silence_threshold = config.DIRECTOR_SILENCE_RATIO_THRESHOLD

    labeled, ratio = None, 0.0
    for attempt in range(3):
        labeled = _classify_scenes(scenes, transcript, density_threshold, silence_threshold)
        vision_total = sum(s["end"] - s["start"] for s in labeled if s["mode"] == "vision")
        ratio = vision_total / total_duration if total_duration > 0 else 0.0
        if ratio <= config.DIRECTOR_MAX_VISION_RATIO or attempt == 2:
            if ratio > config.DIRECTOR_MAX_VISION_RATIO:
                print(f"⚠️ [director] Vẫn còn {ratio:.0%} thời lượng đề xuất vision sau khi nới ngưỡng "
                      f"— chấp nhận (đã thử tối đa 3 lần).")
            break
        print(f"⚠️ [director] Tỉ lệ vision {ratio:.0%} > giới hạn {config.DIRECTOR_MAX_VISION_RATIO:.0%}. "
              f"Nới lỏng ngưỡng (lần {attempt + 1}) và phân loại lại...")
        density_threshold *= 0.5
        silence_threshold = min(silence_threshold + 0.15, 0.95)

    blocks = _merge_adjacent(labeled, _max_dur_for_mode)

    if config.DIRECTOR_CONFIRM_WITH_LLM:
        blocks = _confirm_vision_blocks(blocks, transcript)

    n_vision = sum(1 for b in blocks if b["mode"] == "vision")
    n_text = sum(1 for b in blocks if b["mode"] == "text")
    vision_total = sum(b["end"] - b["start"] for b in blocks if b["mode"] == "vision")
    print(f"[director] Kế hoạch cuối: {len(blocks)} block ({n_text} text-only, {n_vision} vision) "
          f"— {vision_total:.0f}s/{total_duration:.0f}s (~{vision_total / total_duration:.0%}) cần xem hình.")
    return blocks


def _transcript_text_in_range(transcript, start, end):
    parts = []
    for seg in transcript:
        if _overlap(start, end, seg.get("start", 0.0), seg.get("end", 0.0)) > 0:
            parts.append(seg.get("text", "").strip())
    return " ".join(p for p in parts if p)


def _confirm_vision_blocks(blocks, transcript):
    """1 lời gọi LLM text-only duy nhất để rà lại toàn bộ danh sách block
    'candidate vision', tránh tốn tiền gọi vision cho những đoạn thực ra
    không quan trọng (nhạc nền, khoảng lặng cảm xúc không ảnh hưởng cốt
    truyện...). An toàn: lỗi gì cũng giữ nguyên phân loại rule-based."""
    candidates = [b for b in blocks if b["mode"] == "vision"]
    if not candidates:
        return blocks

    lines = []
    for idx, b in enumerate(candidates):
        snippet = _transcript_text_in_range(transcript, b["start"], b["end"])[:200] or "(không có thoại)"
        lines.append(f'{idx}: [{b["start"]:.0f}s-{b["end"]:.0f}s] thoại nghe được: "{snippet}"')

    prompt = f"""Bạn là trợ lý điều phối sản xuất video recap phim. Dưới đây là các đoạn phim được
sơ bộ đánh dấu "ít/không có thoại, có thể cần xem thêm hình ảnh mới hiểu được nội dung":

{chr(10).join(lines)}

Với mỗi đoạn, hãy đánh giá: việc ít thoại có THỰC SỰ đồng nghĩa với việc bắt buộc phải xem hình để
tóm tắt đúng cốt truyện không? Nếu đoạn chỉ là nhạc nền, khoảng lặng cảm xúc, hoặc không quan trọng
với mạch phim, KHÔNG cần xem hình (có thể tóm tắt cực ngắn hoặc bỏ qua).

Trả về CHÍNH XÁC 1 JSON object dạng: {{"needs_vision": [danh sách số thứ tự (index) THỰC SỰ cần xem hình]}}
Không giải thích gì thêm, chỉ trả JSON thuần."""

    try:
        raw = llm_client.call_text(
            prompt, config.LLM_PROVIDER, config.LLM_MODEL, config.LLM_API_KEY, config.LLM_BASE_URL,
            temperature=0.2, label="director-confirm",
        )
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        data = json.loads(match.group(0)) if match else {}
        keep = set(int(i) for i in data.get("needs_vision", []))
    except Exception as e:
        print(f"⚠️ [director] Bước xác nhận thất bại ({e}) — giữ nguyên phân loại rule-based.")
        return blocks

    dropped = 0
    for idx, b in enumerate(candidates):
        if idx not in keep:
            b["mode"] = "text"
            dropped += 1
    if dropped:
        print(f"[director] Bước xác nhận: bỏ {dropped}/{len(candidates)} block khỏi diện cần xem hình "
              f"(thoại ít nhưng không quan trọng với cốt truyện).")
    return _remerge_blocks(blocks)
