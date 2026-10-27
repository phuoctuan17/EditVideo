"""Audio mixing (voiceover + BGM with ducking) and final render (aspect ratio, subtitles, NVENC).

Reference FFmpeg commands (what the functions below build):

1) Dubbing + ducking (voice replaces original audio, BGM ducked by sidechain compressor):
   ffmpeg -i video.mp4 -i voice.mp3 -stream_loop -1 -i bgm.mp3 -filter_complex
     "[1:a]aformat=sample_rates=44100:channel_layouts=stereo,asplit=2[vo][sc];
      [2:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=0.35[bg];
      [bg][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck];
      [duck][vo]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.95[a]"
     -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k -t <video_duration> out.mp4

2) Final render, 16:9 -> 9:16 with blurred background + burned .ass + 60 fps on GPU:
   ffmpeg -i in.mp4 -filter_complex
     "[0:v]split=2[a][b];
      [a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:5[bg];
      [b]scale=1080:1920:force_original_aspect_ratio=decrease[fg];
      [bg][fg]overlay=(W-w)/2:(H-h)/2,fps=60,subtitles='C\\:/path/sub.ass'[v]"
     -map "[v]" -map 0:a? -c:v h264_nvenc -preset p5 -tune hq -rc vbr -cq 21 -b:v 0
     -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart out.mp4
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .ffmpeg_utils import (ProgressCb, escape_filter_path, get_duration, get_video_size,
                           has_audio, run_ffmpeg, video_encoder_args)

ASPECTS = {"original": None, "9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080)}


def mix_voiceover(video: str | Path, voice: str | Path, dst: str | Path,
                  bgm: Optional[str | Path] = None, bgm_volume: float = 0.35,
                  voice_volume: float = 1.0, keep_original: float = 0.0,
                  duck_threshold: float = 0.03, duck_ratio: float = 8.0,
                  on_progress: Optional[ProgressCb] = None) -> Path:
    """Put the TTS voice (and optional BGM, auto-ducked while the voice speaks) on `video`.
    `keep_original` (0..1) keeps some of the original audio; 0 removes it. Output length =
    video length; video stream is copied (no re-encode)."""
    video_dur = get_duration(video)
    fmt = "aformat=sample_rates=44100:channel_layouts=stereo"
    inputs: list = ["-i", video, "-i", voice]
    parts = [f"[1:a]{fmt},volume={voice_volume},asplit=2[vo][sc]"]
    mix_labels = ["[vo]"]

    if bgm:
        inputs += ["-stream_loop", "-1", "-i", bgm]
        parts.append(f"[2:a]{fmt},volume={bgm_volume}[bg]")
        parts.append(f"[bg][sc]sidechaincompress=threshold={duck_threshold}:ratio={duck_ratio}:"
                     "attack=20:release=400[duck]")
        mix_labels.append("[duck]")
    else:
        parts[0] = parts[0].replace(",asplit=2[vo][sc]", "[vo]")

    if keep_original > 0 and has_audio(video):
        parts.append(f"[0:a]{fmt},volume={keep_original}[orig]")
        mix_labels.append("[orig]")

    parts.append(f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:duration=longest:normalize=0,"
                 "alimiter=limit=0.95[a]")
    run_ffmpeg([*inputs, "-filter_complex", ";".join(parts), "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{video_dur:.3f}",
                "-movflags", "+faststart", dst],
               total_duration=video_dur, on_progress=on_progress)
    return Path(dst)


from .effects import COLOR_PRESETS, build_punch_in_filter, build_watermark_filter


def build_video_filter(src_size: tuple[int, int], aspect: str = "original", mode: str = "blur",
                       fps: Optional[int] = None, ass: Optional[str | Path] = None,
                       fonts_dir: Optional[str | Path] = None,
                       color_preset: str = "none", auto_zoom: bool = False,
                       watermark_text: str = "", watermark_pos: str = "top_right") -> tuple[str, tuple[int, int]]:
    """Return (filter_complex graph ending in [v], output_size)."""
    target = ASPECTS.get(aspect)
    w, h = target or src_size
    chain: list[str] = []
    if target is None:
        chain.append("[0:v]null[base]")
    elif abs(src_size[0] / src_size[1] - w / h) < 0.01:
        chain.append(f"[0:v]scale={w}:{h},setsar=1[base]")
    elif mode == "crop":
        chain.append(f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
                     f"crop={w}:{h},setsar=1[base]")
    else:  # blur background
        chain.append("[0:v]split=2[a][b]")
        chain.append(f"[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                     "boxblur=25:5,eq=brightness=-0.05[bg]")
        chain.append(f"[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg]")
        chain.append("[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[base]")

    post = []
    if auto_zoom:
        post.append(build_punch_in_filter())
    if color_preset and color_preset in COLOR_PRESETS and COLOR_PRESETS[color_preset]:
        post.append(COLOR_PRESETS[color_preset])
    if watermark_text.strip():
        wm_f = build_watermark_filter(watermark_text, watermark_pos, font_size=max(int(h * 0.022), 18))
        if wm_f:
            post.append(wm_f)
    if fps:
        post.append(f"fps={fps}")
    if ass:
        sub = f"subtitles='{escape_filter_path(ass)}'"
        if fonts_dir:
            sub += f":fontsdir='{escape_filter_path(fonts_dir)}'"
        post.append(sub)

    chain.append("[base]" + (",".join(post) if post else "null") + "[v]")
    return ";".join(chain), (w, h)


def final_render(src: str | Path, dst: str | Path, aspect: str = "original", mode: str = "blur",
                 fps: Optional[int] = 60, ass: Optional[str | Path] = None, use_gpu: bool = True,
                 fonts_dir: Optional[str | Path] = None,
                 color_preset: str = "none", auto_zoom: bool = False,
                 watermark_text: str = "", watermark_pos: str = "top_right",
                 on_progress: Optional[ProgressCb] = None) -> Path:
    """One pass: aspect conversion + color/zoom/watermark + subtitle burn-in + encode."""
    size = get_video_size(src)
    graph, _ = build_video_filter(size, aspect, mode, fps, ass, fonts_dir,
                                  color_preset=color_preset, auto_zoom=auto_zoom,
                                  watermark_text=watermark_text, watermark_pos=watermark_pos)
    args = ["-i", src, "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
            *video_encoder_args(use_gpu), "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", dst]
    run_ffmpeg(args, total_duration=get_duration(src), on_progress=on_progress)
    return Path(dst)
