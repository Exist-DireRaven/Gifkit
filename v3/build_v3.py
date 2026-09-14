"""Assemble the GPT-drawn frames into aligned frames (v3 material prep).

Fixes applied to the GPT material:
  1. sheet2 only (sheet1 is a different generation: median best-match IoU 0.706)
  2. drop the duplicated shared keyframe at every block boundary
  3. per-block scale normalisation (raw height spread is 41 %)
  4. background removed by border flood fill, then ground-line + mass-centre alignment

Outputs two self-consistent loops so the gun and the melee never share one GIF.
Writes frames_aligned/ (f01.png...) plus _v3_meta.json next to the tiles.
NOTE: this overwrites frames_aligned/ content.
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parent
CW = CH = 320
BASELINE = 296
TARGET_H = 238          # character height after normalisation
UPSCALE = 1.0


# ------------------------------------------------------------------ load
def load_rgba(tiles_dir, k):
    im = Image.open(os.path.join(tiles_dir, "pair_%02d.png" % k)).convert("RGB")
    a = np.asarray(im).astype(np.int16)
    grey = a.mean(axis=2)
    sat = a.max(axis=2) - a.min(axis=2)
    near_white = (grey >= 244) & (sat <= 12)
    lab, n = ndimage.label(near_white, structure=np.ones((3, 3), bool))
    border = set(lab[0, :]) | set(lab[-1, :]) | set(lab[:, 0]) | set(lab[:, -1])
    border.discard(0)
    bg = np.isin(lab, list(border))
    alpha = (~bg).astype(np.float32)
    alpha = ndimage.gaussian_filter(alpha, 0.6)
    out = np.dstack([np.asarray(im).astype(np.float32) / 255.0, alpha])
    return out


def ink_mask(f, thr=0.5):
    return f[..., 3] > thr


def iou_after(a, b, scale=1.0):
    """IoU of mask a and mask b (b scaled by `scale`) after centroid alignment."""
    h = w = 240
    def place(m, s=1.0):
        ys, xs = np.nonzero(m)
        if len(ys) == 0:
            return np.zeros((h, w), bool)
        cy, cx = ys.mean() * s, xs.mean() * s
        m2 = np.zeros((h, w), bool)
        yy = np.clip((ys * s).astype(int) + int(h / 2 - cy), 0, h - 1)
        xx = np.clip((xs * s).astype(int) + int(w / 2 - cx), 0, w - 1)
        m2[yy, xx] = True
        return m2
    A, B = place(a), place(b, scale)
    return (A & B).sum() / max(1, (A | B).sum())


def best_scale(mask_from, mask_to):
    """Scale that maps `mask_to` onto `mask_from`."""
    best, bs = -1, 1.0
    for s in np.linspace(0.72, 1.38, 45):
        v = iou_after(mask_from, mask_to, s)
        if v > best:
            best, bs = v, s
    return bs, best


def scale_frame(f, s):
    if abs(s - 1.0) < 1e-3:
        return f
    im = Image.fromarray((f * 255).round().astype(np.uint8), "RGBA")
    nw, nh = max(1, int(round(im.width * s))), max(1, int(round(im.height * s)))
    return np.asarray(im.resize((nw, nh), Image.LANCZOS)).astype(np.float32) / 255.0


def dense_anchor_x(f, blur=15):
    b = ndimage.uniform_filter(f[..., 3], size=blur, mode="constant") ** 2
    w = b ** 2
    if w.sum() <= 0:
        return f.shape[1] / 2.0
    xs = np.arange(f.shape[1])[None, :]
    return float((xs * w).sum() / w.sum())


def main(argv=None):
    parser = argparse.ArgumentParser(description="Align tiles onto a shared canvas (v3 material prep).")
    parser.add_argument("--tiles-dir", default=str(ROOT / "tiles"),
                        help="directory holding pair_NN.png tiles (default: v3/tiles)")
    parser.add_argument("--out-dir", default=str(ROOT),
                        help="where frames_aligned/ is written (default: v3/)")
    parser.add_argument("--tiles-count", type=int, default=72, help="number of tiles (default: 72)")
    parser.add_argument("--frames-per-block", type=int, default=8,
                        help="frames per motion block (default: 8)")
    parser.add_argument("--canvas", type=int, nargs=2, default=(320, 320), metavar=("W", "H"),
                        help="output canvas (default: 320 320)")
    parser.add_argument("--baseline", type=int, default=296,
                        help="y of the ground line (default: 296)")
    parser.add_argument("--target-height", type=float, default=238,
                        help="normalised character height in px (default: 238)")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.tiles_dir):
        raise SystemExit("tiles directory not found: %s" % args.tiles_dir)
    tiles = [load_rgba(args.tiles_dir, k) for k in range(1, args.tiles_count + 1)]
    fpb = args.frames_per_block
    if args.tiles_count % fpb:
        raise SystemExit("%d tiles is not a multiple of frames_per_block=%d" % (args.tiles_count, fpb))
    cw, ch = args.canvas
    baseline = args.baseline
    target_h = args.target_height

    # ------------------------------------------------- per-block scale normalisation
    BLOCK_FIRST = [1 + fpb * b for b in range(args.tiles_count // fpb)]   # first tile of each block
    scales = [1.0]
    print("boundary scale estimation:")
    for b in range(len(BLOCK_FIRST) - 1):
        last_of_b = BLOCK_FIRST[b] + fpb - 1
        first_of_next = BLOCK_FIRST[b + 1]
        s, q = best_scale(ink_mask(tiles[last_of_b - 1]), ink_mask(tiles[first_of_next - 1]))
        scales.append(scales[-1] * s)
        print("  block %d -> %d : scale %.3f (IoU %.3f)" % (b + 1, b + 2, s, q))
    print("cumulative block scales:", [round(s, 3) for s in scales])

    # ------------------------------------------------- align every frame
    aligned = []
    for k, f in enumerate(tiles):
        blk = k // fpb
        g = scale_frame(f, 1.0 / scales[blk])
        m = ink_mask(g)
        ys, xs = np.nonzero(m)
        if len(ys) == 0:
            raise SystemExit("tile %d has no ink after rescale" % (k + 1))
        y0, y1 = ys.min(), ys.max()
        h = y1 - y0 + 1
        up = target_h / h
        g = scale_frame(g, up)
        m = ink_mask(g)
        ys, xs = np.nonzero(m)
        ax = dense_anchor_x(g)
        canvas = np.zeros((ch, cw, 4), np.float32)
        ox = int(round(cw / 2 - ax))
        oy = int(round(BASELINE - ys.max()))
        src = g
        sh, sw = src.shape[:2]
        ox = max(0, min(CW - sw, ox)); oy = max(0, min(CH - sh, oy))
        canvas[oy:oy + sh, ox:ox + sw] = src[:min(sh, CH - oy), :min(sw, CW - ox)]
        aligned.append(canvas)

    frames_dir = os.path.join(args.out_dir, "frames_aligned")
    os.makedirs(frames_dir, exist_ok=True)
    for k, f in enumerate(aligned, 1):
        Image.fromarray((f * 255).round().astype(np.uint8), "RGBA").save(
            os.path.join(frames_dir, "f%02d.png" % k))
    print("aligned %d frames -> %s" % (len(aligned), frames_dir))
    np.save(os.path.join(args.out_dir, "_aligned.npy"), np.stack(aligned))
    json.dump({"scales": scales, "block_first": BLOCK_FIRST},
              open(os.path.join(args.out_dir, "_v3_meta.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
