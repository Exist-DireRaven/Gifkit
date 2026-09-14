"""Stage-by-stage spatial debug for single-frame displacement reports.

Reproduces the own-sheet pipeline (keyed sheet -> grid -> boxes -> cut ->
anchor -> place) and records, for every frame, the geometry at each stage:

  grid_bbox   cell rect from the even grid (pure geometry)
  box         cut rect actually used
  ink_bbox    ink extent inside the box (absolute sheet coordinates)
  components  connected ink components inside the box (count / sizes)
  anchor_x    dense-alpha anchor of the crop (what placement centers on)
  canvas_x/y  placement offset
  out_bbox    ink extent in the placed frame

Writes debug_geometry.json plus a MAD-based SPATIAL OUTLIER report (median /
MAD, no fixed thresholds).

Usage:
  python debug_spatial.py --run GIF/Gifkit-20260913-170732
  python debug_spatial.py --sheet path/sheet_keyed.png --boxes path/boxes.json \
      --grid 6 8 --canvas 159 220 --baseline 212 [--alpha-solid 96]
"""
import argparse
import glob
import json
import os

import numpy as np
from PIL import Image
from scipy import ndimage as ndi


def record_stages(keyed_path, boxes, grid, canvas, baseline, alpha_solid=96):
    ink = np.asarray(Image.open(keyed_path).convert("RGBA"))[..., 3] > 24
    H, W = ink.shape
    rows, cols = grid
    ch, cw = H // rows, W // cols
    records = []
    for r in range(rows):
        for c in range(cols):
            i = r * cols + c + 1
            grid_bbox = [c * cw, r * ch, (c + 1) * cw, (r + 1) * ch]
            bx0, by0, bx1, by1 = boxes["%d,%d" % (r, c)]
            crop_alpha = np.asarray(
                Image.open(keyed_path).convert("RGBA"))[..., 3][by0:by1, bx0:bx1] / 255.0
            iys, ixs = np.nonzero(crop_alpha >= alpha_solid / 255.0)
            ink_bbox = ([int(ixs.min() + bx0), int(iys.min() + by0),
                         int(ixs.max() + bx0), int(iys.max() + by0)] if len(iys) else None)
            lab, n = ndi.label(crop_alpha >= alpha_solid / 255.0)
            sizes = np.bincount(lab.ravel())[1:] if n else np.array([])
            b = ndi.uniform_filter(crop_alpha, size=31, mode="constant") ** 2
            anchor_x = float((np.arange(crop_alpha.shape[1])[None, :] * b).sum() /
                             max(b.sum(), 1e-9))
            ox = int(round(canvas[0] / 2 - anchor_x))
            oy = (baseline - int(iys[-1])) if len(iys) else baseline - crop_alpha.shape[0]
            rec = dict(frame=i, row=r + 1, col=c + 1,
                       grid_bbox=grid_bbox, box=[bx0, by0, bx1, by1],
                       ink_bbox=ink_bbox, components=int(n),
                       comp_sizes=sorted(int(s) for s in sizes),
                       anchor_x=round(anchor_x, 2),
                       anchor_x_abs=round(anchor_x + bx0, 2),
                       placed_anchor_x=round(anchor_x + ox, 2),
                       canvas_x=ox, canvas_y=oy,
                       out_size=[canvas[0], canvas[1]])
            # 放置后的墨迹范围（绝对画布坐标）
            sh, sw = crop_alpha.shape
            sx0 = max(0, -ox); sy0 = max(0, -oy)
            dx0 = max(0, ox); dy0 = max(0, oy)
            cp_w = min(sw - sx0, canvas[0] - dx0); cp_h = min(sh - sy0, canvas[1] - dy0)
            placed = np.zeros((canvas[1], canvas[0]), bool)
            placed[dy0:dy0 + cp_h, dx0:dx0 + cp_w] = crop_alpha[sy0:sy0 + cp_h, sx0:sx0 + cp_w] >= alpha_solid / 255.0
            pys, pxs = np.nonzero(placed)
            rec["out_bbox"] = ([int(pxs.min()), int(pys.min()),
                                int(pxs.max()), int(pys.max())] if len(pys) else None)
            records.append(rec)
    return records


def mad_outliers(records, key):
    vals = np.array([r[key] for r in records], float)
    med = np.median(vals)
    mad = np.median(np.abs(vals - med))
    if mad < 1e-9:
        mad = 1.0
    out = [(r["frame"], round(float(v), 1), round(float(z), 1))
           for r, v, z in zip(records, vals, np.abs(vals - med) / (1.4826 * mad)) if z > 3.5]
    return med, out


def main():
    ap = argparse.ArgumentParser(description="Stage-by-stage spatial debug.")
    ap.add_argument("--run", help="run directory containing gui_case.json + boxes.json")
    ap.add_argument("--sheet", help="keyed sheet PNG (overrides --run)")
    ap.add_argument("--boxes", help="boxes JSON (overrides --run)")
    ap.add_argument("--grid", nargs=2, type=int)
    ap.add_argument("--canvas", nargs=2, type=int)
    ap.add_argument("--baseline", type=int)
    ap.add_argument("--alpha-solid", type=int, default=96)
    ap.add_argument("--out", help="output JSON path (default: <run>/debug_geometry.json)")
    args = ap.parse_args()

    if args.run:
        cfg = json.load(open(os.path.join(args.run, "gui_case.json"), encoding="utf-8"))
        sheet = cfg["source"]
        boxes_path = os.path.join(args.run, "boxes.json")
        boxes = json.load(open(boxes_path, encoding="utf-8"))
        grid, canvas, baseline = cfg["grid"], cfg["canvas"], cfg["baseline"]
        alpha_solid = cfg.get("alpha_solid", 96)
        out_path = args.out or os.path.join(args.run, "debug_geometry.json")
    else:
        sheet, boxes_path = args.sheet, args.boxes
        grid, canvas, baseline = args.grid, args.canvas, args.baseline
        alpha_solid = args.alpha_solid
        out_path = args.out or "debug_geometry.json"
        boxes = json.load(open(boxes_path, encoding="utf-8"))
    for p in (sheet, boxes_path):
        if not os.path.isfile(p):
            raise SystemExit("file not found: %s" % p)

    records = record_stages(sheet, boxes, grid, canvas, baseline, alpha_solid)
    json.dump(records, open(out_path, "w", encoding="utf-8"), indent=1)
    print("wrote %s (%d frames)" % (out_path, len(records)))

    for name, key in (("锚点x(框内)", "anchor_x"),
                      ("锚点x(绝对)", "anchor_x_abs"),
                      ("锚点x(放置后)", "placed_anchor_x"),
                      ("墨迹左缘", None), ("墨迹右缘", None),
                      ("墨迹顶缘", None), ("墨迹底缘", None)):
        if key is None:
            idx = {"墨迹左缘": 0, "墨迹右缘": 2, "墨迹顶缘": 1, "墨迹底缘": 3}[name]
            vals = [r["ink_bbox"][idx] if r["ink_bbox"] else None for r in records]
            pairs = [(r["frame"], v) for r, v in zip(records, vals) if v is not None]
            med = float(np.median([v for _, v in pairs]))
            mad = float(np.median([abs(v - med) for _, v in pairs])) or 1.0
            out = [(f, round(v, 1), round(abs(v - med) / (1.4826 * mad), 1))
                   for f, v in pairs if abs(v - med) / (1.4826 * mad) > 3.5]
        else:
            med, out = mad_outliers(records, key)
        print("%-8s 中位=%8.1f | SPATIAL OUTLIER: %s" % (name, med, out if out else "无"))


if __name__ == "__main__":
    main()
