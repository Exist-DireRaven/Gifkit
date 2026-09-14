"""Render generated GIFs back to montages for verification.

Usage:
  python verify_v3.py                            # default case: mimo3_gun.gif + mimo3_melee.gif
  python verify_v3.py runs/v3-x/mimo3_gun.gif    # verify arbitrary GIFs
  python verify_v3.py out.gif --cols 6 --tile 160

Montages are written as _check_<gif-stem>.png next to each input GIF
(or into --outdir when given); each tile is labelled with its index and duration.
"""
import argparse
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageSequence

ROOT = Path(__file__).resolve().parent

# Default verification case: the historical v3 outputs.
DEFAULT_CASE = ("mimo3_gun.gif", "mimo3_melee.gif")


def montage(path, cols, tile, out_path):
    im = Image.open(path)
    frames = [f.convert("RGBA").copy() for f in ImageSequence.Iterator(im)]
    durs = [f.info.get("duration", 0) for f in ImageSequence.Iterator(Image.open(path))]
    rows = (len(frames) + cols - 1) // cols
    S = Image.new("RGB", (cols * tile, rows * tile), (255, 255, 255))
    d = ImageDraw.Draw(S)
    for k, f in enumerate(frames):
        bg = Image.new("RGBA", f.size, (255, 255, 255, 255))
        bg.alpha_composite(f)
        r, c = divmod(k, cols)
        S.paste(bg.convert("RGB").resize((tile, tile), Image.LANCZOS), (c * tile, r * tile))
        d.text((c * tile + 3, r * tile + 2), "%d/%dms" % (k + 1, durs[k]), fill=(200, 0, 120))
    for i in range(1, cols):
        d.line([i * tile, 0, i * tile, S.height], fill=(230, 230, 235))
    for i in range(1, rows):
        d.line([0, i * tile, S.width, i * tile], fill=(230, 230, 235))
    S.save(out_path)
    print("%-22s %2d frames  %.2fs  motion %.2f fps -> %s" %
          (os.path.basename(path), len(frames), sum(durs) / 1000,
           sum(1 for x in durs if x <= 50) / max(1e-9, sum(x for x in durs if x <= 50) / 1000),
           out_path))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render GIF verification montages with per-frame timing labels.")
    parser.add_argument("gifs", nargs="*", help="GIF files to verify (default: the historical v3 GIFs)")
    parser.add_argument("--outdir", help="directory for _check_<stem>.png montages "
                                         "(default: next to each input GIF)")
    parser.add_argument("--cols", type=int, default=10, help="montage columns (default: 10)")
    parser.add_argument("--tile", type=int, default=128, help="montage tile size in px (default: 128)")
    args = parser.parse_args(argv)

    if args.gifs:
        missing = [g for g in args.gifs if not os.path.isfile(g)]
        if missing:
            parser.error("GIF not found: %s" % ", ".join(missing))
        jobs = list(args.gifs)
    else:
        jobs = [str(ROOT / name) for name in DEFAULT_CASE if (ROOT / name).is_file()]
        if not jobs:
            parser.error("no default GIFs found; pass GIF paths explicitly")

    for path in jobs:
        outdir = args.outdir or os.path.dirname(os.path.abspath(path))
        os.makedirs(outdir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(path))[0]
        montage(path, args.cols, args.tile, os.path.join(outdir, "_check_%s.png" % stem))


if __name__ == "__main__":
    main()
