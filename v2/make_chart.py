"""Charts for the continuity report: body-mass trajectory + step smoothness.

Requires _align_meta.json (from align.py) and _schemes.json (from
evaluate_schemes.py) in the meta directory.  The take-off / landing
annotations reference the Mimo jump keys (11..14).
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent


def main(argv=None):
    parser = argparse.ArgumentParser(description="Continuity-report charts.")
    parser.add_argument("--meta-dir", default=str(ROOT),
                        help="directory holding _align_meta.json and _schemes.json")
    parser.add_argument("--count", type=int, default=16, help="keyframe count (default: 16)")
    args = parser.parse_args(argv)

    with open(os.path.join(args.meta_dir, "_align_meta.json"), encoding="utf-8") as handle:
        meta = json.load(handle)
    with open(os.path.join(args.meta_dir, "_schemes.json"), encoding="utf-8") as handle:
        schemes = json.load(handle)

    cx = np.array([m["ox"] + m["ax"] for m in meta])
    cy = np.array([m["oy"] + m["ay"] for m in meta])
    idx = np.arange(1, len(meta) + 1)

    # ---- figure 1: trajectory ----
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.2))
    ax[0].plot(idx, cy, "-o", color="#ff7a1a", lw=2, ms=5)
    ax[0].invert_yaxis()
    ax[0].axhline(332, color="#888", ls="--", lw=1)
    ax[0].text(1.2, 336, "ground line", fontsize=8, color="#666")
    ax[0].set_title("Body-mass centre Y (px, up = higher)")
    ax[0].set_xlabel("keyframe"); ax[0].grid(alpha=.3)
    for k in (11, 12, 13, 14):
        if k <= len(meta):
            ax[0].annotate("", xy=(k, cy[k - 1]), xytext=(k, cy[k - 1]),
                           arrowprops=dict(arrowstyle="->", color="#0a84ff"))
    if len(meta) >= 14:
        ax[0].text(11.4, cy[11] - 6, "take-off", fontsize=8, color="#0a84ff")
        ax[0].text(13.0, cy[13] + 14, "landing", fontsize=8, color="#0a84ff")

    dcy = np.diff(np.append(cy, cy[0]))          # step-to-step vertical change (wraps)
    ax[1].bar(idx, dcy, color=["#0a84ff" if v < 0 else "#ff3b30" for v in dcy],
              edgecolor="#444", linewidth=.5)
    ax[1].axhline(0, color="#888", lw=1)
    ax[1].set_title("Vertical velocity of body mass (px per keyframe step, up = -)")
    ax[1].set_xlabel("transition out of keyframe"); ax[1].grid(alpha=.3, axis="y")
    if len(meta) >= 14:
        ax[1].text(11.6, dcy[11] * 1.15, "take-off", fontsize=8, color="#0a84ff")
        ax[1].text(13.2, dcy[13] * 1.15, "landing", fontsize=8, color="#ff3b30")

    area = np.array([m["w"] * m["h"] for m in meta])
    ax[2].bar(idx, area, color="#ffb066", edgecolor="#e06a00")
    ax[2].set_title("Silhouette bounding-box area (px^2)")
    ax[2].set_xlabel("keyframe"); ax[2].grid(alpha=.3, axis="y")
    plt.tight_layout()
    plt.savefig(os.path.join(args.meta_dir, "_chart_trajectory.png"), dpi=110)
    print("saved _chart_trajectory.png")

    # ---- figure 2: step smoothness ----
    base = [r["base"] for r in schemes]
    best = [r["scores"][r["best"]] for r in schemes]
    labels = ["%d>%d" % (r["i"], r["j"]) for r in schemes]
    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(13, 4.6))
    ax.bar(x - 0.2, base, 0.4, label="keyframes only (hard cut)", color="#9db4c8")
    ax.bar(x + 0.2, best, 0.4, label="with motion-compensated in-betweens", color="#ff7a1a")
    ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=8, rotation=45)
    ax.set_ylabel("worst consecutive-frame silhouette IoU")
    ax.set_title("Continuity per transition: worst step IoU (higher = smoother)")
    ax.legend(); ax.grid(alpha=.3, axis="y")
    plt.tight_layout()
    plt.savefig(os.path.join(args.meta_dir, "_chart_smoothness.png"), dpi=110)
    print("saved _chart_smoothness.png")
    print("mean worst-step IoU: key=%.3f  tweened=%.3f" % (np.mean(base), np.mean(best)))


if __name__ == "__main__":
    main()
