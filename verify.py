"""Read generated GIFs back and render verification montages.

Usage:
  python verify.py                       # default case: the three historical mimo_loop GIFs
  python verify.py path/to/a.gif b.gif   # verify arbitrary GIFs
  python verify.py run/out.gif --bg white --scale 0.5 --cols 6

Montages are written as _check_<gif-stem>.png next to each input GIF
(or into --outdir when given).
"""
import argparse
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageSequence

ROOT = Path(__file__).resolve().parent

# Default verification case: the historical v1 outputs, with the per-GIF
# presentation that was originally hard-coded in the loop below.
DEFAULT_CASE = [
    ("mimo_loop.gif", "white", 0.5, 4),
    ("mimo_loop_transparent.gif", "checker", 0.5, 4),
    ("mimo_loop_small.gif", "checker", 1.0, 4),
]


def montage(path, cols=4, bg="checker", scale=1.0):
    im = Image.open(path)
    frames = []
    for fr in ImageSequence.Iterator(im):
        frames.append(fr.convert("RGBA").copy())
    w, h = frames[0].size
    if scale != 1.0:
        nw, nh = int(w * scale), int(h * scale)
        frames = [f.resize((nw, nh), Image.LANCZOS) for f in frames]
        w, h = nw, nh
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGB", (w * cols, h * rows), (255, 255, 255))
    for i, f in enumerate(frames):
        if bg == "checker":
            tile = Image.new("RGB", (w, h), (210, 210, 215))
            d = ImageDraw.Draw(tile)
            for yy in range(0, h, 16):
                for xx in range(0, w, 16):
                    if (xx // 16 + yy // 16) % 2 == 0:
                        d.rectangle([xx, yy, xx + 15, yy + 15], fill=(238, 238, 242))
            tile = Image.alpha_composite(tile.convert("RGBA"), f).convert("RGB")
        elif bg == "dark":
            # dark background exposes edge artefacts (dark halos / light fringes)
            tile = Image.new("RGB", (w, h), (24, 24, 30))
            tile = Image.alpha_composite(tile.convert("RGBA"), f).convert("RGB")
        else:
            tile = Image.new("RGB", (w, h), (255, 255, 255))
            tile = Image.alpha_composite(tile.convert("RGBA"), f).convert("RGB")
        r, c = divmod(i, cols)
        sheet.paste(tile, (c * w, r * h))
    d = ImageDraw.Draw(sheet)
    for i in range(1, cols):
        d.line([i * w, 0, i * w, sheet.height], fill=(255, 0, 200), width=1)
    for i in range(1, rows):
        d.line([0, i * h, sheet.width, i * h], fill=(255, 0, 200), width=1)
    return sheet, frames, im.info


def verify_one(path, bg, scale, cols, outdir):
    sheet, frames, info = montage(path, bg=bg, scale=scale, cols=cols)
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    out = os.path.join(outdir, "_check_%s.png" % stem)
    sheet.save(out)
    print("%-32s frames=%d size=%s loop=%s dur=%s -> %s"
          % (os.path.basename(path), len(frames), frames[0].size, info.get("loop"),
             info.get("duration"), out))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render verification montages from GIF files.")
    parser.add_argument("gifs", nargs="*",
                        help="GIF files to verify (default: the historical mimo_loop GIFs)")
    parser.add_argument("--outdir", help="directory for _check_<stem>.png montages "
                                         "(default: next to each input GIF)")
    parser.add_argument("--cols", type=int, default=4, help="montage columns (default: 4)")
    parser.add_argument("--scale", type=float, default=1.0, help="montage tile scale (default: 1.0)")
    parser.add_argument("--bg", choices=("checker", "white", "dark"), default="checker",
                        help="montage background (default: checker; 'dark' exposes edge artefacts)")
    args = parser.parse_args(argv)

    if args.gifs:
        missing = [g for g in args.gifs if not os.path.isfile(g)]
        if missing:
            parser.error("GIF not found: %s" % ", ".join(missing))
        jobs = [(g, args.bg, args.scale, args.cols) for g in args.gifs]
    else:
        jobs = [(str(ROOT / name), bg, scale, cols)
                for name, bg, scale, cols in DEFAULT_CASE if (ROOT / name).is_file()]
        if not jobs:
            parser.error("no default GIFs found; pass GIF paths explicitly")

    for path, bg, scale, cols in jobs:
        outdir = args.outdir or os.path.dirname(os.path.abspath(path))
        verify_one(path, bg, scale, cols, outdir)


if __name__ == "__main__":
    main()
