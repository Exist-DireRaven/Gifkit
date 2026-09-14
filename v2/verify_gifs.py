"""Render generated GIFs back to montages for verification.

Usage:
  python verify_gifs.py                          # default case: mimo2_smooth.gif + mimo2_key.gif
  python verify_gifs.py runs/v2-legacy-x/*.gif   # verify arbitrary GIFs
  python verify_gifs.py out.gif --cols 6 --tile 200

Montages are written as _check_<gif-stem>.png next to each input GIF
(or into --outdir when given).
"""
import argparse
import os
from pathlib import Path

from PIL import Image, ImageSequence, ImageDraw

ROOT = Path(__file__).resolve().parent

# Default verification case: the historical v2 outputs with their montage layout.
DEFAULT_CASE = [
    ("mimo2_smooth.gif", 8, 176),
    ("mimo2_key.gif", 4, 176),
]


def montage(path, cols, tile, out_path):
    im = Image.open(path)
    frames = [f.convert("RGBA").copy() for f in ImageSequence.Iterator(im)]
    durs = []
    im2 = Image.open(path)
    for f in ImageSequence.Iterator(im2):
        durs.append(f.info.get("duration", 0))
    w, h = tile
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGB", (w * cols, h * rows), (255, 255, 255))
    for k, f in enumerate(frames):
        bg = Image.new("RGBA", f.size, (255, 255, 255, 255))
        bg.alpha_composite(f)
        t = bg.convert("RGB").resize((w, h), Image.LANCZOS)
        r, c = divmod(k, cols)
        sheet.paste(t, (c * w, r * h))
    d = ImageDraw.Draw(sheet)
    for i in range(1, cols):
        d.line([i * w, 0, i * w, sheet.height], fill=(255, 0, 200), width=1)
    for i in range(1, rows):
        d.line([0, i * h, sheet.width, i * h], fill=(255, 0, 200), width=1)
    sheet.save(out_path)
    print("%-28s %2d frames  sizes=%s  total=%.2fs -> %s" %
          (os.path.basename(path), len(frames), sorted(set(durs)), sum(durs) / 1000, out_path))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render GIF verification montages.")
    parser.add_argument("gifs", nargs="*",
                        help="GIF files to verify (default: the historical mimo2 GIFs)")
    parser.add_argument("--outdir", help="directory for _check_<stem>.png montages "
                                         "(default: next to each input GIF)")
    parser.add_argument("--cols", type=int, default=8, help="montage columns (default: 8)")
    parser.add_argument("--tile", type=int, default=176, help="montage tile size in px (default: 176)")
    args = parser.parse_args(argv)

    if args.gifs:
        missing = [g for g in args.gifs if not os.path.isfile(g)]
        if missing:
            parser.error("GIF not found: %s" % ", ".join(missing))
        jobs = [(g, args.cols, (args.tile, args.tile)) for g in args.gifs]
    else:
        jobs = [(str(ROOT / name), cols, (tile, tile))
                for name, cols, tile in DEFAULT_CASE if (ROOT / name).is_file()]
        if not jobs:
            parser.error("no default GIFs found; pass GIF paths explicitly")

    for path, cols, tile in jobs:
        outdir = args.outdir or os.path.dirname(os.path.abspath(path))
        os.makedirs(outdir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(path))[0]
        montage(path, cols, tile, os.path.join(outdir, "_check_%s.png" % stem))


if __name__ == "__main__":
    main()
