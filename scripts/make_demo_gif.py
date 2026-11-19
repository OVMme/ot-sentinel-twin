#!/usr/bin/env python3
"""Assemble frames recorded by frontend/scripts/record-demo-frames.mjs into an animated GIF.

Development helper only (requires Pillow: ``pip install pillow``; not a runtime dependency).
    python scripts/make_demo_gif.py <frames_dir> docs/screenshots/demo.gif [--width 960] [--ms 300]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("frames", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--width", type=int, default=960)
    ap.add_argument("--ms", type=int, default=300, help="frame duration in milliseconds")
    args = ap.parse_args()
    files = sorted(args.frames.glob("frame-*.png"))
    if not files:
        raise SystemExit("no frames found")
    frames = []
    for f in files:
        im = Image.open(f).convert("RGB")
        h = round(im.height * args.width / im.width)
        im = im.resize((args.width, h), Image.Resampling.LANCZOS)
        frames.append(im.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
    durations = [args.ms] * len(frames)
    durations[-1] = 2500  # hold the final state
    args.out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        args.out, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True
    )
    print(f"{args.out} ({len(frames)} frames, {args.out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
