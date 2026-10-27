"""Video effects: Color grading presets, dynamic Auto Zoom (Punch-in), and Watermarks."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .ffmpeg_utils import escape_filter_path

# Pre-tuned color grading filters using native FFmpeg eq and colorbalance
COLOR_PRESETS: dict[str, str] = {
    "none": "",
    "cinematic": "eq=contrast=1.14:brightness=0.01:saturation=1.22,colorbalance=rs=0.06:gs=0.01:bs=-0.04:rm=-0.02:gm=0.01:bm=0.06",
    "warm_pastel": "eq=saturation=1.12:contrast=1.04:brightness=0.03,colorbalance=rs=0.05:gs=0.02:bs=-0.03",
    "korean_clean": "eq=brightness=0.05:contrast=1.06:saturation=0.96,colorbalance=bs=0.04:bm=0.03",
    "vintage": "eq=contrast=1.12:saturation=0.78:brightness=-0.02,colorbalance=rs=0.07:gs=0.01:bs=-0.05",
    "vibrant": "eq=saturation=1.35:contrast=1.12:brightness=0.01",
}


def get_system_font() -> Optional[str]:
    """Find a standard TTF/OTF font on Windows/macOS/Linux to avoid Fontconfig crashes."""
    candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/tahoma.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/System/Library/Fonts/Helvetica.ttc"),
    ]
    for p in candidates:
        if p.exists():
            return escape_filter_path(p)
    return None


def build_punch_in_filter(interval: float = 4.0, zoom_factor: float = 1.15) -> str:
    """Dynamic punch-in / auto zoom: alternates between 1.0x and 1.15x every `interval` seconds.
    Creates a dynamic, professional multicam feel for talking head videos."""
    cycle = interval * 2
    # When mod(t, cycle) >= interval, zoom in by cropping in_w/zoom_factor and scaling back up
    w_expr = f"if(gte(mod(t\\,{cycle})\\,{interval})\\,in_w/{zoom_factor:.2f}\\,in_w)"
    h_expr = f"if(gte(mod(t\\,{cycle})\\,{interval})\\,in_h/{zoom_factor:.2f}\\,in_h)"
    return f"crop=w='{w_expr}':h='{h_expr}':x='(in_w-out_w)/2':y='(in_h-out_h)/2',scale=iw:ih"


def build_watermark_filter(text: str, position: str = "top_right", font_size: int = 24) -> str:
    """Draw simple clean text watermark / channel handle with explicit fontfile."""
    clean_text = text.replace("'", "").replace(":", "").strip()
    if not clean_text:
        return ""
    pos_map = {
        "top_right": "x=w-tw-28:y=28",
        "top_left": "x=28:y=28",
        "bottom_right": "x=w-tw-28:y=h-th-28",
        "bottom_left": "x=28:y=h-th-28",
    }
    coord = pos_map.get(position, pos_map["top_right"])
    font_file = get_system_font()
    font_arg = f"fontfile='{font_file}':" if font_file else ""
    return f"drawtext={font_arg}text='{clean_text}':fontcolor=white@0.75:fontsize={font_size}:{coord}:shadowcolor=black@0.5:shadowx=2:shadowy=2"
