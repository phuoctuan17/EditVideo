"""CLI to test the core engine.

  python cli.py silence in.mp4 out.mp4 --min-silence 0.5
  python cli.py subtitle in.mp4 out.ass [--burn out_sub.mp4]
  python cli.py tts "Xin chào các bạn" voice.mp3 --voice namminh
"""
import argparse
import sys

from core import silence, subtitles, tts


def bar(p: float) -> None:
    n = int(p * 30)
    print(f"\r[{'#' * n}{'.' * (30 - n)}] {p * 100:5.1f}%", end="", flush=True)
    if p >= 1:
        print()


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("silence")
    s.add_argument("src"); s.add_argument("dst")
    s.add_argument("--min-silence", type=float, default=0.5)
    s.add_argument("--noise-db", type=float, default=-35)
    s.add_argument("--cpu", action="store_true")

    c = sub.add_parser("subtitle")
    c.add_argument("src"); c.add_argument("ass")
    c.add_argument("--model", default="small"); c.add_argument("--lang", default="vi")
    c.add_argument("--burn")
    c.add_argument("--cpu", action="store_true")

    t = sub.add_parser("tts")
    t.add_argument("text"); t.add_argument("dst")
    t.add_argument("--voice", default="hoaimy"); t.add_argument("--rate", default="+0%")

    a = ap.parse_args()
    if a.cmd == "silence":
        print(silence.remove_silence(a.src, a.dst, a.min_silence, a.noise_db,
                                     use_gpu=not a.cpu, on_progress=bar))
    elif a.cmd == "subtitle":
        subtitles.generate_karaoke_ass(a.src, a.ass, a.model, a.lang,
                                       "cpu" if a.cpu else "auto", bar)
        if a.burn:
            subtitles.burn_subtitles(a.src, a.ass, a.burn, not a.cpu, on_progress=bar)
    else:
        print(tts.text_to_speech(a.text, a.dst, a.voice, a.rate))


if __name__ == "__main__":
    sys.exit(main())
