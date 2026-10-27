"""FFmpeg / FFprobe wrappers: probing, running with real-time progress, GPU detection."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional, Sequence

ProgressCb = Callable[[float], None]  # receives 0.0 .. 1.0

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class FFmpegError(RuntimeError):
    pass


def require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise FFmpegError(f"Không tìm thấy '{name}' trong PATH. Cài FFmpeg: winget install Gyan.FFmpeg")
    return path


@lru_cache(maxsize=1)
def has_nvenc() -> bool:
    """True if h264_nvenc is both compiled in and actually usable on this machine."""
    try:
        r = subprocess.run(
            [require_binary("ffmpeg"), "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1",
             "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, text=True, creationflags=_NO_WINDOW)
        return r.returncode == 0
    except Exception:
        return False


def video_encoder_args(use_gpu: bool = True, quality: int = 21, fps: Optional[int] = None) -> list[str]:
    """Encoder args. NVENC when available, libx264 fallback."""
    args: list[str] = []
    if use_gpu and has_nvenc():
        args += ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr",
                 "-cq", str(quality), "-b:v", "0", "-spatial-aq", "1", "-profile:v", "high"]
    else:
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(quality)]
    args += ["-pix_fmt", "yuv420p"]
    if fps:
        args += ["-r", str(fps)]
    return args


def probe(path: str | Path) -> dict:
    r = subprocess.run(
        [require_binary("ffprobe"), "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, encoding="utf-8", creationflags=_NO_WINDOW)
    if r.returncode != 0:
        raise FFmpegError(r.stderr.strip())
    return json.loads(r.stdout)


def get_duration(path: str | Path) -> float:
    return float(probe(path)["format"]["duration"])


def get_video_size(path: str | Path) -> tuple[int, int]:
    for s in probe(path)["streams"]:
        if s["codec_type"] == "video":
            return int(s["width"]), int(s["height"])
    raise FFmpegError("File không có luồng video")


def has_audio(path: str | Path) -> bool:
    return any(s["codec_type"] == "audio" for s in probe(path)["streams"])


def run_ffmpeg(args: Sequence[str], total_duration: Optional[float] = None,
               on_progress: Optional[ProgressCb] = None) -> None:
    """Run ffmpeg with `-progress pipe:1`, reporting progress as a 0..1 fraction.

    `total_duration` is the expected OUTPUT duration in seconds.
    """
    cmd = [require_binary("ffmpeg"), "-hide_banner", "-y", "-loglevel", "error",
           "-progress", "pipe:1", "-nostats", *map(str, args)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace",
                            creationflags=_NO_WINDOW)
    time_re = re.compile(r"out_time_us=(\d+)")
    assert proc.stdout is not None
    for line in proc.stdout:
        m = time_re.match(line.strip())
        if m and total_duration and on_progress:
            on_progress(min(int(m.group(1)) / 1e6 / total_duration, 1.0))
    err = proc.stderr.read() if proc.stderr else ""
    if proc.wait() != 0:
        raise FFmpegError(f"FFmpeg lỗi (code {proc.returncode}):\n{err}\nCMD: {' '.join(cmd)}")
    if on_progress:
        on_progress(1.0)


@lru_cache(maxsize=1)
def _supports_slash_option() -> bool:
    """FFmpeg >= 7 uses `-/filter_complex file`; `-filter_complex_script` was removed."""
    r = subprocess.run([require_binary("ffmpeg"), "-hide_banner", "-version"],
                       capture_output=True, text=True, creationflags=_NO_WINDOW)
    m = re.search(r"ffmpeg version \D*(\d+)", r.stdout)
    return bool(m) and int(m.group(1)) >= 7


def filter_graph_file_args(script_path: str | Path) -> list[str]:
    """Args that make ffmpeg read a filter_complex graph from a file (avoids the Windows
    command-line length limit)."""
    if _supports_slash_option():
        return ["-/filter_complex", str(script_path)]
    return ["-filter_complex_script", str(script_path)]


def escape_filter_path(path: str | Path) -> str:
    """Escape a Windows path for use inside an ffmpeg filter (e.g. subtitles=...).

    C:\\a\\b.ass  ->  C\\:/a/b.ass
    """
    p = Path(path).resolve().as_posix()
    return p.replace(":", r"\:").replace("'", r"\'")
