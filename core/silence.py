"""Smart Silence Remover based on FFmpeg `silencedetect`."""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from .ffmpeg_utils import (FFmpegError, ProgressCb, filter_graph_file_args, get_duration, has_audio,
                           require_binary, run_ffmpeg, video_encoder_args, _NO_WINDOW)

Segment = tuple[float, float]


def detect_silences(src: str | Path, min_silence: float = 0.5, noise_db: float = -35.0) -> list[Segment]:
    """Return [(start, end)] of silent spans longer than `min_silence` seconds."""
    r = subprocess.run(
        [require_binary("ffmpeg"), "-hide_banner", "-nostats", "-i", str(src), "-vn",
         "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
    if r.returncode != 0:
        raise FFmpegError(r.stderr)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", r.stderr)]
    silences: list[Segment] = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else float("inf")  # silence runs to EOF
        silences.append((max(s, 0.0), e))
    return silences


def compute_keep_segments(silences: list[Segment], duration: float,
                          padding: float = 0.08, min_keep: float = 0.15) -> list[Segment]:
    """Invert silences into segments to keep. `padding` keeps a little air around speech
    so words are not clipped; tiny fragments (< min_keep) are dropped."""
    keep: list[Segment] = []
    cursor = 0.0
    for s, e in silences:
        end = min(s + padding, duration)
        if end - cursor >= min_keep:
            keep.append((cursor, end))
        cursor = max(cursor, e - padding)
        if cursor >= duration:
            break
    if duration - cursor >= min_keep:
        keep.append((cursor, duration))
    # merge overlaps created by padding
    merged: list[Segment] = []
    for seg in keep:
        if merged and seg[0] <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], seg[1]))
        else:
            merged.append(seg)
    return merged


def remove_silence(src: str | Path, dst: str | Path, min_silence: float = 0.5,
                   noise_db: float = -35.0, padding: float = 0.08, use_gpu: bool = True,
                   on_progress: Optional[ProgressCb] = None) -> dict:
    """Cut silent parts and concatenate the rest with A/V kept in sync (trim+concat filter,
    re-encoded so cuts are frame-accurate). Returns stats dict."""
    src, dst = Path(src), Path(dst)
    if not has_audio(src):
        raise FFmpegError("Video không có âm thanh để phát hiện khoảng lặng")
    duration = get_duration(src)
    if on_progress:
        on_progress(0.02)
    keep = compute_keep_segments(detect_silences(src, min_silence, noise_db), duration, padding)
    if not keep:
        raise FFmpegError("Toàn bộ video bị coi là im lặng - hãy tăng ngưỡng noise_db (ví dụ -30)")
    out_duration = sum(e - s for s, e in keep)

    parts, labels = [], []
    for i, (s, e) in enumerate(keep):
        parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}];"
                     f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[v{i}][a{i}]")
    graph = ";\n".join(parts) + f";\n{''.join(labels)}concat=n={len(keep)}:v=1:a=1[v][a]"

    # Script file avoids the Windows command-line length limit with many segments.
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(graph)
        script = f.name
    try:
        run_ffmpeg(["-i", src, *filter_graph_file_args(script), "-map", "[v]", "-map", "[a]",
                    *video_encoder_args(use_gpu), "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", dst],
                   total_duration=out_duration,
                   on_progress=(lambda p: on_progress(0.05 + p * 0.95)) if on_progress else None)
    finally:
        Path(script).unlink(missing_ok=True)

    return {"original": duration, "result": out_duration, "removed": duration - out_duration,
            "segments": len(keep)}
