"""Health check of the GPT frames.

1. Are sheet1 (full_*) and sheet2 (pair_*) the same generation?  Match every
   sheet2 frame against sheet1 by centroid-aligned mask overlap.
2. Per-frame scale (bbox height) and step-to-step silhouette IoU within sheet2.

Usage:
  python check_frames.py                           # default case: v3/tiles
  python check_frames.py --tiles-dir runs/x/tiles
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent


def load(tiles_dir, prefix, n):
    out = []
    for k in range(1, n + 1):
        path = os.path.join(tiles_dir, "%s_%02d.png" % (prefix, k))
        if not os.path.isfile(path):
            raise SystemExit("tile not found: %s\n"
                             "tiles are regenerable intermediates; run v3/extract_all.py first, "
                             "or point --tiles-dir at a directory that contains them." % path)
        im = Image.open(path).convert("L")
        a = np.asarray(im).astype(np.int16)
        m = a < 238
        ys, xs = np.nonzero(m)
        if ys.size == 0:
            raise SystemExit("tile has no ink (<238 grey): %s" % path)
        out.append(dict(mask=m, h=int(ys.max() - ys.min() + 1), w=int(xs.max() - xs.min() + 1),
                        cy=float(ys.mean()), cx=float(xs.mean()), area=int(m.sum())))
    return out


def align_iou(a, b):
    """IoU of two masks after centring on their ink centroid."""
    h = 200; w = 200
    def place(c):
        m = np.zeros((h, w), bool)
        y0 = int(round(h / 2 - c["cy"])); x0 = int(round(w / 2 - c["cx"]))
        ys, xs = np.nonzero(c["mask"])
        yy = np.clip(ys + y0, 0, h - 1); xx = np.clip(xs + x0, 0, w - 1)
        m[yy, xx] = True
        return m
    ma, mb = place(a), place(b)
    return (ma & mb).sum() / max(1, (ma | mb).sum())


def main(argv=None):
    parser = argparse.ArgumentParser(description="Health check of generated sprite tiles.")
    parser.add_argument("--tiles-dir", default=str(ROOT / "tiles"),
                        help="directory holding full_NN.png / pair_NN.png tiles (default: v3/tiles)")
    parser.add_argument("--full-count", type=int, default=64, help="number of full_* tiles (default: 64)")
    parser.add_argument("--pair-count", type=int, default=72, help="number of pair_* tiles (default: 72)")
    parser.add_argument("--json-out", help="output JSON path (default: <tiles-dir>/../_match.json)")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.tiles_dir):
        parser.error("tiles directory not found: %s" % args.tiles_dir)

    S1 = load(args.tiles_dir, "full", args.full_count)
    S2 = load(args.tiles_dir, "pair", args.pair_count)

    print("--- sheet2 frame -> best matching sheet1 frame ---")
    best_all = []
    for k, c in enumerate(S2, 1):
        ious = [align_iou(c, c1) for c1 in S1]
        j = int(np.argmax(ious))
        best_all.append((k, j + 1, ious[j]))
    print("frame: best_match_sheet1_iou")
    for k, j, v in best_all:
        print("  %2d -> %2d  %.3f" % (k, j, v))
    vals = np.array([v for _, _, v in best_all])
    print("median best-match IoU = %.3f  (1.0 = identical frame)" % np.median(vals))

    print("\n--- per-frame size / spacing (sheet2) ---")
    print("idx  h   w   area   stepIoU")
    for k, c in enumerate(S2, 1):
        step = "" if k == 1 else "%.3f" % align_iou(S2[k - 2], c)
        print("  %2d %4d %4d %6d   %s" % (k, c["h"], c["w"], c["area"], step))

    hs = np.array([c["h"] for c in S2])
    print("\nheight: min=%d max=%d  (scale spread %.0f%%)" % (hs.min(), hs.max(), 100 * (hs.max() / hs.min() - 1)))

    json_out = args.json_out or os.path.join(os.path.dirname(os.path.abspath(args.tiles_dir)),
                                             "_match.json")
    with open(json_out, "w") as handle:
        json.dump({"match": best_all}, handle)
    print("wrote %s" % json_out)


if __name__ == "__main__":
    main()
