"""End-to-end job pipeline: silence cut -> dubbing -> karaoke subs -> aspect + final render."""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import mixer, silence, subtitles, tts
from .ffmpeg_utils import get_video_size

# on_update(stage_id, stage_fraction, message)
UpdateCb = Callable[[str, float, str], None]


@dataclass
class JobOptions:
    # silence
    cut_silence: bool = False
    min_silence: float = 0.5
    noise_db: float = -35.0
    # dubbing
    dub: bool = False
    script: str = ""
    voice: str = "hoaimy"
    rate: str = "+0%"
    bgm: Optional[str] = None
    bgm_volume: float = 0.35
    keep_original: float = 0.0
    # subtitles
    subtitles: bool = False
    sub_model: str = "small"
    sub_language: Optional[str] = "vi"
    sub_highlight: str = "#FFD400"
    sub_font: str = "Montserrat ExtraBold"
    sub_font_size: Optional[int] = None
    custom_sub_ass: Optional[str] = None
    # visual effects
    color_preset: str = "none"    # none | cinematic | warm_pastel | korean_clean | vintage | vibrant
    auto_zoom: bool = False       # dynamic punch-in
    watermark_text: str = ""
    # output
    aspect: str = "original"      # original | 9:16 | 1:1 | 16:9
    aspect_mode: str = "blur"     # blur | crop
    fps: Optional[int] = 60
    use_gpu: bool = True
    extra: dict = field(default_factory=dict)


def plan_stages(o: JobOptions) -> list[tuple[str, str, float]]:
    """[(id, label, weight)] for the stages that will actually run."""
    stages = []
    if o.cut_silence:
        stages.append(("silence", "Cắt khoảng lặng", 3))
    if o.dub:
        stages.append(("tts", "Tạo giọng đọc", 1))
        stages.append(("mix", "Trộn giọng + nhạc nền", 1))
    if o.subtitles:
        stages.append(("subs", "Nhận diện lời thoại (Whisper)", 4))
    stages.append(("render", "Render cuối (GPU)", 4))
    return stages


def run_pipeline(src: str | Path, dst: str | Path, o: JobOptions, on_update: UpdateCb) -> dict:
    stages = plan_stages(o)
    total_w = sum(w for _, _, w in stages)
    done_w = 0.0
    result: dict = {}

    def stage_cb(sid: str, label: str, weight: float):
        def cb(p: float) -> None:
            on_update(sid, p, label)
        return cb

    with tempfile.TemporaryDirectory(prefix="avedit_") as td:
        tmp = Path(td)
        current = Path(src)

        for sid, label, weight in stages:
            on_update(sid, 0.0, label)
            if sid == "silence":
                nxt = tmp / "cut.mp4"
                result["silence"] = silence.remove_silence(
                    current, nxt, o.min_silence, o.noise_db, use_gpu=o.use_gpu,
                    on_progress=stage_cb(sid, label, weight))
                current = nxt
            elif sid == "tts":
                voice_file = tmp / "voice.mp3"
                tts.text_to_speech(o.script, voice_file, o.voice, o.rate)
            elif sid == "mix":
                nxt = tmp / "dub.mp4"
                mixer.mix_voiceover(current, voice_file, nxt, o.bgm, o.bgm_volume,
                                    keep_original=o.keep_original,
                                    on_progress=stage_cb(sid, label, weight))
                current = nxt
            elif sid == "subs":
                ass = tmp / "sub.ass"
                if o.custom_sub_ass and Path(o.custom_sub_ass).exists():
                    shutil.copy(o.custom_sub_ass, ass)
                else:
                    _, size = mixer.build_video_filter(get_video_size(current), o.aspect, o.aspect_mode)
                    subtitles.generate_karaoke_ass(
                        current, ass, o.sub_model, o.sub_language, "auto" if o.use_gpu else "cpu",
                        on_progress=stage_cb(sid, label, weight), size=size,
                        highlight=o.sub_highlight, font=o.sub_font, font_size=o.sub_font_size)
            elif sid == "render":
                mixer.final_render(current, dst, o.aspect, o.aspect_mode, o.fps,
                                   ass if o.subtitles else None, o.use_gpu,
                                   color_preset=o.color_preset, auto_zoom=o.auto_zoom,
                                   watermark_text=o.watermark_text,
                                   on_progress=stage_cb(sid, label, weight))
            done_w += weight
            on_update(sid, 1.0, label)
        if not Path(dst).exists():
            shutil.copy(current, dst)
    result["total_weight"] = total_w
    return result
