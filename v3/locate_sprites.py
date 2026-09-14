"""Locate every sprite by clustering connected components (no grid-line assumptions).

One-off prep tool for the v3 GPT sheets; writes _sprites.json next to the sheets.
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parent
MIN_AREA = 250


def cluster_1d(vals, gap):
    order = np.argsort(vals)
    groups, cur = [], [order[0]]
    for k in order[1:]:
        if vals[k] - vals[cur[-1]] <= gap:
            cur.append(k)
        else:
            groups.append(cur); cur = [k]
    groups.append(cur)
    return groups


def analyse(out_dir, name):
    a = np.asarray(Image.open(os.path.join(out_dir, name)).convert("L")).astype(np.int16)
    ink = a < 238
    lab, n = ndimage.label(ink, structure=np.ones((3, 3), bool))
    sizes = ndimage.sum(ink, lab, range(1, n + 1))
    big = int(np.argmax(sizes)) + 1          # grid network
    objs = ndimage.find_objects(lab)
    comps = []
    for k in range(1, n + 1):
        if k == big or sizes[k - 1] < MIN_AREA:
            continue
        ys, xs = objs[k - 1]
        comps.append(dict(area=int(sizes[k - 1]), box=(xs.start, ys.start, xs.stop, ys.stop),
                          cx=(xs.start + xs.stop) / 2, cy=(ys.start + ys.stop) / 2))
    cys = np.array([c["cy"] for c in comps])
    row_groups = cluster_1d(cys, 60)
    print("\n=== %s ===  parts=%d  rows=%d" % (name, len(comps), len(row_groups)))
    rows = []
    for gi, g in enumerate(row_groups):
        sel = [comps[k] for k in g]
        cxs = np.array([c["cx"] for c in sel])
        col_groups = cluster_1d(cxs, 100)
        sprites = []
        for cg in col_groups:
            grp = [sel[k] for k in cg]
            x0 = min(c["box"][0] for c in grp); y0 = min(c["box"][1] for c in grp)
            x1 = max(c["box"][2] for c in grp); y1 = max(c["box"][3] for c in grp)
            sprites.append(dict(box=(x0, y0, x1, y1), parts=len(grp),
                                area=sum(c["area"] for c in grp)))
        sprites.sort(key=lambda s: s["box"][0])
        rows.append(sprites)
        print("  row %d: %d sprites  y=%4d..%4d  widths=%s" %
              (gi + 1, len(sprites), min(s["box"][1] for s in sprites),
               max(s["box"][3] for s in sprites),
               [s["box"][2] - s["box"][0] for s in sprites]))
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description="Cluster-locate sprites on the v3 GPT sheets.")
    parser.add_argument("--dir", default=str(ROOT), help="directory holding the sheet images")
    parser.add_argument("--json-out", help="output JSON path (default: <dir>/_sprites.json)")
    args = parser.parse_args(argv)

    all_rows = {}
    for name in ("gpt_full64.png", "gpt_pairs72.png"):
        if not os.path.isfile(os.path.join(args.dir, name)):
            raise SystemExit("sheet not found: %s" % os.path.join(args.dir, name))
        rows = analyse(args.dir, name)
        all_rows[name] = [[dict(box=list(s["box"]), parts=s["parts"], area=s["area"]) for s in r] for r in rows]

    json_out = args.json_out or os.path.join(args.dir, "_sprites.json")
    json.dump(all_rows, open(json_out, "w"), indent=1)
    print("\nsaved %s" % json_out)


if __name__ == "__main__":
    main()
