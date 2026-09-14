"""Evaluate in-between schemes per transition and pick the smoothest one.

Schemes (all single-source warps, no cross-fade ghosts):
  s0 : no in-between
  s1a: warpA(0.5)
  s1b: warpB(0.5)
  s2a: warpA(1/3), warpA(2/3)
  s2b: warpA(1/3), warpB(2/3)
  s3 : warpA(0.25), warpB(0.5), warpB(0.75)

Metric: silhouette IoU between consecutive frames of the augmented sequence.
We maximise the minimum consecutive IoU (the worst "jump" the eye will see).

Usage:
  python evaluate_schemes.py                             # default case: v2/frames_key
  python evaluate_schemes.py --frames-dir runs/x/keys --count 8
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np
import morph

ROOT = Path(__file__).resolve().parent


def iou(a, b):
    ma = a[..., 3] > 0.5; mb = b[..., 3] > 0.5
    return float((ma & mb).sum() / max(1, (ma | mb).sum()))


def seq_min_iou(frames):
    return min(iou(frames[k], frames[k + 1]) for k in range(len(frames) - 1))


def evaluate(keys, count, frames_dir=None):
    results = []
    order = {"s0": 0, "s1a": 1, "s1b": 1, "s2a": 2, "s2b": 2, "s3": 3}
    for i in range(1, count + 1):
        j = i % count + 1
        A, B = keys[i - 1], keys[j - 1]
        d_ab, d_ba = morph.get_flow(i, j, frames_dir=frames_dir)
        cands = {
            "s0": [A, B],
            "s1a": [A, morph.warp_premult(A, 0.5 * d_ab), B],
            "s1b": [A, morph.warp_premult(B, 0.5 * d_ba), B],
            "s2a": [A, morph.warp_premult(A, (1 / 3) * d_ab), morph.warp_premult(A, (2 / 3) * d_ab), B],
            "s2b": [A, morph.warp_premult(A, (1 / 3) * d_ab), morph.warp_premult(B, (1 / 3) * d_ba), B],
            "s3": [A, morph.warp_premult(A, 0.25 * d_ab), morph.warp_premult(B, 0.5 * d_ba),
                   morph.warp_premult(B, 0.25 * d_ba), B],
        }
        scores = {k: seq_min_iou(v) for k, v in cands.items()}
        base = scores["s0"]
        best = max(scores, key=lambda k: scores[k])
        # prefer the fewest added frames among near-ties (within 0.02)
        near = [k for k in scores if scores[k] >= scores[best] - 0.02]
        best = min(near, key=lambda k: order[k])
        results.append(dict(i=i, j=j, scores=scores, best=best, base=base))
        print("%2d->%-3d base=%.3f | %s   -> best=%s (%.3f, +%.3f)" %
              (i, j, base, "  ".join("%s=%.3f" % (k, scores[k]) for k in ("s0", "s1a", "s1b", "s2a", "s2b", "s3")),
               best, scores[best], scores[best] - base))
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pick the smoothest in-between scheme per transition.")
    parser.add_argument("--frames-dir", default=None,
                        help="key frame directory (default: morph's bundled v2/frames_key)")
    parser.add_argument("--count", type=int, default=morph.N,
                        help="number of keys (default: 16)")
    parser.add_argument("--json-out",
                        help="output JSON path (default: <frames-dir>/../_schemes.json)")
    args = parser.parse_args(argv)

    keys = [morph.load_key(i, args.frames_dir) for i in range(1, args.count + 1)]
    results = evaluate(keys, args.count, args.frames_dir)
    json_out = args.json_out or os.path.join(
        os.path.dirname(os.path.abspath(args.frames_dir or morph.FRAMES)), "_schemes.json")
    with open(json_out, "w") as handle:
        json.dump(results, handle, indent=1)
    print("\nwrote %s" % json_out)
    print("\nchosen:", " ".join("%d->%d:%s" % (r["i"], r["j"], r["best"]) for r in results))


if __name__ == "__main__":
    main()
