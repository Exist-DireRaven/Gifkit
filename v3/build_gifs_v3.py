"""Assemble two coherent loops from normalised frames (v3 case).

A. 枪械连段  gun combo : key02 step -> lunge -> crouch -> raise gun -> aim -> fire -> stow -> idle
B. 格斗连段  melee combo: idle -> straight punch -> spin attack -> settle back to idle

The gun and the fists never share one GIF.  Motion frames sit on a 1/fps grid.

Usage:
  python v3/build_gifs_v3.py                          # bundled case: cases/mimo_v3.json
  python v3/build_gifs_v3.py --config my_case.json    # another aligned frame set
  python v3/build_gifs_v3.py --out path/to/dir        # explicit output directory (must be empty or new)

Case config keys: aligned_dir, frames_per_block, canvas, alpha_solid, fps, nb,
sequences (intro/blocks/block_holds/settle per loop), run_prefix.  Relative
paths resolve against the config file's directory.  Material policy: a missing
aligned frame or a fully transparent frame is an error; the frame count must
be a multiple of frames_per_block.
"""
import argparse
import json
import os
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage
from skimage.registration import optical_flow_tvl1, phase_cross_correlation

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT.parent / "cases" / "mimo_v3.json"

ALPHA_SOLID_DEFAULT = 128


def load_config(path):
    """Load a case JSON and resolve its relative paths against the config file."""
    with open(path, encoding="utf-8") as handle:
        cfg = json.load(handle)
    base = os.path.dirname(os.path.abspath(path))
    if "aligned_dir" in cfg and cfg["aligned_dir"] and not os.path.isabs(cfg["aligned_dir"]):
        cfg["aligned_dir"] = os.path.normpath(os.path.join(base, cfg["aligned_dir"]))
    return cfg


def open_run_dir(script_root, cfg, out_override):
    if out_override:
        out = os.path.abspath(out_override)
        if os.path.isdir(out) and os.listdir(out):
            raise SystemExit("output directory exists and is not empty: %s" % out)
        os.makedirs(out, exist_ok=True)
        return out
    runs = os.path.join(str(script_root), "runs")
    os.makedirs(runs, exist_ok=True)
    return tempfile.mkdtemp(prefix=cfg.get("run_prefix", "v3-"), dir=runs)


def load_aligned(aligned_dir, frames_per_block):
    """Load the aligned frames in name order; missing/empty frames are errors."""
    if not os.path.isdir(aligned_dir):
        raise SystemExit("aligned frames directory not found: %s" % aligned_dir)
    files = sorted(f for f in os.listdir(aligned_dir) if f.lower().endswith(".png"))
    if not files:
        raise SystemExit("no .png frames in %s" % aligned_dir)
    if len(files) % frames_per_block:
        raise SystemExit("%d frames in %s is not a multiple of frames_per_block=%d"
                         % (len(files), aligned_dir, frames_per_block))
    aligned = []
    for name in files:
        path = os.path.join(aligned_dir, name)
        frame = np.asarray(Image.open(path).convert("RGBA")).astype(np.float32) / 255.0
        if not (frame[..., 3] > 0).any():
            raise SystemExit("aligned frame has no opaque pixels: %s" % path)
        aligned.append(frame)
    return aligned


def frame_at(aligned, b, local, fpb):
    """aligned frame for block b (1-based) and local index 0..fpb-1."""
    return aligned[fpb * (b - 1) + local]


def step_motion(fa, fb):
    """Motion between two aligned frames: mean abs difference over the union mask."""
    m = (fa[..., 3] > 0.5) | (fb[..., 3] > 0.5)
    if m.sum() == 0:
        return 0.0
    d = np.abs(fa[..., :3] - fb[..., :3]).mean(axis=2)
    return float(d[m].mean())


def pick_by_motion(aligned, b, n, fpb):
    """Return n local in-between indices (1..fpb-2) spaced by cumulative motion."""
    fs = [frame_at(aligned, b, i, fpb) for i in range(fpb)]
    diffs = [step_motion(fs[i], fs[i + 1]) for i in range(fpb - 1)]
    cum = np.concatenate([[0.0], np.cumsum(diffs)])       # fpb values, last = closing key
    total = cum[-1]
    if total <= 1e-6:
        return list(range(1, n + 1))
    picks = []
    for k in range(1, n + 1):
        target = total * k / (n + 1.0)
        cand = [i for i in range(1, fpb - 1) if i not in picks]
        picks.append(min(cand, key=lambda i: abs(cum[i] - target)))
    return sorted(picks)


def build_sequence(aligned, spec, nb, fpb, unit_ms):
    """intro frame -> per-block (in-betweens + closing key with extra hold)."""
    intro = spec["intro"]
    seq = [(frame_at(aligned, intro["block"], 0, fpb), intro["hold"], intro.get("label", "intro key"))]
    for b in spec["blocks"]:
        for ib in pick_by_motion(aligned, b, nb[str(b)], fpb):
            seq.append((frame_at(aligned, b, ib, fpb), unit_ms, "b%d ib%d" % (b, ib)))
        extra = spec.get("block_holds", {}).get(str(b), 0)
        seq.append((frame_at(aligned, b, fpb - 1, fpb), unit_ms + extra, "b%d key" % b))
    return seq


def warp_bridge(fa, fb, n=3):
    """Motion-compensated settle frames from fa to fb."""
    aa, bb = fa[..., 3], fb[..., 3]
    s, _, _ = phase_cross_correlation(aa, bb, upsample_factor=10, normalization=None)
    bb_a = ndimage.shift(bb, s, order=1, mode="constant", cval=0.0)
    v, u = optical_flow_tvl1(aa, bb_a, attachment=15, num_warp=8, num_iter=25, tol=1e-4)
    d = np.stack([v, u], -1).astype(np.float32) - s.astype(np.float32)

    h, w = aa.shape
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)

    def sample(f, dy, dx):
        out = np.empty_like(f)
        for c in range(f.shape[2]):
            out[..., c] = ndimage.map_coordinates(f[..., c], [ys - dy, xs - dx],
                                                  order=1, mode="constant", cval=0.0)
        return out
    res = []
    for k in range(1, n + 1):
        t = k / (n + 1.0)
        res.append(sample(fa, t * d[..., 0], t * d[..., 1]))
    return res


def snap(seq):
    """Snap nominal frame times to the GIF 10 ms grid by cumulative rounding."""
    durs, cum, prev = [], 0.0, 0
    for _, ms, _ in seq:
        cum += ms
        c = int(round(cum / 10.0) * 10)
        durs.append(c - prev)
        prev = c
    return durs


def on_white(f):
    a = f[..., 3:4]
    return ((f[..., :3] * a + (1 - a)).clip(0, 1) * 255).round().astype(np.uint8)


def palette(seq, canvas):
    cw, ch = canvas
    cols = 4
    sample = seq[::max(1, len(seq) // 16)]
    rows = (len(sample) + cols - 1) // cols
    mont = Image.new("RGB", (cw * cols, ch * rows), (255, 255, 255))
    for k, (f, _, _) in enumerate(sample):
        r, c = divmod(k, cols)
        mont.paste(Image.fromarray(on_white(f), "RGB"), (c * cw, r * ch))
    return mont.quantize(colors=254, method=Image.MEDIANCUT, dither=Image.NONE)


def save(name, seq, pal, transparent, out_dir, alpha_solid=ALPHA_SOLID_DEFAULT):
    durs = snap(seq)
    pf = []
    for f, _, _ in seq:
        q = Image.fromarray(on_white(f), "RGB").quantize(palette=pal, dither=Image.NONE)
        arr = np.asarray(q).astype(np.uint16)
        if transparent:
            a8 = (f[..., 3] * 255).round().astype(np.uint8)
            arr = np.where(a8 >= alpha_solid, arr + 1, 0)
        p = Image.fromarray(arr.astype(np.uint8), "P")
        p.putpalette(([0, 0, 0] if transparent else []) + pal.getpalette()[:254 * 3])
        if transparent:
            p.info["transparency"] = 0
        pf.append(p)
    path = os.path.join(out_dir, name)
    kw = dict(save_all=True, append_images=pf[1:], duration=durs, loop=0,
              optimize=False, format="GIF")
    if transparent:
        kw.update(disposal=2, transparency=0)
    pf[0].save(path, **kw)
    print("%-34s %7.1f KB  %2d frames  %.2fs" %
          (name, os.path.getsize(path) / 1024, len(pf), sum(durs) / 1000))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the v3 gun/melee loop GIFs from aligned frames.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help="case config JSON (default: cases/mimo_v3.json)")
    parser.add_argument("--aligned-dir", help="override the config's aligned_dir")
    parser.add_argument("--out", help="output directory (default: a fresh runs/<prefix>-<id>/ directory)")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    aligned_dir = args.aligned_dir or cfg["aligned_dir"]
    out_dir = open_run_dir(ROOT, cfg, args.out)
    print("New output directory:", out_dir)

    fpb = cfg["frames_per_block"]
    aligned = load_aligned(aligned_dir, fpb)
    nb = cfg["nb"]
    unit_ms = 1000.0 / cfg.get("fps", 24)

    sequences = {}
    for tag, spec in cfg["sequences"].items():
        seq = build_sequence(aligned, spec, nb, fpb, unit_ms)
        settle = spec.get("settle")
        if settle:
            target = frame_at(aligned, settle["to_block"], 0, fpb)
            for k, f in enumerate(warp_bridge(seq[-1][0], target, settle.get("count", 3)), 1):
                seq.append((f, unit_ms, "settle %d" % k))
            seq.append((target, settle["final_hold"], settle.get("label", "loop key")))
        sequences[tag] = seq

    for tag, seq in sequences.items():
        d = snap(seq)
        print("%-6s frames=%2d  total=%.2fs  motion avg=%.2f fps" %
              (tag, len(seq), sum(d) / 1000,
               sum(1 for x in d if x <= 50) / max(1e-9, sum(x for x in d if x <= 50) / 1000)))

    alpha_solid = cfg.get("alpha_solid", ALPHA_SOLID_DEFAULT)
    for tag, seq in sequences.items():
        pal = palette(seq, cfg["canvas"])
        save("%s_%s.gif" % (cfg.get("output_stem") or "mimo3", tag), seq, pal, False, out_dir, alpha_solid)
        save("%s_%s_transparent.gif" % (cfg.get("output_stem") or "mimo3", tag), seq, pal, True,
             out_dir, alpha_solid)
        d = os.path.join(out_dir, "seq_%s" % tag)
        os.makedirs(d, exist_ok=True)
        for k, (f, _, _) in enumerate(seq, 1):
            Image.fromarray((f * 255).round().astype(np.uint8), "RGBA").save(
                os.path.join(d, "%02d.png" % k))
        print("wrote seq_%s/ (%d frames)" % (tag, len(seq)))

    with open(os.path.join(out_dir, "_v3_plan.json"), "w", encoding="utf-8") as handle:
        json.dump({tag: {"labels": [lab for _, _, lab in seq], "durs": snap(seq)}
                   for tag, seq in sequences.items()}, handle, indent=1)
    print("done")


if __name__ == "__main__":
    main()
