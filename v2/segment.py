"""Segment the NEW 4x4 sprite sheet: tolerant gutter detection + component assignment.

One-off prep tool for the v2 sheet; writes _boxes.json and _verify_boxes.png
next to the source.  NOTE: this overwrites _boxes.json in the output directory.
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

ROOT = Path(__file__).resolve().parent


def find_boundaries(profile, n=4, win=90):
    L = len(profile)
    bs, info = [], []
    for k in range(1, n):
        exp = int(round(L * k / n))
        lo, hi = max(1, exp - win), min(L - 2, exp + win)
        seg = profile[lo:hi]
        i = int(np.argmin(seg)) + lo
        bs.append(float(i))
        info.append((exp, i, int(profile[i]), int(np.median(seg))))
    return bs, info


def main(argv=None):
    parser = argparse.ArgumentParser(description="Segment the v2 4x4 sheet into cell boxes.")
    parser.add_argument("--source", default=str(ROOT / "mimo2.png"), help="sheet image")
    parser.add_argument("--out-dir", default=str(ROOT), help="where _boxes.json is written")
    args = parser.parse_args(argv)

    im = Image.open(args.source).convert("RGBA")
    rgba = np.asarray(im)
    alpha = rgba[..., 3]
    H, W = alpha.shape
    mask = alpha > 16
    colsum = mask.sum(0); rowsum = mask.sum(1)

    COL_B, ci = find_boundaries(colsum)
    ROW_B, ri = find_boundaries(rowsum)
    print("column boundaries:", COL_B)
    for exp, i, val, med in ci:
        print("   expected %4d -> min at %4d  ink=%5d  median-in-window=%5d" % (exp, i, val, med))
    print("row boundaries:", ROW_B)
    for exp, i, val, med in ri:
        print("   expected %4d -> min at %4d  ink=%5d  median-in-window=%5d" % (exp, i, val, med))

    lab, n = ndimage.label(mask, structure=np.ones((3, 3), bool))
    objs = ndimage.find_objects(lab)
    comps = []
    for i, sl in enumerate(objs, start=1):
        if sl is None:
            continue
        sub = (lab[sl] == i)
        area = int(sub.sum())
        if area < 8:
            continue
        ys, xs = sl
        yy, xx = np.nonzero(sub)
        comps.append(dict(area=area, box=(int(xs.start), int(ys.start), int(xs.stop), int(ys.stop)),
                          cx=float(xs.start + xx.mean()), cy=float(ys.start + yy.mean())))
    print("\ncomponents kept:", len(comps), " total area:", sum(c["area"] for c in comps))

    def cell_of(c):
        return (sum(1 for b in ROW_B if c["cy"] > b), sum(1 for b in COL_B if c["cx"] > b))

    grid = {}
    for c in comps:
        grid.setdefault(cell_of(c), []).append(c)

    boxes = {}
    print("\nper-cell boxes (reading order):")
    for r in range(4):
        for c in range(4):
            k = (r, c)
            if k not in grid:
                print("  r%dc%d EMPTY" % (r + 1, c + 1)); continue
            g = grid[k]
            x0 = min(c["box"][0] for c in g); y0 = min(c["box"][1] for c in g)
            x1 = max(c["box"][2] for c in g); y1 = max(c["box"][3] for c in g)
            boxes[k] = (x0, y0, x1, y1)
            print("  r%dc%d cmp=%2d area=%6d box=(%4d,%4d)-(%4d,%4d) %3dx%3d" %
                  (r + 1, c + 1, len(g), sum(c["area"] for c in g), x0, y0, x1, y1, x1 - x0, y1 - y0))

    vis = Image.new("RGBA", im.size, (255, 255, 255, 255))
    vis.alpha_composite(im)
    d = ImageDraw.Draw(vis)
    for key, (x0, y0, x1, y1) in boxes.items():
        d.rectangle([x0 - 1, y0 - 1, x1, y1], outline=(0, 160, 255, 255), width=2)
    for b in COL_B:
        d.line([b, 0, b, H], fill=(255, 0, 255, 255), width=2)
    for b in ROW_B:
        d.line([0, b, W, b], fill=(255, 0, 255, 255), width=2)
    vis.convert("RGB").resize((627, 627), Image.LANCZOS).save(os.path.join(args.out_dir, "_verify_boxes.png"))
    json.dump({"%d,%d" % k: list(v) for k, v in boxes.items()},
              open(os.path.join(args.out_dir, "_boxes.json"), "w"), indent=1)
    print("\nsaved _verify_boxes.png / _boxes.json")


if __name__ == "__main__":
    main()
