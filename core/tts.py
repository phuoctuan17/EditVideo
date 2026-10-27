"""Free Vietnamese TTS via edge-tts (no API key)."""
from __future__ import annotations

import asyncio
from pathlib import Path

VOICES = {
    "hoaimy": "vi-VN-HoaiMyNeural",   # nữ
    "namminh": "vi-VN-NamMinhNeural",  # nam
}


def _resolve_voice(voice: str) -> str:
    return VOICES.get(voice.lower(), voice)


def _split_text(text: str, max_len: int = 80) -> list[str]:
    """Split on sentence/clause punctuation into short chunks (more reliable for edge-tts)."""
    import re
    pieces = [p.strip() for p in re.split(r"(?<=[.!?;:,\n])\s+", text) if p.strip()]
    chunks: list[str] = []
    for p in pieces:
        if chunks and len(chunks[-1]) + len(p) + 1 <= max_len:
            chunks[-1] += " " + p
        else:
            chunks.append(p)
    return chunks


async def _synthesize_chunk(text: str, voice: str, rate: str, pitch: str, volume: str,
                            retries: int = 4) -> bytes:
    import edge_tts
    last: Exception | None = None
    for attempt in range(retries):
        try:
            audio = b""
            comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume)
            async for msg in comm.stream():
                if msg["type"] == "audio":
                    audio += msg["data"]
            if audio:
                return audio
        except Exception as e:
            last = e
        await asyncio.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"edge-tts thất bại với đoạn '{text[:40]}...': {last}")


async def _synthesize(text: str, out: Path, voice: str, rate: str, pitch: str, volume: str) -> None:
    data = b""
    for chunk in _split_text(text):
        data += await _synthesize_chunk(chunk, voice, rate, pitch, volume)
    out.write_bytes(data)  # MP3 frames can be concatenated directly


def text_to_speech(text: str, out_path: str | Path, voice: str = "hoaimy", rate: str = "+0%",
                   pitch: str = "+0Hz", volume: str = "+0%") -> Path:
    """Synthesize `text` into an MP3. rate like '+10%' / '-15%'."""
    text = text.strip()
    if not text:
        raise ValueError("Kịch bản trống")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    coro = _synthesize(text, out, _resolve_voice(voice), rate, pitch, volume)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)
    else:  # called from inside an event loop (e.g. a web server) -> run in a worker thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(1) as ex:
            ex.submit(asyncio.run, coro).result()
    return out
