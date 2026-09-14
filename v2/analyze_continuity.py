"""Quantify continuity between adjacent keyframes (reading order, wrap at the end).

Metrics per transition:
  dx, dy      : dense-mass centroid displacement (px)
  iou         : silhouette IoU after centroid alignment
  flow_mean   : mean optical-flow magnitude in full-res px (silhouette motion)
  flow_coh    : flow coherence |mean(v)| / mean(|v|)  (1 = coherent, 0 = chaotic)
  dpx         : mean abs pixel diff after alignment (0..255)

Usage:
  python analyze_continuity.py                                  # default case: v2/frames_key
  python analyze_continuity.py --frames-dir runs/x/frames_key --count 12
"""
import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from skimage.registration import optical_flow_tvl1

ROOT = Path(__file__).resolve().parent
DS = 2  # downsample factor for flow


def load_frames(frames_dir, pattern, start, count):
    paths = [os.path.join(frames_dir, pattern % i) for i in range(start, start + count)]
    missing = [p for p in paths if not os.path.isfile(p)]
    if missing:
        raise SystemExit("frame not found: %s" % missing[0])
    return [np.asarray(Image.open(p).convert("RGBA")).astype(np.float32) / 255.0 for p in paths]


def centroid(a):
    m = a[..., 3]
    s = m.sum()
    if s <= 0:
        return 0.0, 0.0
    ys, xs = np.mgrid[0:m.shape[0], 0:m.shape[1]]
    return float((xs * m).sum() / s), float((ys * m).sum() / s)


def shift(a, dx, dy):
    """Translate RGBA frame by (dx,dy) using bilinear sampling."""
    h, w = a.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    return sample(a, xs - dx, ys - dy)


def sample(a, xs, ys):
    h, w = a.shape[:2]
    x0 = np.floor(xs).astype(np.int32); y0 = np.floor(ys).astype(np.int32)
    fx = (xs - x0)[..., None]; fy = (ys - y0)[..., None]
    out = np.zeros((h, w, a.shape[2]), np.float32)
    for oy in (0, 1):
        for ox in (0, 1):
            yy = np.clip(y0 + oy, 0, h - 1); xx = np.clip(x0 + ox, 0, w - 1)
            wt = (fx if ox else 1 - fx) * (fy if oy else 1 - fy)
            out += a[yy, xx] * wt
    return out


def analyze(frames, start):
    rows = []
    n = len(frames)
    for i in range(n):
        a, b = frames[i], frames[(i + 1) % n]
        ca, cb = centroid(a), centroid(b)
        dx, dy = cb[0] - ca[0], cb[1] - ca[1]
        b_shift = shift(b, -dx, -dy)
        ma = a[..., 3] > 0.5
        mb = b_shift[..., 3] > 0.5
        inter = (ma & mb).sum(); union = (ma | mb).sum()
        iou = inter / max(1, union)
        dpx = float(np.abs(a[..., :3] - b_shift[..., :3]).mean() * 255)

        # flow on downsampled alpha
        aa = a[..., 3][::DS, ::DS]
        bb = b_shift[..., 3][::DS, ::DS]
        try:
            v, u = optical_flow_tvl1(bb, aa, attachment=15, num_warp=8, num_iter=20, tol=1e-4)
            mag = np.sqrt(u ** 2 + v ** 2) * DS
            fmean = float(mag.mean())
            mv = np.array([u.mean(), v.mean()]) * DS
            fcoh = float(np.linalg.norm(mv) / max(1e-6, mag.mean()))
        except Exception as e:
            fmean, fcoh = float("nan"), float("nan")
            print("flow failed for %d->%d: %s" % (start + i, start + (i + 1) % n, e), file=sys.stderr)

        rows.append(dict(i=start + i, j=start + (i + 1) % n, dx=dx, dy=dy, iou=iou,
                         fmean=fmean, fcoh=fcoh, dpx=dpx))
    return rows


def report(rows):
    print("%-9s %7s %7s %7s %9s %8s %8s  %s" %
          ("transition", "dx", "dy", "iou", "flow_mean", "flow_coh", "dpx", "verdict"))
    ious = np.array([r["iou"] for r in rows])
    fm = np.array([r["fmean"] for r in rows])
    for r in rows:
        flags = []
        if r["iou"] < 0.62: flags.append("SILHOUETTE-JUMP")
        if r["fmean"] > np.percentile(fm, 75): flags.append("high-motion")
        if r["dpx"] > 42: flags.append("big-detail-change")
        print("%2d -> %-4d %7.1f %7.1f %7.3f %9.1f %8.2f %8.1f  %s" %
              (r["i"], r["j"], r["dx"], r["dy"], r["iou"], r["fmean"], r["fcoh"], r["dpx"],
               " ".join(flags) or "-"))

    print("\nIoU   min=%.3f med=%.3f max=%.3f" % (ious.min(), np.median(ious), ious.max()))
    print("flow  min=%.1f med=%.1f max=%.1f" % (fm.min(), np.median(fm), fm.max()))
    print("\nranked by silhouette discontinuity (lowest IoU first):")
    for r in sorted(rows, key=lambda r: r["iou"])[:8]:
        print("  %2d -> %-3d  IoU=%.3f  flow=%.1f  dpx=%.1f" % (r["i"], r["j"], r["iou"], r["fmean"], r["dpx"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Continuity metrics between adjacent keyframes.")
    parser.add_argument("--frames-dir", default=str(ROOT / "frames_key"),
                        help="key frame directory (default: the bundled v2/frames_key)")
    parser.add_argument("--pattern", default="key_%02d.png",
                        help="file name pattern with one %%d placeholder (default: key_%%02d.png)")
    parser.add_argument("--start", type=int, default=1, help="first frame index (default: 1)")
    parser.add_argument("--count", type=int, default=16, help="number of frames (default: 16)")
    parser.add_argument("--json-out",
                        help="output JSON path (default: <frames-dir>/../_continuity.json)")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.frames_dir):
        parser.error("frames directory not found: %s" % args.frames_dir)
    frames = load_frames(args.frames_dir, args.pattern, args.start, args.count)
    rows = analyze(frames, args.start)
    report(rows)
    json_out = args.json_out or os.path.join(os.path.dirname(os.path.abspath(args.frames_dir)),
                                             "_continuity.json")
    with open(json_out, "w") as handle:
        json.dump(rows, handle, indent=1)
    print("wrote %s" % json_out)


if __name__ == "__main__":
    main()
