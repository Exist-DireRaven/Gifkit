"""Extract every GPT frame and build inspection contact sheets.

One-off prep tool for the v3 GPT sheets; requires _sprites.json (from
locate_sprites.py) next to the sheets.  NOTE: this overwrites tiles/full_*
and tiles/pair_* in the tiles directory.
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent


def dump(tiles_dir, im, boxes, prefix):
    out = []
    for k, (x0, y0, x1, y1) in enumerate(boxes, 1):
        m = 4
        crop = im.crop((max(0, x0 - m), max(0, y0 - m), min(im.width, x1 + m), min(im.height, y1 + m)))
        crop.save(os.path.join(tiles_dir, "%s_%02d.png" % (prefix, k)))
        out.append(crop)
    return out


def sheet(imgs, cols, path, labels=None):
    w = max(i.width for i in imgs); h = max(i.height for i in imgs)
    rows = (len(imgs) + cols - 1) // cols
    pad = 4
    S = Image.new("RGB", (cols * (w + pad) + pad, rows * (h + pad) + pad), (225, 225, 232))
    d = ImageDraw.Draw(S)
    for k, t in enumerate(imgs):
        r, c = divmod(k, cols)
        x = pad + c * (w + pad); y = pad + r * (h + pad)
        S.paste(t, (x + (w - t.width) // 2, y + (h - t.height)))
        if labels:
            d.text((x + 2, y + 2), labels[k], fill=(200, 0, 120))
    S.save(path)
    print("saved", os.path.basename(path), S.size)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Extract GPT tiles from the v3 sheets (overwrites tiles/).")
    parser.add_argument("--dir", default=str(ROOT), help="directory holding sheets and _sprites.json")
    parser.add_argument("--tiles-dir", help="tile output directory (default: <dir>/tiles)")
    args = parser.parse_args(argv)

    out_dir = args.dir
    tiles_dir = args.tiles_dir or os.path.join(out_dir, "tiles")
    os.makedirs(tiles_dir, exist_ok=True)

    sprites_path = os.path.join(out_dir, "_sprites.json")
    if not os.path.isfile(sprites_path):
        raise SystemExit("_sprites.json not found in %s; run locate_sprites.py first" % out_dir)
    with open(sprites_path, encoding="utf-8") as handle:
        data = json.load(handle)

    # --- sheet 1: rows 2,4,6,8,10,12,13,14 are sprite rows (odd rows are labels) ---
    rows1 = data["gpt_full64.png"]
    sprite_rows1 = [1, 3, 5, 7, 9, 11, 12, 13]          # 0-based
    # --- sheet 2: drop the label column (x0 < 160) ---
    rows2 = data["gpt_pairs72.png"]

    im1 = Image.open(os.path.join(out_dir, "gpt_full64.png")).convert("RGB")
    im2 = Image.open(os.path.join(out_dir, "gpt_pairs72.png")).convert("RGB")

    full, pairs = [], []
    for r in sprite_rows1:
        assert len(rows1[r]) == 8, (r, len(rows1[r]))
        for s in rows1[r]:
            full.append(s["box"])
    for r in rows2:
        row = [s for s in r if s["box"][0] >= 160]
        assert len(row) == 8, (r, len(row))
        for s in row:
            pairs.append(s["box"])

    print("sheet1 frames: %d   sheet2 frames: %d" % (len(full), len(pairs)))

    f1 = dump(tiles_dir, im1, full, "full")
    f2 = dump(tiles_dir, im2, pairs, "pair")
    print("wrote %d + %d tiles" % (len(f1), len(f2)))
    print("sheet1 tile sizes:", sorted({c.size for c in f1}))
    print("sheet2 tile sizes:", sorted({c.size for c in f2}))

    sheet(f1, 8, os.path.join(out_dir, "_tiles_full.png"), [str(i) for i in range(1, len(f1) + 1)])
    sheet(f2, 8, os.path.join(out_dir, "_tiles_pairs.png"), [str(i) for i in range(1, len(f2) + 1)])
    json.dump({"full": full, "pairs": pairs}, open(os.path.join(out_dir, "_boxes_gpt.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
