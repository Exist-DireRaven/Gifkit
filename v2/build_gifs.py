"""Build the v2 GIFs (key / smooth cut) from aligned keyframes.

Two versions, same total cycle time so they can be compared directly:
  <stem>_key.gif    : keyframes only, animation-principled timing (holds + snaps)
  <stem>_smooth.gif : keyframes + motion-compensated in-betweens, eased timing

PLAN[i] = (hold_ms_of_key_i, [(t, source, duration_ms), ...])
  t      : phase of the in-between (0 = key i, 1 = key i+1)
  source : 'A' = key i deformed forward, 'B' = key i+1 deformed backward

Usage:
  python v2/build_gifs.py                          # bundled case: cases/mimo_v2_key.json
  python v2/build_gifs.py --config my_case.json    # another keyframe set
  python v2/build_gifs.py --out path/to/dir        # explicit output directory (must be empty or new)

Case config keys: frames_dir, pattern, count, canvas, small_size, alpha_solid,
plan, run_prefix.  Relative paths resolve against the config file's directory.
Material policy: a missing keyframe file or a fully transparent keyframe is an error.
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
DEFAULT_CONFIG = ROOT.parent / "cases" / "mimo_v2_key.json"

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
    return tempfile.mkdtemp(prefix=cfg.get("run_prefix", "v2-legacy-"), dir=runs)


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


def to_p(seq, transparent, pal_src, alpha_solid=ALPHA_SOLID_DEFAULT):
    out = []
    for f, _, _ in seq:
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


def save_gif(path, seq, transparent, pal_src, alpha_solid=ALPHA_SOLID_DEFAULT):
    pf = to_p(seq, transparent, pal_src, alpha_solid)
    durs = [d for _, d, _ in seq]
    kw = dict(save_all=True, append_images=pf[1:], duration=durs, loop=0,
              optimize=False, format="GIF")
    if transparent:
        kw.update(disposal=2, transparency=0)
    pf[0].save(path, **kw)
    print("%-34s %7.1f KB  %2d frames  %.2fs" %
          (os.path.basename(path), os.path.getsize(path) / 1024, len(pf), sum(durs) / 1000))


def half(seq, size):
    out = []
    for f, d, lab in seq:
        im = morph.to_image(f).resize(size, Image.LANCZOS)
        g = np.asarray(im).astype(np.float32) / 255.0
        out.append((g, d, lab))
    return out


def build_palette(sample, canvas):
    """Shared palette from a representative montage of (frame, ...) samples."""
    cw, ch = canvas
    mont = Image.new("RGB", (cw * 4, ch * ((len(sample) + 3) // 4)), (255, 255, 255))
    for k, f in enumerate(sample):
        r, c = divmod(k, 4)
        mont.paste(Image.fromarray((on_white(f) * 255).round().astype(np.uint8), "RGB"), (c * cw, r * ch))
    return mont.quantize(colors=254, method=Image.MEDIANCUT, dither=Image.NONE)


def build_sequences(keys, plan, tween_dir, frames_dir, pattern):
    """Assemble the smooth and key-only sequences; write in-between previews."""
    smooth = []      # (frame, duration, label)
    keyonly = []
    for i in range(1, len(keys) + 1):
        j = i % len(keys) + 1
        hold, tweens = plan[str(i)]
        A, B = keys[i - 1], keys[j - 1]
        smooth.append((A, hold, "key%02d" % i))
        keyonly.append((A, hold + sum(d for _, _, d in tweens), "key%02d" % i))
        d_ab, d_ba = morph.get_flow(i, j, frames_dir=frames_dir, pattern=pattern)
        for k, (t, src, dur) in enumerate(tweens):
            f = morph.warp_premult(A, t * d_ab) if src == "A" else morph.warp_premult(B, (1.0 - t) * d_ba)
            f = crisp_alpha(f)
            smooth.append((f, dur, "tw%02d_%02d_%d%s" % (i, j, k, src)))
            if tween_dir:
                morph.to_image(f).save(os.path.join(tween_dir, "tween_%02d_%02d_%d%s.png" % (i, j, k, src)))
    return smooth, keyonly


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build v2 key/smooth GIFs from aligned keyframes.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help="case config JSON (default: cases/mimo_v2_key.json)")
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
    tween_dir = None if args.no_tween_pngs else os.path.join(out_dir, "frames_tween")
    if tween_dir:
        os.makedirs(tween_dir, exist_ok=True)

    count = cfg["count"]
    pattern = cfg.get("pattern", "key_%02d.png")
    plan = cfg["plan"]
    missing = [str(i) for i in range(1, count + 1) if str(i) not in plan]
    if missing:
        raise SystemExit("config plan is missing transitions: %s" % ", ".join(missing))
    keys = load_keys(frames_dir, pattern, count)

    smooth, keyonly = build_sequences(keys, plan, tween_dir, frames_dir, pattern)

    print("key-only frames : %d  total %.2fs" % (len(keyonly), sum(d for _, d, _ in keyonly) / 1000))
    print("smooth frames   : %d  total %.2fs" % (len(smooth), sum(d for _, d, _ in smooth) / 1000))

    sample = [f for f, _, _ in smooth][::max(1, len(smooth) // 16)]
    pal_src = build_palette(sample, cfg["canvas"])
    print("palette colours:", len(pal_src.getcolors(maxcolors=100000) or []))

    alpha_solid = cfg.get("alpha_solid", ALPHA_SOLID_DEFAULT)
    stem = cfg.get("output_stem") or "mimo2"
    save_gif(os.path.join(out_dir, stem + "_key.gif"), keyonly, False, pal_src, alpha_solid)
    save_gif(os.path.join(out_dir, stem + "_smooth.gif"), smooth, False, pal_src, alpha_solid)
    save_gif(os.path.join(out_dir, stem + "_key_transparent.gif"), keyonly, True, pal_src, alpha_solid)
    save_gif(os.path.join(out_dir, stem + "_smooth_transparent.gif"), smooth, True, pal_src, alpha_solid)

    # small web version (half size)
    small_size = tuple(cfg.get("small_size", (176, 176)))
    save_gif(os.path.join(out_dir, stem + "_smooth_small.gif"), half(smooth, small_size), True,
             pal_src, alpha_solid)
    with open(os.path.join(out_dir, "_plan.json"), "w", encoding="utf-8") as handle:
        json.dump(plan, handle, indent=1)
    print("done")


if __name__ == "__main__":
    main()
