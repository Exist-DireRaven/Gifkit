"""Generic sequence diagnostic: alignment stability + step smoothness.

Usage:
  python diag_seq.py                              # default case: v3/seq_melee_v4
  python diag_seq.py runs/melee-v4-x/seq_melee_v4 # any frame folder (absolute or relative path)
  python diag_seq.py seq_gun --json-out _diag.json
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parent


def resolve_folder(folder):
    """Accept a real path or a folder name relative to this script (legacy form)."""
    if os.path.isdir(folder):
        return folder
    legacy = ROOT / folder
    if legacy.is_dir():
        return str(legacy)
    raise SystemExit("sequence folder not found: %s" % folder)


def load_frames(seq_dir):
    files = sorted(f for f in os.listdir(seq_dir) if f.endswith(".png"))
    if not files:
        raise SystemExit("no .png frames in %s" % seq_dir)
    frames = []
    for f in files:
        a = np.asarray(Image.open(os.path.join(seq_dir, f)).convert("RGBA")).astype(np.float32) / 255.0
        if not (a[..., 3] > 0.5).any():
            raise SystemExit("frame has no opaque pixels: %s" % os.path.join(seq_dir, f))
        frames.append(a)
    return files, frames


def measure(frames):
    rows = []
    for k, f in enumerate(frames):
        m = f[..., 3] > 0.5
        ys, xs = np.nonzero(m)
        b = ndimage.uniform_filter(f[..., 3], size=15, mode="constant") ** 2
        xg = np.arange(f.shape[1])[None, :]
        ax = float((xg * b).sum() / max(1e-9, b.sum()))
        rows.append(dict(i=k + 1, top=int(ys.min()), bottom=int(ys.max()),
                         h=int(ys.max() - ys.min() + 1), w=int(xs.max() - xs.min() + 1),
                         area=int(m.sum()), ax=ax))
    return rows


def report(folder, frames, rows):
    print("%s : %d frames %s" % (folder, len(frames), frames[0].shape[1::-1]))
    print("\nidx  top bottom    h    w   area  anchorX")
    for r in rows:
        print("%3d %4d %5d %4d %4d %6d %8.1f" % (r["i"], r["top"], r["bottom"], r["h"], r["w"], r["area"], r["ax"]))

    bot = np.array([r["bottom"] for r in rows]); top = np.array([r["top"] for r in rows])
    ax = np.array([r["ax"] for r in rows]); hh = np.array([r["h"] for r in rows])
    print("\nground-line jitter : %d px  (%d..%d)" % (bot.max() - bot.min(), bot.min(), bot.max()))
    print("head-top spread    : %d px  (%d..%d)" % (top.max() - top.min(), top.min(), top.max()))
    print("anchor-X spread    : %.1f px" % (ax.max() - ax.min()))
    print("height spread      : %d px (%.0f%%)" % (hh.max() - hh.min(), 100 * (hh.max() / hh.min() - 1)))
    return dict(ground_line_jitter=int(bot.max() - bot.min()), head_top_spread=int(top.max() - top.min()),
                anchor_x_spread=float(ax.max() - ax.min()), height_spread=int(hh.max() - hh.min()))


def step_iou(frames):
    def iou(a, b):
        ma, mb = a[..., 3] > 0.5, b[..., 3] > 0.5
        return float((ma & mb).sum() / max(1, (ma | mb).sum()))

    print("\nstep-to-step silhouette IoU:")
    vals = []
    for k in range(1, len(frames)):
        v = iou(frames[k - 1], frames[k]); vals.append(v)
        print("  %2d -> %-2d  %.3f %s" % (k, k + 1, v, "<-- jump" if v < 0.80 else ""))
    loop = iou(frames[-1], frames[0])
    print("  loop %2d -> 1  %.3f" % (len(frames), loop))
    print("min=%.3f  mean=%.3f" % (min(vals), np.mean(vals)))
    return dict(steps=vals, loop=loop, minimum=min(vals), mean=float(np.mean(vals)))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Sequence diagnostic: alignment stability + step smoothness.")
    parser.add_argument("folder", nargs="?", default="seq_melee_v4",
                        help="sequence folder: a path, or a name relative to v3/ (default: seq_melee_v4)")
    parser.add_argument("--json-out", help="optional path for a JSON summary of the diagnostics")
    args = parser.parse_args(argv)

    seq_dir = resolve_folder(args.folder)
    files, frames = load_frames(seq_dir)
    rows = measure(frames)
    label = os.path.basename(os.path.normpath(seq_dir))
    summary = report(label, frames, rows)
    steps = step_iou(frames)

    if args.json_out:
        payload = {"folder": seq_dir, "frames": [os.path.splitext(f)[0] for f in files],
                   "rows": rows, "summary": summary, "steps": steps}
        with open(args.json_out, "w") as handle:
            json.dump(payload, handle, indent=1)
        print("wrote %s" % args.json_out)


if __name__ == "__main__":
    main()
