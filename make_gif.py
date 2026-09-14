"""Build the final animated GIFs from a segmented 4x4 sprite sheet (v1 case).

Alignment: horizontal = dense-alpha mass anchor (character stays put),
           vertical   = sprite bottom on a fixed ground line.
Outputs (into a fresh runs/ directory): frames/*.png, <stem>.gif (white),
<stem>_transparent.gif, <stem>_small.gif, <stem>_small_white.gif

Usage:
  python make_gif.py                          # bundled case: cases/mimo_v1.json
  python make_gif.py --config my_case.json    # another 4x4 sheet
  python make_gif.py --out path/to/dir        # explicit output directory (must be empty or new)

Case config keys: source, boxes_file, grid, canvas, baseline, duration_ms,
alpha_solid, small_size, oversize_policy ("clamp"|"error"), normalize_height,
despeckle, output_stem, run_prefix.
Relative paths in the config resolve against the config file's directory.
"""
import argparse
import json
import os
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy import ndimage as ndi

from spatial_stabilize import stabilize_spatial_sequence

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "cases" / "mimo_v1.json"

DURATION_DEFAULT = 200
ALPHA_SOLID_DEFAULT = 128


def load_config(path):
    """Load a case JSON and resolve its relative paths against the config file."""
    with open(path, encoding="utf-8") as handle:
        cfg = json.load(handle)
    base = os.path.dirname(os.path.abspath(path))

    def resolve(key):
        if key in cfg and cfg[key] is not None and not os.path.isabs(cfg[key]):
            cfg[key] = os.path.normpath(os.path.join(base, cfg[key]))

    for key in ("source", "boxes_file"):
        resolve(key)
    return cfg


def open_run_dir(script_root, cfg, out_override):
    """Fresh timestamped runs/<prefix>-<id>/ by default; --out must be new or empty."""
    if out_override:
        out = os.path.abspath(out_override)
        if os.path.isdir(out) and os.listdir(out):
            raise SystemExit("output directory exists and is not empty: %s" % out)
        os.makedirs(out, exist_ok=True)
        return out
    runs = os.path.join(str(script_root), "runs")
    os.makedirs(runs, exist_ok=True)
    return tempfile.mkdtemp(prefix=cfg.get("run_prefix", "v1-"), dir=runs)


def dense_anchor_x(sub_alpha, blur=31):
    b = ndimage.uniform_filter(sub_alpha, size=blur, mode="constant")
    w = b ** 2
    if w.sum() <= 0:
        return sub_alpha.shape[1] / 2.0
    xs = np.arange(sub_alpha.shape[1])[None, :]
    return float((xs * w).sum() / w.sum())


def on_white(f):
    a = f[..., 3:4]
    return (f[..., :3] * a + (1 - a) * 1.0).clip(0, 1)


def to_p(frames_alpha, transparent, pal_src, alpha_solid=ALPHA_SOLID_DEFAULT):
    """Convert float RGBA frames to P-mode frames sharing pal_src's palette."""
    out = []
    for f in frames_alpha:
        rgb = (on_white(f) * 255).round().astype(np.uint8)
        q = Image.fromarray(rgb, "RGB").quantize(palette=pal_src, dither=Image.NONE)
        arr = np.asarray(q).astype(np.uint16)
        if transparent:
            alpha8 = (f[..., 3] * 255).round().astype(np.uint8)
            arr = np.where(alpha8 >= alpha_solid, arr + 1, 0)   # 0 = transparent
        p = Image.fromarray(arr.astype(np.uint8), "P")
        p.putpalette(([0, 0, 0] if transparent else []) + pal_src.getpalette()[:254 * 3])
        if transparent:
            p.info["transparency"] = 0
        out.append(p)
    return out


def save_gif(path, pframes, transparent, duration=DURATION_DEFAULT):
    kw = dict(save_all=True, append_images=pframes[1:], duration=duration,
              loop=0, optimize=False, format="GIF")
    if transparent:
        kw.update(disposal=2, transparency=0)
    pframes[0].save(path, **kw)
    print("%-42s %8.1f KB  (%d frames)" % (os.path.basename(path),
                                           os.path.getsize(path) / 1024, len(pframes)))


def _ink_rows(crop, alpha_solid):
    return np.nonzero((crop[..., 3] * 255).round() >= alpha_solid)[0]


def _ground_span(solid, max_gap=2):
    """Ground reference robust against detached fragments below the sprite.

    The ground is the bottom of the connected ink run that contains the
    widest row of the character: walking down from the widest row, the first
    fully empty row ends the run.  A detached blob below that gap (leakage
    from the adjacent grid row) never moves the ground line, while real feet
    — continuous with the body — always do.  Returns (top, ground) of that
    connected run."""
    widths = solid.sum(axis=1)
    ink_rows = np.nonzero(widths > 0)[0]
    if len(ink_rows) == 0:
        return None
    anchor_row = int(np.argmax(widths))          # widest row = body
    ground = anchor_row
    y = anchor_row
    while y + 1 < solid.shape[0] and solid[y + 1].any():
        y += 1
        ground = y
    top = anchor_row
    y = anchor_row
    while y - 1 >= 0 and solid[y - 1].any():
        y -= 1
        top = y
    return top, ground


def _despeckle(crop, alpha_solid, ratio=0.004, absolute=24):
    """Drop detached ink components that are tiny relative to the main one.

    AI sheets often leave 1-2px hair slivers at cut-box edges; as connected
    components they pop in and out between frames (single-frame jump).  The
    ratio is relative to the largest component, so it scales with the sprite;
    small but real parts (detached feet ~0.8% of main) stay as long as they
    clear the relative bar and the absolute floor."""
    solid = (crop[..., 3] * 255).round() >= alpha_solid
    lab, n = ndi.label(solid)
    if n < 2:
        return crop
    sizes = np.bincount(lab.ravel())
    main = sizes[1:].max() if len(sizes) > 1 else 0
    keep_mask = np.zeros_like(solid)
    for k in range(1, n + 1):
        if sizes[k] >= max(ratio * main, absolute):
            keep_mask |= (lab == k)
    if keep_mask.all():
        return crop
    out = crop.copy()
    out[..., 3] = np.where(keep_mask, crop[..., 3], 0.0)
    return out


def cut_frames(rgba, boxes, grid, canvas, baseline, oversize_policy,
               alpha_solid=ALPHA_SOLID_DEFAULT, normalize_height=False,
               despeckle=False, stabilize=True):
    """Crop each grid cell and place it on the shared canvas.

    Material policy: a missing cell, a box outside the image, or a fully
    transparent crop is an error (report, never guess).  A crop larger than
    the canvas follows oversize_policy: clamp (crop the overhang, the
    historical behaviour) or error.

    normalize_height rescales every sprite's ink height to the sheet median —
    for AI-generated micro-variation sheets where the model drew some sprites
    a few percent larger (which reads as popping in the GIF).  Off for
    genuine action sheets where height differences are part of the motion.
    """
    ih, iw = rgba.shape[:2]
    cw, ch = canvas

    def solid_mask(crop):
        return (crop[..., 3] * 255).round() >= alpha_solid

    # ---- pass 1: validate and crop ----
    crops = []
    for r in range(grid[0]):
        for c in range(grid[1]):
            if (r, c) not in boxes:
                raise SystemExit("boxes file has no cell r%dc%d (grid %dx%d)" % (r + 1, c + 1, grid[0], grid[1]))
            x0, y0, x1, y1 = boxes[(r, c)]
            if not (0 <= x0 < x1 <= iw and 0 <= y0 < y1 <= ih):
                raise SystemExit("cell r%dc%d box (%d,%d,%d,%d) outside the %dx%d source image"
                                 % (r + 1, c + 1, x0, y0, x1, y1, iw, ih))
            crop = rgba[y0:y1, x0:x1].copy()
            if not (crop[..., 3] > 0).any():
                raise SystemExit("cell r%dc%d crop is fully transparent" % (r + 1, c + 1))
            crops.append(crop)

    # ---- pass 2: normalize, despeckle, measure ----
    median_h = None
    if normalize_height:
        heights = []
        for cp in crops:
            span = _ground_span(_despeckle(cp, alpha_solid)[..., 3] >= (alpha_solid / 255.0))
            if span:
                heights.append(span[1] - span[0] + 1)
        if heights:
            median_h = float(np.median(heights))

    prepared = []
    measurements = []
    for idx, crop in enumerate(crops):
        h, w = crop.shape[:2]
        r, c = idx // grid[1], idx % grid[1]
        if (h > ch or w > cw) and oversize_policy == "error":
            raise SystemExit("cell r%dc%d crop %dx%d exceeds the %dx%d canvas "
                             "(oversize_policy=error)" % (r + 1, c + 1, w, h, cw, ch))
        if normalize_height and median_h:
            span = _ground_span(solid_mask(crop))
            if span:
                s = median_h / (span[1] - span[0] + 1)
                if abs(s - 1.0) > 0.005:
                    im = Image.fromarray((np.clip(crop, 0, 1) * 255).round().astype(np.uint8), "RGBA")
                    im = im.resize((max(1, int(round(w * s))), max(1, int(round(h * s)))), Image.LANCZOS)
                    crop = np.asarray(im).astype(np.float32) / 255.0
        # despeckle last: cleans box-edge slivers AND the resampling ripple
        if despeckle:
            crop = _despeckle(crop, alpha_solid)
        span = _ground_span(solid_mask(crop))
        ground = span[1] if span else crop.shape[0] - 1
        anchor = dense_anchor_x(crop[..., 3])
        prepared.append(crop)
        measurements.append({"anchor_x": anchor, "ground_y": float(ground),
                             "width": crop.shape[1], "height": crop.shape[0]})

    # ---- sequence-level spatial stabilization ----
    if stabilize:
        corrections, report = stabilize_spatial_sequence(measurements, cw, ch)
        snaps = report.get("snapped", [])
        if snaps:
            print("stabilize: 吸附 %d 处单帧微跳动 -> %s" %
                  (len(snaps), [(s["frame"], s["jitter_px"]) for s in snaps[:6]]))
        outs = report.get("outliers_kept_as_motion", {})
        if outs.get("x") or outs.get("y"):
            print("stabilize: 保留的大幅真实运动 -> %s" %
                  (outs.get("x") or []) + str(outs.get("y") or []))
    else:
        corrections = [{"dx": 0.0, "dy": 0.0} for _ in measurements]

    # ---- pass 3: place ----
    frames = []
    for idx, (crop, corr) in enumerate(zip(prepared, corrections)):
        m = measurements[idx]
        h, w = crop.shape[:2]
        ax = m["anchor_x"]
        ground = m["ground_y"]
        canvas_img = np.zeros((ch, cw, 4), np.float32)
        ox = int(round(cw / 2 - ax + corr["dx"]))
        oy = int(round(baseline - ground + corr["dy"]))
        # clamp: copy only the intersection of the crop and the canvas, so an
        # oversized crop is cropped at the canvas edge instead of crashing
        sh, sw = crop.shape[:2]
        sx0 = max(0, -ox); sy0 = max(0, -oy)
        dx0 = max(0, ox); dy0 = max(0, oy)
        cp_w = min(sw - sx0, cw - dx0); cp_h = min(sh - sy0, ch - dy0)
        canvas_img[dy0:dy0 + cp_h, dx0:dx0 + cp_w] = crop[sy0:sy0 + cp_h, sx0:sx0 + cp_w]
        frames.append(canvas_img)
    return frames


def main(argv=None):
    runs = os.path.join(str(ROOT), "runs")
    parser = argparse.ArgumentParser(description="Build v1 GIFs from a segmented sprite sheet.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help="case config JSON (default: cases/mimo_v1.json)")
    parser.add_argument("--out", help="output directory (default: a fresh runs/<prefix>-<id>/ directory)")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    out_dir = open_run_dir(ROOT, cfg, args.out)
    print("New output directory:", out_dir)
    frames_dir = os.path.join(out_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    cw, ch = cfg["canvas"]
    alpha_solid = cfg.get("alpha_solid", ALPHA_SOLID_DEFAULT)
    if not os.path.isfile(cfg["source"]):
        raise SystemExit(
            "source sheet not found: %s\n"
            "(the bundled Mimo imagery is not distributed; point the config's "
            "\"source\" at your own sprite sheet)" % cfg["source"])
    im = Image.open(cfg["source"]).convert("RGBA")
    rgba = np.asarray(im).astype(np.float32) / 255.0
    with open(cfg["boxes_file"], encoding="utf-8") as handle:
        boxes = {tuple(map(int, k.split(","))): v for k, v in json.load(handle).items()}

    frames_rgba = cut_frames(rgba, boxes, cfg["grid"], cfg["canvas"], cfg["baseline"],
                             cfg.get("oversize_policy", "clamp"), alpha_solid,
                             cfg.get("normalize_height", False),
                             cfg.get("despeckle", False),
                             cfg.get("stabilize", False))

    # ---------- PNG frames (RGBA, transparent) ----------
    for i, f in enumerate(frames_rgba):
        a8 = (f[..., 3] * 255).round().astype(np.uint8)
        rgb = (f[..., :3] * 255).round().astype(np.uint8)
        Image.fromarray(np.dstack([rgb, a8]), "RGBA").save(
            os.path.join(frames_dir, "mimo_%02d.png" % (i + 1)))

    # ---------- shared palette from a montage (prevents colour flicker) ----------
    cols = cfg["grid"][1]
    rows = (len(frames_rgba) + cols - 1) // cols
    montage = Image.new("RGB", (cw * cols, ch * rows), (255, 255, 255))
    for i, f in enumerate(frames_rgba):
        r, c = divmod(i, cols)
        montage.paste(Image.fromarray((on_white(f) * 255).round().astype(np.uint8), "RGB"),
                      (c * cw, r * ch))
    pal_src = montage.quantize(colors=254, method=Image.MEDIANCUT, dither=Image.NONE)
    print("palette colours:", len(pal_src.getcolors(maxcolors=100000) or []))

    duration = cfg.get("duration_ms", DURATION_DEFAULT)
    stem = cfg.get("output_stem") or Path(cfg["source"]).stem
    save_gif(os.path.join(out_dir, stem + ".gif"), to_p(frames_rgba, False, pal_src, alpha_solid),
             False, duration)
    save_gif(os.path.join(out_dir, stem + "_transparent.gif"), to_p(frames_rgba, True, pal_src, alpha_solid),
             True, duration)

    # small web version
    sw, sh = cfg.get("small_size", (176, 176))
    small_rgba = []
    for f in frames_rgba:
        img = Image.fromarray((f * 255).round().astype(np.uint8), "RGBA").resize((sw, sh), Image.LANCZOS)
        small_rgba.append(np.asarray(img).astype(np.float32) / 255.0)
    save_gif(os.path.join(out_dir, stem + "_small.gif"), to_p(small_rgba, True, pal_src, alpha_solid),
             True, duration)
    save_gif(os.path.join(out_dir, stem + "_small_white.gif"), to_p(small_rgba, False, pal_src, alpha_solid),
             False, duration)
    print("done")


if __name__ == "__main__":
    main()
