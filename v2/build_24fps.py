"""Rebuild at 24 fps (v2 case).

Motion frames are placed on a 1/fps grid.  GIF stores durations in 10 ms
units, so per-frame durations are 40/50 ms distributed by cumulative
rounding, which keeps the average motion rate at exactly the target fps.
Keyframe holds stay as single long-duration frames (the dramatic pauses).

In-between count per transition follows the measured motion magnitude; phases
are k/(n+1) with a single-source warp: A forward for phase <= 0.5, B backward
for phase > 0.5 (keeps maximum deformation at ~50 %).

Usage:
  python v2/build_24fps.py                          # bundled case: cases/mimo_v2_24fps.json
  python v2/build_24fps.py --config my_case.json    # another keyframe set
  python v2/build_24fps.py --out path/to/dir        # explicit output directory (must be empty or new)

Case config keys: frames_dir, pattern, count, canvas, alpha_solid, fps, nb,
hold, outputs (name/transparent/scale), run_prefix.  Relative paths resolve
against the config file's directory.  Material policy: a missing keyframe
file or a fully transparent keyframe is an error.
"""
import argparse
import json
import os
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
import morph
from morph import crisp_alpha

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT.parent / "cases" / "mimo_v2_24fps.json"

ALPHA_SOLID_DEFAULT = 128


def load_config(path):
    """Load a case JSON and resolve its relative paths against the config file."""
    with open(path, encoding="utf-8") as handle:
        cfg = json.load(handle)
    base = os.path.dirname(os.path.abspath(path))

    def resolve(key):
        if key in cfg and cfg[key] is not None and not os.path.isabs(cfg[key]):
            cfg[key] = os.path.normpath(os.path.join(base, cfg[key]))

    for key in ("frames_dir",):
        resolve(key)
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
    return tempfile.mkdtemp(prefix=cfg.get("run_prefix", "v2-24fps-"), dir=runs)


def load_keys(frames_dir, pattern, count):
    """Load `count` RGBA float keys; missing files and empty frames are errors."""
    from PIL import Image
    keys = []
    for i in range(1, count + 1):
        path = os.path.join(frames_dir, pattern % i)
        if not os.path.isfile(path):
            raise SystemExit("key frame not found: %s" % path)
        frame = np.asarray(Image.open(path).convert("RGBA")).astype(np.float32) / 255.0
        if not (frame[..., 3] > 0).any():
            raise SystemExit("key frame has no opaque pixels: %s" % path)
        keys.append(frame)
    return keys


def on_white(f):
    a = f[..., 3:4]
    return (f[..., :3] * a + (1 - a)).clip(0, 1)


def snap_durations(raw, unit_ms):
    """Snap nominal frame times to the GIF 10 ms grid by cumulative rounding."""
    durs, cum, prev = [], 0.0, 0
    for _, ms, _ in raw:
        cum += ms
        c = int(round(cum / 10.0) * 10)
        durs.append(c - prev)
        prev = c
    return durs


def to_p(frames, transparent, pal_src, scale=1.0, canvas=(352, 352), alpha_solid=ALPHA_SOLID_DEFAULT):
    cw, ch = canvas
    out = []
    for f in frames:
        if scale != 1.0:
            im = morph.to_image(f).resize((int(cw * scale), int(ch * scale)), Image.LANCZOS)
            f = np.asarray(im).astype(np.float32) / 255.0
        rgb = (on_white(f) * 255).round().astype(np.uint8)
        q = Image.fromarray(rgb, "RGB").quantize(palette=pal_src, dither=Image.NONE)
        arr = np.asarray(q).astype(np.uint16)
        if transparent:
            a8 = (f[..., 3] * 255).round().astype(np.uint8)
            arr = np.where(a8 >= alpha_solid, arr + 1, 0)
        p = Image.fromarray(arr.astype(np.uint8), "P")
        p.putpalette(([0, 0, 0] if transparent else []) + pal_src.getpalette()[:254 * 3])
        if transparent:
            p.info["transparency"] = 0
        out.append(p)
    return out


def save_gif(path, frames, durs, transparent, pal_src, scale=1.0, canvas=(352, 352),
             alpha_solid=ALPHA_SOLID_DEFAULT):
    pf = to_p(frames, transparent, pal_src, scale, canvas, alpha_solid)
    kw = dict(save_all=True, append_images=pf[1:], duration=durs, loop=0,
              optimize=False, format="GIF")
    if transparent:
        kw.update(disposal=2, transparency=0)
    pf[0].save(path, **kw)
    print("%-38s %7.1f KB  %d frames  %.2fs" %
          (os.path.basename(path), os.path.getsize(path) / 1024, len(pf), sum(durs) / 1000))


def build_palette(sample, canvas):
    cw, ch = canvas
    mont = Image.new("RGB", (cw * 4, ch * ((len(sample) + 3) // 4)), (255, 255, 255))
    for k, f in enumerate(sample):
        r, c = divmod(k, 4)
        mont.paste(Image.fromarray((on_white(f) * 255).round().astype(np.uint8), "RGB"), (c * cw, r * ch))
    return mont.quantize(colors=254, method=Image.MEDIANCUT, dither=Image.NONE)


def build_sequence(keys, nb, hold, unit_ms, tween_dir, frames_dir, pattern):
    """Assemble (frame, nominal_ms, label) rows for all transitions."""
    raw = []
    n_keys = len(keys)
    for i in range(1, n_keys + 1):
        j = i % n_keys + 1
        A, B = keys[i - 1], keys[j - 1]
        raw.append((A, hold[str(i)], "key%02d" % i))
        d_ab, d_ba = morph.get_flow(i, j, frames_dir=frames_dir, pattern=pattern)
        n = nb[str(i)]
        for k in range(1, n + 1):
            t = k / (n + 1.0)
            if t <= 0.5:
                f = morph.warp_premult(A, t * d_ab)
                src = "A"
            else:
                f = morph.warp_premult(B, (1.0 - t) * d_ba)
                src = "B"
            f = crisp_alpha(f)
            raw.append((f, unit_ms, "ib%02d_%02d_%d%s" % (i, j, k, src)))
            if tween_dir:
                morph.to_image(f).save(os.path.join(tween_dir, "tween_%02d_%02d_%d%s.png" % (i, j, k, src)))
    return raw


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the 24 fps v2 GIF from aligned keyframes.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help="case config JSON (default: cases/mimo_v2_24fps.json)")
    parser.add_argument("--frames-dir", help="override the config's frames_dir")
    parser.add_argument("--out", help="output directory (default: a fresh runs/<prefix>-<id>/ directory)")
    parser.add_argument("--no-tween-pngs", action="store_true",
                        help="skip writing the in-between preview PNGs")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    frames_dir = args.frames_dir or cfg["frames_dir"]
    if not os.path.isdir(frames_dir):
        raise SystemExit("frames directory not found: %s" % frames_dir)
    out_dir = open_run_dir(ROOT, cfg, args.out)
    print("New output directory:", out_dir)
    tween_dir = None if args.no_tween_pngs else os.path.join(out_dir, "frames_tween24")
    if tween_dir:
        os.makedirs(tween_dir, exist_ok=True)

    count = cfg["count"]
    pattern = cfg.get("pattern", "key_%02d.png")
    nb, hold = cfg["nb"], cfg["hold"]
    for table, name in ((nb, "nb"), (hold, "hold")):
        missing = [str(i) for i in range(1, count + 1) if str(i) not in table]
        if missing:
            raise SystemExit("config %s is missing keys: %s" % (name, ", ".join(missing)))
    keys = load_keys(frames_dir, pattern, count)

    fps = cfg.get("fps", 24)
    unit_ms = 1000.0 / fps
    raw = build_sequence(keys, nb, hold, unit_ms, tween_dir, frames_dir, pattern)

    durs = snap_durations(raw, unit_ms)
    motion = [(i, d) for i, (_, ms, lab) in enumerate(raw) if lab.startswith("ib") for d in [durs[i]]]
    print("frames total      : %d" % len(raw))
    print("motion frames     : %d  (avg %.2f fps)" %
          (len(motion), len(motion) / max(1e-9, sum(d for _, d in motion) / 1000.0)))
    print("total duration    : %.2f s" % (sum(durs) / 1000.0))
    print("duration histogram: %s" % {d: durs.count(d) for d in sorted(set(durs))})

    sample = [f for f, _, _ in raw][::4]
    pal_src = build_palette(sample, cfg["canvas"])
    frames = [f for f, _, _ in raw]
    alpha_solid = cfg.get("alpha_solid", ALPHA_SOLID_DEFAULT)
    for spec in cfg.get("outputs") or [{"name": "mimo2_24fps.gif", "transparent": False, "scale": 1.0}]:
        save_gif(os.path.join(out_dir, spec["name"]), frames, durs, spec.get("transparent", False),
                 pal_src, spec.get("scale", 1.0), cfg["canvas"], alpha_solid)
    with open(os.path.join(out_dir, "_plan24.json"), "w", encoding="utf-8") as handle:
        json.dump({"nb": nb, "hold": hold, "fps": fps, "durations": durs,
                   "labels": [lab for _, _, lab in raw]}, handle, indent=1)
    print("done")


if __name__ == "__main__":
    main()
