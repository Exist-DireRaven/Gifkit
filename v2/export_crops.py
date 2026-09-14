"""Export row strips and individual cell crops for close inspection."""
import argparse
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export row strips and 2x cell crops.")
    parser.add_argument("--source", default=str(ROOT / "mimo2.png"), help="sheet image")
    parser.add_argument("--boxes", default=str(ROOT / "_boxes.json"), help="boxes JSON")
    parser.add_argument("--out-dir", default=str(ROOT), help="where the crops are written")
    parser.add_argument("--grid", type=int, default=4, help="grid size (default: 4 -> 4x4)")
    args = parser.parse_args(argv)

    im = Image.open(args.source).convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    bg.alpha_composite(im)
    rgb = bg.convert("RGB")

    with open(args.boxes, encoding="utf-8") as handle:
        boxes = {tuple(map(int, k.split(","))): v for k, v in json.load(handle).items()}

    # row strips: crop the union of each row's cells, 1:1
    for r in range(args.grid):
        xs0 = min(boxes[(r, c)][0] for c in range(args.grid))
        ys0 = min(boxes[(r, c)][1] for c in range(args.grid))
        xs1 = max(boxes[(r, c)][2] for c in range(args.grid))
        ys1 = max(boxes[(r, c)][3] for c in range(args.grid))
        strip = rgb.crop((xs0, ys0, xs1, ys1))
        strip.save(os.path.join(args.out_dir, "_row%d.png" % (r + 1)))
        print("row%d strip: %s from (%d,%d)-(%d,%d)" % (r + 1, strip.size, xs0, ys0, xs1, ys1))

    # individual cells, upscaled 2x for detail
    for r in range(args.grid):
        for c in range(args.grid):
            x0, y0, x1, y1 = boxes[(r, c)]
            cell = rgb.crop((x0, y0, x1, y1))
            cell = cell.resize((cell.width * 2, cell.height * 2), Image.LANCZOS)
            cell.save(os.path.join(args.out_dir, "_cell_r%dc%d.png" % (r + 1, c + 1)))
    print("saved %d cell crops (2x)" % (args.grid * args.grid))


if __name__ == "__main__":
    main()
