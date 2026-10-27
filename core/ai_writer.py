"""AI Content & Script Writer for video dubbing.

Supports:
1) Gemini Free API (via direct HTTP, no heavy SDK required)
2) Local Ollama (http://127.0.0.1:11434) for 100% offline LLM
3) Built-in Smart Script Engine (works offline with zero keys based on video duration & transcript)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
import aiohttp

from .ffmpeg_utils import get_duration, has_audio
from .subtitles import transcribe_words


STYLES = {
    "tiktok_viral": "Hài hước, bắt trend, giật gân, câu hook mở đầu cực cuốn hút kiểu TikTok/Reels",
    "review": "Đánh giá, review trải nghiệm chân thực, nêu điểm nổi bật và lợi ích",
    "storytelling": "Kể chuyện cảm xúc, truyền cảm hứng, sâu lắng, lôi cuốn người xem",
    "news": "Tóm tắt ngắn gọn, trực diện, chuyên nghiệp, thông tin nhanh",
    "sales": "Kịch bản bán hàng kích thích hành động, giới thiệu sản phẩm và kêu gọi mua ngay",
}


def _estimate_target_words(duration_sec: float) -> int:
    """Vietnamese speaking rate is roughly 2.5 to 3 words per second (150-180 wpm)."""
    dur = max(duration_sec, 6.0)
    # Target ~2.5 words per sec so it sounds natural with small pauses
    return max(int(dur * 2.5), 18)


async def extract_transcript_from_video(video_path: str | Path) -> str:
    """Extract spoken text from the video using local Faster-Whisper if video has audio."""
    path = Path(video_path)
    if not has_audio(path):
        return ""
    try:
        from tempfile import NamedTemporaryFile
        from .subtitles import extract_audio
        with NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name
        extract_audio(path, wav_path)
        words = transcribe_words(wav_path, model_size="base", language="vi")
        Path(wav_path).unlink(missing_ok=True)
        return " ".join(w.text for w in words).strip()
    except Exception:
        return ""


async def generate_with_gemini(prompt: str, api_key: str, model: str = "gemini-1.5-flash") -> str:
    """Call Google Gemini Free API."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 600}
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=25)) as resp:
            if resp.status != 200:
                err_text = await resp.text()
                raise RuntimeError(f"Gemini API lỗi ({resp.status}): {err_text}")
            data = await resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()


async def generate_with_ollama(prompt: str, model: str = "qwen2.5:latest",
                               host: str = "http://127.0.0.1:11434") -> str:
    """Call Local Ollama API (100% offline)."""
    url = f"{host.rstrip('/')}/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": False}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=45)) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Không thể kết nối Ollama tại {host} (status {resp.status})")
            data = await resp.json()
            return data.get("response", "").strip()


def generate_smart_offline_template(style: str, duration_sec: float, transcript: str = "",
                                    topic: str = "") -> str:
    """Smart offline script generator when no API key or Ollama is available."""
    words_target = _estimate_target_words(duration_sec)
    subject = topic.strip() or ("nội dung này" if not transcript else transcript[:60])

    if style == "tiktok_viral":
        lines = [
            f"Bạn có tin được không? Đây chính là điều bất ngờ nhất về {subject} mà chưa ai nói cho bạn biết!",
            f"Hãy nhìn kỹ từng chi tiết này nhé, nó thực sự thú vị và đỉnh hơn bạn nghĩ rất nhiều.",
            "Xem đến đây rồi thì đừng quên thả tim và bấm follow để không bỏ lỡ những điều hay ho tiếp theo nha!"
        ]
    elif style == "review":
        lines = [
            f"Hôm nay mình sẽ review nhanh cho các bạn về {subject}.",
            "Cảm nhận đầu tiên là mọi thứ được làm rất chỉn chu, trải nghiệm thực tế mượt mà và vượt ngoài mong đợi.",
            "Cá nhân mình chấm 9 trên 10 điểm. Các bạn thấy thế nào, hãy để lại bình luận phía dưới nhé!"
        ]
    elif style == "storytelling":
        lines = [
            f"Có những khoảnh khắc về {subject} khiến chúng ta phải dừng lại và suy ngẫm.",
            "Mỗi chi tiết trôi qua đều mang theo một câu chuyện đặc biệt và nhiều cảm xúc.",
            "Hy vọng video này sẽ mang đến cho bạn một chút bình yên và nguồn năng lượng tích cực cho ngày hôm nay."
        ]
    elif style == "sales":
        lines = [
            f"Nếu bạn đang tìm kiếm giải pháp hoàn hảo cho {subject}, thì đây chính là thứ bạn cần!",
            "Thiết kế tối ưu, tính năng vượt trội giúp bạn tiết kiệm tối đa thời gian và công sức.",
            "Số lượng ưu đãi có hạn, bấm ngay vào link bên dưới để sở hữu ngay hôm nay nhé!"
        ]
    else:  # news / default
        lines = [
            f"Chào các bạn, hôm nay chúng ta cùng cập nhật nhanh những thông tin nổi bật về {subject}.",
            "Qua video này, bạn có thể thấy rõ các điểm mấu chốt quan trọng nhất đã được diễn ra.",
            "Cảm ơn các bạn đã theo dõi, hẹn gặp lại trong những video tiếp theo!"
        ]

    script = " ".join(lines)
    # If transcript exists and style is news/review, prepend context
    if transcript and len(transcript) > 20:
        script = f"Dựa vào nội dung gốc: {transcript[:100]}... {script}"
    return script


async def write_video_script(
    video_path: str | Path,
    style: str = "tiktok_viral",
    topic: str = "",
    provider: str = "auto",  # 'gemini' | 'ollama' | 'offline' | 'auto'
    api_key: Optional[str] = None,
    ollama_model: str = "qwen2.5:latest",
) -> dict:
    """Main function to generate video voiceover script."""
    path = Path(video_path)
    duration = get_duration(path)
    target_words = _estimate_target_words(duration)
    transcript = await extract_transcript_from_video(path)

    style_desc = STYLES.get(style, STYLES["tiktok_viral"])
    prompt = f"""Bạn là một chuyên gia sáng tạo nội dung video ngắn chuyên nghiệp (TikTok, Facebook Reels, YouTube Shorts).
Hãy viết một kịch bản giọng đọc lồng tiếng (Voiceover) tiếng Việt cho video sau:
- Thời lượng video: {duration:.1f} giây.
- Độ dài kịch bản mong muốn: Khoảng {target_words} từ (để đọc vừa khít thời lượng video, không quá dài, không quá ngắn).
- Phong cách: {style_desc}.
- Chủ đề/Gợi ý của tác giả: {topic or 'Phù hợp với nội dung video'}.
- Nội dung/Lời thoại gốc nghe được trong video (nếu có): "{transcript or 'Video không có lời thoại sẵn, hãy sáng tạo kịch bản hấp dẫn'}".

Yêu cầu định dạng:
- CHỈ trả về đoạn văn bản kịch bản tiếng Việt liền mạch để đưa thẳng vào máy đọc Text-to-Speech.
- KHÔNG thêm tiêu đề, KHÔNG thêm lời giải thích, KHÔNG thêm ghi chú như [Nhạc nền], (Cười), v.v.
- Câu từ tự nhiên, mạch lạc, hấp dẫn người nghe.
"""

    used_provider = "offline"
    generated_text = ""

    # 1. Try Gemini if key is provided or provider is gemini
    if (provider in ("gemini", "auto")) and api_key and api_key.strip():
        try:
            generated_text = await generate_with_gemini(prompt, api_key.strip())
            used_provider = "gemini"
        except Exception as e:
            if provider == "gemini":
                raise e

    # 2. Try Ollama if requested or in auto mode
    if not generated_text and (provider in ("ollama", "auto")):
        try:
            generated_text = await generate_with_ollama(prompt, model=ollama_model)
            used_provider = "ollama"
        except Exception as e:
            if provider == "ollama":
                raise e

    # 3. Fallback to smart offline template
    if not generated_text:
        generated_text = generate_smart_offline_template(style, duration, transcript, topic)
        used_provider = "offline_smart"

    return {
        "script": generated_text.strip(),
        "provider": used_provider,
        "duration": duration,
        "target_words": target_words,
        "transcript_extracted": bool(transcript),
    }
