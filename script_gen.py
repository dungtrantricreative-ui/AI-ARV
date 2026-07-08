import json
import shutil
from pathlib import Path

import config
import director
import frame_extract
import llm_client


# ============================================================
#  ĐƯỜNG CHÍNH (director bật): sinh kịch bản theo từng block,
#  block ít thoại -> gửi kèm khung hình cho model vision.
# ============================================================

def generate_script(transcript, scenes, out_path: Path, video_path: Path = None):
    print("[script_gen] Đang sinh kịch bản nháp...")

    if not config.DIRECTOR_ENABLED or not scenes:
        script = _generate_script_legacy(transcript, scenes)
    else:
        script = _generate_script_directed(transcript, scenes, video_path)

    script.sort(key=lambda x: x.get("ref_start", 0.0))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)
    print(f"[script_gen] Xong: {len(script)} dòng thoại -> {out_path}")
    return script


def _generate_script_directed(transcript, scenes, video_path: Path):
    blocks = director.plan_scenes(scenes, transcript)
    if not blocks:
        return _generate_script_legacy(transcript, scenes)

    frames_dir = config.TEMP_DIR / "director_frames"
    all_lines = []
    n_blocks = len(blocks)
    for i, block in enumerate(blocks, 1):
        tag = f"{block['start']:.1f}"
        print(f"[script_gen] Block {i}/{n_blocks}: {block['start']:.1f}s-{block['end']:.1f}s ({block['mode']})")
        try:
            if block["mode"] == "vision" and video_path is not None:
                lines = _generate_vision_block(block, transcript, video_path, frames_dir, tag)
            else:
                lines = _generate_text_block(block, transcript)
        except Exception as e:
            print(f"⚠️ [script_gen] Lỗi ở block {block['start']:.1f}-{block['end']:.1f}s ({e}). "
                  f"Bỏ qua block này (thoại/hình các block khác không bị ảnh hưởng).")
            lines = []
        all_lines.extend(lines)

    if frames_dir.exists():
        shutil.rmtree(frames_dir, ignore_errors=True)

    if not all_lines:
        print("⚠️ [script_gen] Không sinh được dòng thoại nào theo director. Dùng lại cách cũ (1 lần gọi toàn bộ transcript).")
        return _generate_script_legacy(transcript, scenes)

    return all_lines


def _generate_text_block(block, transcript):
    t_block = _format_transcript_range(transcript, block["start"], block["end"])
    prompt = f"""Bạn là biên kịch tóm tắt phim. Dưới đây là một đoạn trong phim, từ giây
{block['start']:.1f} đến {block['end']:.1f} (so với video gốc).

Transcript đoạn này:
{t_block if t_block.strip() else "(không có thoại đáng kể trong đoạn này)"}

Hãy viết lại thành kịch bản recap ngắn gọn, hấp dẫn, bằng tiếng Việt cho ĐÚNG đoạn này.

Yêu cầu:
- Trả về JSON array, mỗi phần tử có: ref_start (float), ref_end (float), text (string).
- ref_start >= {block['start']:.1f} và ref_end <= {block['end']:.1f} (phải nằm trong đoạn này).
- Không giải thích gì thêm, chỉ trả về JSON thuần.

Ví dụ:
[{{"ref_start": {block['start']:.1f}, "ref_end": {min(block['start'] + 4, block['end']):.1f}, "text": "..."}}]
"""
    raw = llm_client.call_text(
        prompt, config.LLM_PROVIDER, config.LLM_MODEL, config.LLM_API_KEY, config.LLM_BASE_URL,
        label="script-text",
    )
    return llm_client.extract_json(raw)


def _generate_vision_block(block, transcript, video_path, frames_dir, tag):
    frames = frame_extract.extract_frames(
        video_path, block["start"], block["end"], config.DIRECTOR_FRAMES_PER_BLOCK, frames_dir, tag,
    )
    if not frames:
        print(f"⚠️ [script_gen] Không trích được khung hình nào cho block {tag}s -> lùi về text-only.")
        return _generate_text_block(block, transcript)

    t_block = _format_transcript_range(transcript, block["start"], block["end"])
    prompt = f"""Bạn là biên kịch tóm tắt phim. Đây là {len(frames)} khung hình đại diện, trích đều nhau
từ một đoạn phim ÍT/KHÔNG CÓ THOẠI, từ giây {block['start']:.1f} đến {block['end']:.1f} (so với video gốc).
Hãy NHÌN KỸ các khung hình để hiểu chuyện gì đang xảy ra (hành động, bối cảnh, cảm xúc nhân vật...).

Thoại nghe được trong đoạn này (nếu có, có thể rất ít hoặc không có):
{t_block if t_block.strip() else "(không có thoại)"}

Hãy viết lại thành kịch bản recap ngắn gọn, hấp dẫn, bằng tiếng Việt, MÔ TẢ đúng những gì đang diễn ra
trong hình chứ không chỉ dựa vào thoại.

Yêu cầu:
- Trả về JSON array, mỗi phần tử có: ref_start (float), ref_end (float), text (string).
- ref_start >= {block['start']:.1f} và ref_end <= {block['end']:.1f} (phải nằm trong đoạn này).
- Không giải thích gì thêm, chỉ trả về JSON thuần.
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
#  ĐƯỜNG LÙI (legacy, director tắt hoặc thất bại hoàn toàn):
#  y hệt hành vi cũ — 1 lần gọi LLM cho toàn bộ transcript.
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
    prompt = f"""Bạn là biên kịch tóm tắt phim. Dựa vào transcript và danh sách cảnh dưới đây, hãy viết lại thành kịch bản recap ngắn gọn, hấp dẫn, bằng tiếng Việt.

Transcript:
{t_block}

Danh sách cảnh:
{s_block}

Yêu cầu:
- Trả về JSON array, mỗi phần tử có: ref_start (float), ref_end (float), text (string).
- ref_start/ref_end phải nằm trong khoảng thời gian của một cảnh cụ thể.
- text là lời thoại recap cho cảnh đó, ngắn gọn, có cảm xúc.
- Không giải thích gì thêm, chỉ trả về JSON thuần.

Ví dụ:
[
  {{"ref_start": 0.0, "ref_end": 4.2, "text": "Mở đầu phim, chúng ta thấy một thành phố chìm trong bóng tối..."}}
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
