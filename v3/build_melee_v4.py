"""v4: optimised melee loop (config-driven).

Fixes over the v3 cut:
  1. ground-line jitter (settle frames drifted 11 px down) -> every frame, including
     warp-synthesised ones, is re-aligned to the same baseline and mass centre
  2. lumpy punch (v3 used two near-identical idle frames then a jump) -> hand-picked
     frames b8.3..b8.7 so the extension ramps evenly
  3. punch -> spin seam (IoU 0.726) -> two motion-compensated bridge frames
  4. spin gets all seven drawn frames instead of four
  5. single resampling pass + unsharp mask instead of two LANCZOS passes
  6. no per-frame height normalisation: pose height differences (lean / crouch) survive

Usage:
  python v3/build_melee_v4.py                          # bundled case: cases/mimo_v4.json
  python v3/build_melee_v4.py --config my_case.json    # another tile set
  python v3/build_melee_v4.py --out path/to/dir        # explicit output directory (must be empty or new)

Case config keys: tiles_dir, tile_prefix, tiles_per_block, blocks (punch/spin),
canvas, baseline, target_height, upscale_cap, fps, punch_indices, spin_indices,
bridge_to_spin_index, holds_ms, bridge_phases, adaptive_iou, oversize_policy,
run_prefix.  Relative paths resolve against the config file's directory.
Material policy: a missing tile or a tile with no ink is an error; a frame
larger than the canvas follows oversize_policy ("clamp" crops the overhang).
"""
import argparse
import json
import os
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage
from skimage.registration import optical_flow_tvl1, phase_cross_correlation

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT.parent / "cases" / "mimo_v4.json"

ALPHA_SOLID_DEFAULT = 128


def load_config(path):
    """Load a case JSON and resolve its relative paths against the config file."""
    with open(path, encoding="utf-8") as handle:
        cfg = json.load(handle)
    base = os.path.dirname(os.path.abspath(path))
    if "tiles_dir" in cfg and cfg["tiles_dir"] and not os.path.isabs(cfg["tiles_dir"]):
        cfg["tiles_dir"] = os.path.normpath(os.path.join(base, cfg["tiles_dir"]))
    return cfg


def open_run_dir(script_root, cfg, out_override, seq_name="seq_melee_v4"):
    """Fresh timestamped runs/<prefix>-<id>/ with a sequence subdirectory."""
    if out_override:
        run_out = os.path.abspath(out_override)
        if os.path.isdir(run_out) and os.listdir(run_out):
            raise SystemExit("output directory exists and is not empty: %s" % run_out)
        os.makedirs(run_out, exist_ok=True)
    else:
        runs = os.path.join(str(script_root), "runs")
        os.makedirs(runs, exist_ok=True)
        run_out = tempfile.mkdtemp(prefix=cfg.get("run_prefix", "melee-v4-"), dir=runs)
    seqdir = os.path.join(run_out, seq_name)
    os.makedirs(seqdir, exist_ok=True)
    return run_out, seqdir


def load_tile(tiles_dir, prefix, k):
    """Load tile k as RGBA float; the near-white border flood fill becomes alpha."""
    path = os.path.join(tiles_dir, "%s_%02d.png" % (prefix, k))
    if not os.path.isfile(path):
        raise SystemExit("tile not found: %s" % path)
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(np.int16)
    grey = a.mean(axis=2)
    sat = a.max(axis=2) - a.min(axis=2)
    near_white = (grey >= 244) & (sat <= 12)
    lab, n = ndimage.label(near_white, structure=np.ones((3, 3), bool))
    border = set(lab[0, :]) | set(lab[-1, :]) | set(lab[:, 0]) | set(lab[:, -1])
    border.discard(0)
    bg = np.isin(lab, list(border))
    alpha = (~bg).astype(np.float32)
    if not alpha.any():
        raise SystemExit("tile has no ink outside its white border: %s" % path)
    alpha = ndimage.gaussian_filter(alpha, 0.55)
    return np.dstack([np.asarray(im).astype(np.float32) / 255.0, alpha])


def bbox_h(f):
    ys = np.nonzero(f[..., 3] > 0.5)[0]
    return int(ys.max() - ys.min() + 1) if len(ys) else 0


def resample(f, s, sharpen=True):
    im = Image.fromarray((np.clip(f, 0, 1) * 255).round().astype(np.uint8), "RGBA")
    nw, nh = max(1, int(round(im.width * s))), max(1, int(round(im.height * s)))
    im = im.resize((nw, nh), Image.LANCZOS)
    if sharpen and s > 1.2:
        rgb = im.convert("RGB").filter(ImageFilter.UnsharpMask(radius=1.1, percent=105, threshold=3))
        im = Image.merge("RGBA", (*rgb.split(), im.split()[3]))
    return np.asarray(im).astype(np.float32) / 255.0


def dense_anchor_x(f, blur=15):
    b = ndimage.uniform_filter(f[..., 3], size=blur, mode="constant") ** 2
    if b.sum() <= 0:
        return f.shape[1] / 2.0
    xs = np.arange(f.shape[1])[None, :]
    return float((xs * b).sum() / b.sum())


def place(f, canvas, baseline, oversize_policy="clamp"):
    """Centre horizontally on the mass anchor, put the bbox bottom on the baseline."""
    cw, ch = canvas
    m = f[..., 3] > 0.5
    ys, xs = np.nonzero(m)
    if len(ys) == 0:
        raise SystemExit("cannot place a frame with no opaque pixels")
    if (ys.max() >= ch or (xs.max() - xs.min() + 1) > cw) and oversize_policy == "error":
        raise SystemExit("frame %dx%d does not fit the %dx%d canvas (oversize_policy=error)"
                         % (f.shape[1], f.shape[0], cw, ch))
    ax = dense_anchor_x(f)
    out = np.zeros((ch, cw, 4), np.float32)
    ox = int(round(cw / 2 - ax))
    oy = int(round(baseline - ys.max()))
    sh, sw = f.shape[:2]
    sx0 = max(0, -ox); sy0 = max(0, -oy)
    dx0 = max(0, ox); dy0 = max(0, oy)
    w = min(sw - sx0, cw - dx0); h = min(sh - sy0, ch - dy0)
    out[dy0:dy0 + h, dx0:dx0 + w] = f[sy0:sy0 + h, sx0:sx0 + w]
    return out


def flows(fa, fb):
    """Bidirectional dense flow: d_ab maps A->B, d_ba maps B->A (row, col)."""
    aa, bb = fa[..., 3], fb[..., 3]
    s, _, _ = phase_cross_correlation(aa, bb, upsample_factor=10, normalization=None)
    bb_a = ndimage.shift(bb, s, order=1, mode="constant", cval=0.0)
    v, u = optical_flow_tvl1(aa, bb_a, attachment=15, num_warp=8, num_iter=25, tol=1e-4)
    d_ab = np.stack([v, u], -1).astype(np.float32) - s.astype(np.float32)

    s2, _, _ = phase_cross_correlation(bb, aa, upsample_factor=10, normalization=None)
    aa_b = ndimage.shift(aa, s2, order=1, mode="constant", cval=0.0)
    v2, u2 = optical_flow_tvl1(bb, aa_b, attachment=15, num_warp=8, num_iter=25, tol=1e-4)
    d_ba = np.stack([v2, u2], -1).astype(np.float32) - s2.astype(np.float32)
    return d_ab, d_ba


def warp_by(f, disp):
    h, w = f.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    out = np.empty_like(f)
    for c in range(f.shape[2]):
        out[..., c] = ndimage.map_coordinates(f[..., c], [ys - disp[..., 0], xs - disp[..., 1]],
                                              order=1, mode="constant", cval=0.0)
    return out


def bridge(fa, fb, phases, switch=0.5):
    """Single-source motion-compensated frames.

    t <= switch is warped forward from fa (so the first step stays small);
    t > switch is warped backward from fb (so the last step stays small).
    """
    d_ab, d_ba = flows(fa, fb)
    out = []
    for t in phases:
        if t <= switch:
            out.append(warp_by(fa, t * d_ab))
        else:
            out.append(warp_by(fb, (1.0 - t) * d_ba))
    return out


def best_scale(mask_from, mask_to):
    best, bs = -1, 1.0
    for s in np.linspace(0.75, 1.30, 45):
        h = w = 200
        def place_m(m, sc):
            ys, xs = np.nonzero(m)
            cy, cx = ys.mean() * sc, xs.mean() * sc
            out = np.zeros((h, w), bool)
            out[np.clip((ys * sc).astype(int) + int(h / 2 - cy), 0, h - 1),
                np.clip((xs * sc).astype(int) + int(w / 2 - cx), 0, w - 1)] = True
            return out
        A_, B_ = place_m(mask_from, 1.0), place_m(mask_to, s)
        v = (A_ & B_).sum() / max(1, (A_ | B_).sum())
        if v > best:
            best, bs = v, s
    return bs, best


def iou(a, b):
    ma, mb = a[..., 3] > 0.5, b[..., 3] > 0.5
    return float((ma & mb).sum() / max(1, (ma | mb).sum()))


def on_white(f):
    a = f[..., 3:4]
    return ((f[..., :3] * a + (1 - a)).clip(0, 1) * 255).round().astype(np.uint8)


def snap(seq):
    """Snap nominal frame times to the 10 ms grid by cumulative rounding."""
    durs, cum, prev = [], 0.0, 0
    for _, ms, _ in seq:
        cum += ms
        c = int(round(cum / 10.0) * 10)
        durs.append(c - prev); prev = c
    return durs


def save_gif(name, seq, durs, pal, out_dir, transparent, alpha_solid=ALPHA_SOLID_DEFAULT):
    pf = []
    for f, _, _ in seq:
        q = Image.fromarray(on_white(f), "RGB").quantize(palette=pal, dither=Image.NONE)
        arr = np.asarray(q).astype(np.uint16)
        if transparent:
            arr = np.where((f[..., 3] * 255).round().astype(np.uint8) >= alpha_solid, arr + 1, 0)
        p = Image.fromarray(arr.astype(np.uint8), "P")
        p.putpalette(([0, 0, 0] if transparent else []) + pal.getpalette()[:254 * 3])
        if transparent:
            p.info["transparency"] = 0
        pf.append(p)
    kw = dict(save_all=True, append_images=pf[1:], duration=durs, loop=0,
              optimize=False, format="GIF")
    if transparent:
        kw.update(disposal=2, transparency=0)
    path = os.path.join(out_dir, name)
    pf[0].save(path, **kw)
    print("%-36s %7.1f KB  %2d frames  %.2fs" %
          (name, os.path.getsize(path) / 1024, len(pf), sum(durs) / 1000))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the optimised v4 melee loop from tiles.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help="case config JSON (default: cases/mimo_v4.json)")
    parser.add_argument("--tiles-dir", help="override the config's tiles_dir")
    parser.add_argument("--out", help="output directory (default: a fresh runs/<prefix>-<id>/ directory)")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    tiles_dir = args.tiles_dir or cfg["tiles_dir"]
    if not os.path.isdir(tiles_dir):
        raise SystemExit("tiles directory not found: %s" % tiles_dir)

    canvas = tuple(cfg["canvas"])
    baseline = cfg["baseline"]
    oversize_policy = cfg.get("oversize_policy", "clamp")
    unit_ms = 1000.0 / cfg.get("fps", 24)
    fpb = cfg["tiles_per_block"]
    prefix = cfg.get("tile_prefix", "pair")

    def load_block(b):
        return [load_tile(tiles_dir, prefix, fpb * (b - 1) + i) for i in range(1, fpb + 1)]

    # ---------------------------------------------------------------- raw material
    b8 = load_block(cfg["blocks"]["punch"])
    b9 = load_block(cfg["blocks"]["spin"])

    s_seam, q_seam = best_scale(b8[fpb - 1][..., 3] > 0.5, b9[0][..., 3] > 0.5)
    print("block9 scale vs block8: %.3f (IoU %.3f)" % (s_seam, q_seam))
    b9s = [resample(f, s_seam, sharpen=False) for f in b9]

    # global scale so the median character height hits TARGET_H
    h_all = [bbox_h(f) for f in b8] + [bbox_h(f) for f in b9s]
    med = float(np.median(h_all))
    if med <= 0:
        raise SystemExit("median character height is zero; tiles have no ink")
    g = min(cfg["target_height"] / med, cfg["upscale_cap"])
    print("median native height %.1f px -> global scale %.2fx" % (med, g))

    def prep(f):
        return place(resample(f, g, sharpen=True), canvas, baseline, oversize_policy)

    b8p = [prep(f) for f in b8]
    b9p = [prep(f) for f in b9s]

    # ---------------------------------------------------------------- sequence
    holds = cfg["holds_ms"]
    phases = cfg["bridge_phases"]
    seq = []
    seq.append((b8p[0], holds["idle"], "idle"))
    for i in cfg["punch_indices"]:
        seq.append((b8p[i], unit_ms, "punch %d" % i))
    seq.append((b8p[fpb - 1], holds["punch_full"], "punch full"))
    for k, f in enumerate(bridge(b8p[fpb - 1], b9p[cfg["bridge_to_spin_index"]],
                                 phases["punch_to_spin"]), 1):
        seq.append((place(f, canvas, baseline, oversize_policy), unit_ms, "bridge %d" % k))
    for i in cfg["spin_indices"]:
        seq.append((b9p[i], unit_ms, "spin %d" % i))
    seq.append((b9p[fpb - 1], holds["spin_end"], "spin end"))
    for k, f in enumerate(bridge(b9p[fpb - 1], b8p[0], phases["settle"]), 1):
        seq.append((place(f, canvas, baseline, oversize_policy), unit_ms, "settle %d" % k))
    seq.append((b8p[0], holds["idle_loop"], "idle (loop)"))

    # adaptive insert: wherever two *drawn* frames still jump (IoU below the
    # threshold), add one motion-compensated frame so no step is left abrupt
    fixed = []
    thr = cfg.get("adaptive_iou", 0.75)
    for k, item in enumerate(seq):
        fixed.append(item)
        if k + 1 >= len(seq):
            continue
        fa, fb = item[0], seq[k + 1][0]
        if item[2].startswith(("punch", "spin")) and seq[k + 1][2].startswith(("punch", "spin")):
            if iou(fa, fb) < thr:
                mid = bridge(fa, fb, [0.5])[0]
                fixed.append((place(mid, canvas, baseline, oversize_policy), unit_ms,
                              "fix %s->%s" % (item[2], seq[k + 1][2])))
                print("inserted in-between between %s and %s" % (item[2], seq[k + 1][2]))
    seq = fixed

    durs = snap(seq)
    print("frames=%d  total=%.2fs  motion avg=%.2f fps" %
          (len(seq), sum(durs) / 1000,
           sum(1 for d in durs if d <= 50) / max(1e-9, sum(d for d in durs if d <= 50) / 1000)))

    run_out, seqdir = open_run_dir(ROOT, cfg, args.out)
    print("New output directory:", run_out)
    for k, (f, _, _) in enumerate(seq, 1):
        Image.fromarray((np.clip(f, 0, 1) * 255).round().astype(np.uint8), "RGBA").save(
            os.path.join(seqdir, "%02d.png" % k))

    # ---------------------------------------------------------------- encode
    cw, ch = canvas
    mont = Image.new("RGB", (cw * 4, ch * ((len(seq) + 3) // 4)), (255, 255, 255))
    for k, (f, _, _) in enumerate(seq):
        r, c = divmod(k, 4)
        mont.paste(Image.fromarray(on_white(f), "RGB"), (c * cw, r * ch))
    pal = mont.quantize(colors=254, method=Image.MEDIANCUT, dither=Image.NONE)

    stem = cfg.get("output_stem") or "mimo4_melee"
    alpha_solid = cfg.get("alpha_solid", ALPHA_SOLID_DEFAULT)
    save_gif(stem + ".gif", seq, durs, pal, run_out, False, alpha_solid)
    save_gif(stem + "_transparent.gif", seq, durs, pal, run_out, True, alpha_solid)
    print("done")


if __name__ == "__main__":
    main()
