"""Zoom check: full-res filmstrip of the hardest transitions + colour fidelity vs source.

Usage:
  python check_quality.py                                   # default case: v2/mimo2_key.gif
  python check_quality.py --gif runs/v2-legacy-x/mimo2_key.gif
  python check_quality.py --gif out.gif --transitions 2,3 5,6
"""
import argparse
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import morph
from morph import crisp_alpha

ROOT = Path(__file__).resolve().parent


def white(f):
    a = f[..., 3:4]
    return ((f[..., :3] * a + (1 - a)).clip(0, 1) * 255).round().astype(np.uint8)


def parse_transition(text):
    parts = text.replace(" ", ",").split(",")
    if len(parts) != 2:
        raise ValueError("transition must look like 2,3 (got %r)" % text)
    return int(parts[0]), int(parts[1])


def strip(keys, i, j, outdir, frames_dir=None):
    d_ab, d_ba = morph.get_flow(i, j, frames_dir=frames_dir)
    A, B = keys[i - 1], keys[j - 1]
    frames = [(i, A)]
    for (t, src) in [(0.24, "A"), (0.52, "B"), (0.78, "B")]:
        f = morph.warp_premult(A, t * d_ab) if src == "A" else morph.warp_premult(B, (1 - t) * d_ba)
        frames.append(("%.2f%s" % (t, src), crisp_alpha(f)))
    frames.append((j, B))
    tiles = []
    for lab, f in frames:
        t = Image.fromarray(white(f), "RGB")
        tiles.append((str(lab), t))
    w, h = tiles[0][1].size
    sheet = Image.new("RGB", (w * len(tiles) + 6 * (len(tiles) - 1), h), (255, 0, 200))
    d = ImageDraw.Draw(sheet)
    for k, (lab, t) in enumerate(tiles):
        sheet.paste(t, (k * (w + 6), 0))
        d.text((k * (w + 6) + 6, 4), lab, fill=(0, 120, 255))
    sheet = sheet.resize((int(sheet.width * 0.45), int(sheet.height * 0.45)), Image.LANCZOS)
    out = os.path.join(outdir, "_strip_hard_%02d_%02d.png" % (i, j))
    sheet.save(out)
    print("saved %s" % out)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Colour fidelity + transition filmstrips for a built GIF.")
    parser.add_argument("--gif", default=str(ROOT / "mimo2_key.gif"),
                        help="built GIF whose first frame is compared against key 1 "
                             "(default: the historical v2/mimo2_key.gif)")
    parser.add_argument("--transitions", nargs="*", type=parse_transition,
                        default=[(2, 3), (11, 12), (13, 14)],
                        help="key pairs to filmstrip, as i,j (default: 2,3 11,12 13,14)")
    parser.add_argument("--frames-dir", default=None,
                        help="key frame directory (default: morph's bundled v2/frames_key)")
    parser.add_argument("--count", type=int, default=morph.N,
                        help="number of keys in --frames-dir (default: 16)")
    parser.add_argument("--outdir", help="output directory (default: next to the GIF)")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.gif):
        parser.error("GIF not found: %s" % args.gif)
    for (i, j) in args.transitions:
        if not (1 <= i <= args.count and 1 <= j <= args.count):
            parser.error("transition %d,%d outside keys 1..%d" % (i, j, args.count))

    keys = [morph.load_key(i, args.frames_dir) for i in range(1, args.count + 1)]
    outdir = args.outdir or os.path.dirname(os.path.abspath(args.gif))
    os.makedirs(outdir, exist_ok=True)

    # --- colour fidelity: key frame 1 from the GIF vs the source keyframe ---
    im = Image.open(args.gif)
    gif0 = np.asarray(im.convert("RGB")).astype(np.float32)
    src0 = white(keys[0]).astype(np.float32)
    print("key frame 1 colour MAE (GIF vs source): %.1f / 255" % np.abs(gif0 - src0).mean())

    for (i, j) in args.transitions:
        strip(keys, i, j, outdir, args.frames_dir)


if __name__ == "__main__":
    main()
