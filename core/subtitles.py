"""Auto karaoke subtitles: Faster-Whisper (word timestamps) -> .ass with \\kf word highlight."""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .ffmpeg_utils import (ProgressCb, escape_filter_path, get_duration, get_video_size,
                           require_binary, run_ffmpeg, video_encoder_args, _NO_WINDOW)


@dataclass
class Word:
    text: str
    start: float
    end: float


def extract_audio(video: str | Path, wav: str | Path) -> None:
    """16 kHz mono WAV - the format Whisper wants."""
    run_ffmpeg(["-i", video, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav])


_MODEL_CACHE: dict = {}


def _register_cuda_dlls() -> None:
    """Windows: cuBLAS/cuDNN installed via pip live in site-packages/nvidia/*/bin, which is not
    on the DLL search path by default."""
    import os
    import site
    import sys
    if sys.platform != "win32":
        return
    roots = [Path(p) / "nvidia" for p in site.getsitepackages() + [site.getusersitepackages()]]
    for root in roots:
        for b in root.glob("*/bin") if root.exists() else []:
            os.add_dll_directory(str(b))
            os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")


def _load_model(model_size: str, device: str):
    from faster_whisper import WhisperModel
    key = (model_size, device)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    _register_cuda_dlls()
    attempts = ([("cuda", "int8_float16"), ("cpu", "int8")] if device in ("auto", "cuda")
                else [("cpu", "int8")])
    last: Exception | None = None
    for dev, ctype in attempts:
        try:
            model = WhisperModel(model_size, device=dev, compute_type=ctype)
            _MODEL_CACHE[key] = model
            return model
        except Exception as e:  # CUDA/cuDNN missing -> fall back to CPU
            last = e
    raise RuntimeError(f"Không tải được Whisper model: {last}")


def transcribe_words(audio: str | Path, model_size: str = "small", language: Optional[str] = "vi",
                     device: str = "auto", on_progress: Optional[ProgressCb] = None) -> list[Word]:
    import wave
    import numpy as np
    total = get_duration(audio)
    with wave.open(str(audio), "rb") as wf:  # our own 16 kHz mono PCM -> no PyAV decoding needed
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    samples = pcm.astype(np.float32) / 32768.0

    def run(model) -> list[Word]:
        segments, _ = model.transcribe(samples, language=language, word_timestamps=True,
                                       vad_filter=True, beam_size=5)
        words: list[Word] = []
        for seg in segments:  # generator -> lets us report progress
            for w in seg.words or []:
                t = w.word.strip()
                if t:
                    words.append(Word(t, w.start, w.end))
            if on_progress and total:
                on_progress(min(seg.end / total, 1.0))
        return words

    try:
        return run(_load_model(model_size, device))
    except RuntimeError as e:
        # CUDA libs are only resolved lazily at the first inference call -> retry on CPU.
        if device == "cpu" or not any(k in str(e).lower() for k in ("cublas", "cudnn", "cuda", "dll")):
            raise
        _MODEL_CACHE.pop((model_size, device), None)
        return run(_load_model(model_size, "cpu"))


def group_words(words: list[Word], max_words: int = 4, max_chars: int = 22,
                max_gap: float = 0.8) -> list[list[Word]]:
    """Chunk words into short on-screen lines (CapCut style)."""
    lines: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        if cur:
            chars = sum(len(x.text) + 1 for x in cur) + len(w.text)
            if (len(cur) >= max_words or chars > max_chars or w.start - cur[-1].end > max_gap
                    or cur[-1].text[-1] in ".?!"):
                lines.append(cur)
                cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def _ass_time(t: float) -> str:
    t = max(t, 0.0)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_color(rgb_hex: str) -> str:
    """'#RRGGBB' -> ASS '&H00BBGGRR'."""
    h = rgb_hex.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def words_to_ass(words: list[Word], out_path: str | Path, width: int = 1920, height: int = 1080,
                 font: str = "Montserrat ExtraBold", font_size: Optional[int] = None,
                 highlight: str = "#FFD400", base: str = "#FFFFFF", outline: str = "#000000",
                 uppercase: bool = True, margin_v_ratio: float = 0.18) -> Path:
    """Write ASS with karaoke tags. In ASS karaoke, text is drawn in SecondaryColour until the
    word is reached and then fills to PrimaryColour -> Primary=highlight, Secondary=base."""
    # Moderate, well-balanced font size (e.g. 48px for 1080p), looks neat like CapCut
    size = font_size or max(int(min(width, height) * 0.045), 24)
    outline_w = max(size // 14, 2)
    margin_v = int(height * margin_v_ratio)
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Karaoke,{font},{size},{_ass_color(highlight)},{_ass_color(base)},{_ass_color(outline)},"
        f"&H80000000,-1,0,0,0,100,100,0,0,1,{outline_w},2,2,60,60,{margin_v},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = []
    lines = group_words(words)
    for i, line in enumerate(lines):
        start = line[0].start
        # keep the line on screen until just before the next one begins (max 0.4 s tail)
        end = line[-1].end
        if i + 1 < len(lines):
            end = min(max(end, lines[i + 1][0].start - 0.02), end + 0.4)
        parts = []
        for j, w in enumerate(line):
            nxt = line[j + 1].start if j + 1 < len(line) else w.end
            dur_cs = max(int(round((nxt - w.start) * 100)), 1)  # gaps absorbed -> no drift
            txt = w.text.upper() if uppercase else w.text
            parts.append(f"{{\\kf{dur_cs}}}{txt}")
        events.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Karaoke,,0,0,0,,{' '.join(parts)}")
    out_path = Path(out_path)
    out_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")
    return out_path


def generate_karaoke_ass(video: str | Path, ass_path: str | Path, model_size: str = "small",
                         language: Optional[str] = "vi", device: str = "auto",
                         on_progress: Optional[ProgressCb] = None,
                         size: Optional[tuple[int, int]] = None, **style) -> Path:
    """`size` = final output resolution the ASS is designed for (defaults to the video's)."""
    w, h = size or get_video_size(video)
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "audio.wav"
        extract_audio(video, wav)
        if on_progress:
            on_progress(0.05)
        words = transcribe_words(wav, model_size, language, device,
                                 (lambda p: on_progress(0.05 + p * 0.95)) if on_progress else None)
    if not words:
        raise RuntimeError("Không nhận diện được lời thoại nào")
    return words_to_ass(words, ass_path, w, h, **style)


def transcribe_to_segments(video: str | Path, model_size: str = "small",
                           language: Optional[str] = "vi", device: str = "auto") -> list[dict]:
    """Transcribe video and group into editable sentence segments for the UI."""
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "audio.wav"
        extract_audio(video, wav)
        words = transcribe_words(wav, model_size, language, device)
    lines = group_words(words)
    segments = []
    for i, line in enumerate(lines):
        segments.append({
            "id": i,
            "start": round(line[0].start, 2),
            "end": round(line[-1].end, 2),
            "text": " ".join(w.text for w in line),
        })
    return segments


def segments_to_ass(segments: list[dict], out_path: str | Path, width: int = 1920, height: int = 1080,
                    font: str = "Montserrat ExtraBold", font_size: Optional[int] = None,
                    highlight: str = "#FFD400", base: str = "#FFFFFF", outline: str = "#000000",
                    uppercase: bool = True, margin_v_ratio: float = 0.18) -> Path:
    """Build .ass karaoke file from user-edited subtitle segments."""
    size = font_size or max(int(min(width, height) * 0.045), 24)
    outline_w = max(size // 14, 2)
    margin_v = int(height * margin_v_ratio)
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Karaoke,{font},{size},{_ass_color(highlight)},{_ass_color(base)},{_ass_color(outline)},"
        f"&H80000000,-1,0,0,0,100,100,0,0,1,{outline_w},2,2,60,60,{margin_v},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = []
    for i, seg in enumerate(segments):
        start = float(seg.get("start", 0))
        end = float(seg.get("end", start + 2.0))
        raw_words = [w.strip() for w in seg.get("text", "").split() if w.strip()]
        if not raw_words:
            continue
        # distribute duration evenly across words
        total_cs = max(int(round((end - start) * 100)), len(raw_words))
        word_dur = max(total_cs // len(raw_words), 1)
        parts = []
        for w in raw_words:
            txt = w.upper() if uppercase else w
            parts.append(f"{{\\kf{word_dur}}}{txt}")
        events.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Karaoke,,0,0,0,,{' '.join(parts)}")
    out = Path(out_path)
    out.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")
    return out


def burn_subtitles(video: str | Path, ass: str | Path, dst: str | Path, use_gpu: bool = True,
                   fonts_dir: Optional[str | Path] = None,
                   on_progress: Optional[ProgressCb] = None) -> None:
    """Hard-burn .ass into the video (decode on CPU for the libass filter, encode on NVENC)."""
    vf = f"subtitles='{escape_filter_path(ass)}'"
    if fonts_dir:
        vf += f":fontsdir='{escape_filter_path(fonts_dir)}'"
    run_ffmpeg(["-i", video, "-vf", vf, *video_encoder_args(use_gpu), "-c:a", "copy",
                "-movflags", "+faststart", dst],
               total_duration=get_duration(video), on_progress=on_progress)
