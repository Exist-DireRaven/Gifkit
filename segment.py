"""Segment the 4x4 sprite sheet into 16 sprite groups via connected components.

One-off prep tool for the v1 sheet; writes _boxes.json and _verify_boxes.png
next to the source image.  NOTE: this overwrites _boxes.json.
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

ROOT = Path(__file__).resolve().parent

COL_B = [323.0, 630.0, 911.5]
ROW_B = [328.0, 635.5, 952.0]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Segment the v1 4x4 sheet into cell boxes.")
    parser.add_argument("--source", default=str(ROOT / "mimo.png"), help="sheet image")
    parser.add_argument("--out-dir", default=str(ROOT), help="where _boxes.json is written")
    args = parser.parse_args(argv)

    im = Image.open(args.source).convert("RGBA")
    rgba = np.asarray(im).astype(np.uint8)
    H, W = rgba.shape[:2]
    alpha = rgba[..., 3]

    mask = alpha > 16
    lab, n = ndimage.label(mask, structure=np.ones((3, 3), bool))
    print("components:", n)

    objs = ndimage.find_objects(lab)
    comps = []
    for i, sl in enumerate(objs, start=1):
        if sl is None:
            continue
        ys, xs = sl
        area = int((lab[sl] == i).sum())
        if area < 8:
            continue
        yy, xx = np.nonzero(lab[sl] == i)
        cy = ys.start + yy.mean()
        cx = xs.start + xx.mean()
        comps.append(dict(id=i, area=area, box=(xs.start, ys.start, xs.stop, ys.stop),
                          cx=cx, cy=cy))

    print("kept components:", len(comps), " total area:", sum(c["area"] for c in comps))

    def cell_of(c):
        col = sum(1 for b in COL_B if c["cx"] > b)
        row = sum(1 for b in ROW_B if c["cy"] > b)
        return row, col

    grid = {}
    for c in comps:
        grid.setdefault(cell_of(c), []).append(c)

    print("\ncell component counts / total area:")
    for r in range(4):
        line = []
        for cc in range(4):
            g = grid.get((r, cc), [])
            line.append("r%dc%d:%3d cmp %6d px" % (r + 1, cc + 1, len(g), sum(x["area"] for x in g)))
        print("  " + " | ".join(line))

    boxes = {}
    for key, g in grid.items():
        x0 = min(c["box"][0] for c in g); y0 = min(c["box"][1] for c in g)
        x1 = max(c["box"][2] for c in g); y1 = max(c["box"][3] for c in g)
        boxes[key] = (x0, y0, x1, y1)
        print("  cell %s box = (%4d,%4d)-(%4d,%4d)  %3dx%3d" % (key, x0, y0, x1, y1, x1 - x0, y1 - y0))

    # verification overlay: draw boxes + gutters on a white-composited copy
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

    json.dump({f"{k[0]},{k[1]}": list(map(int, v)) for k, v in boxes.items()},
              open(os.path.join(args.out_dir, "_boxes.json"), "w"), indent=1)
    print("\nsaved _verify_boxes.png / _boxes.json")


if __name__ == "__main__":
    main()
