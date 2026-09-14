"""Verify the 24 fps GIF: montage + timing stats, plus an optional palette-size experiment.

Usage:
  python verify_24.py                                  # default case: v2/mimo2_24fps.gif
  python verify_24.py --gif runs/v2-24fps-x/mimo2_24fps.gif
  python verify_24.py --gif any.gif --plan _plan24.json

The palette-size experiment replays the in-between synthesis against the key
frames, so it only runs when the referenced plan file exists; otherwise the
script verifies the GIF alone.
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageSequence
import morph

ROOT = Path(__file__).resolve().parent


def load_gif(path):
    im = Image.open(path)
    frames = [f.convert("RGBA").copy() for f in ImageSequence.Iterator(im)]
    im2 = Image.open(path)
    durs = [f.info.get("duration", 0) for f in ImageSequence.Iterator(im2)]
    return frames, durs


def montage_sheet(frames, cols, tile):
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGB", (tile * cols, tile * rows), (255, 255, 255))
    for k, f in enumerate(frames):
        bg = Image.new("RGBA", f.size, (255, 255, 255, 255))
        bg.alpha_composite(f)
        r, c = divmod(k, cols)
        sheet.paste(bg.convert("RGB").resize((tile, tile), Image.LANCZOS), (c * tile, r * tile))
    d = ImageDraw.Draw(sheet)
    for i in range(1, cols):
        d.line([i * tile, 0, i * tile, sheet.height], fill=(255, 0, 200), width=1)
    for i in range(1, rows):
        d.line([0, i * tile, sheet.width, i * tile], fill=(255, 0, 200), width=1)
    return sheet


def palette_experiment(plan_path, frames_dir, durs, outdir):
    """Rebuild the in-between sequence and try smaller palettes (writes nothing permanent)."""
    plan = json.load(open(plan_path))
    # builders wrote "NB" historically; since the config-driven builder writes "nb"
    NB = {int(k): v for k, v in (plan.get("NB") or plan.get("nb")).items()}
    keys = [morph.load_key(i, frames_dir) for i in range(1, morph.N + 1)]
    raw = []
    for i in range(1, morph.N + 1):
        j = i % morph.N + 1
        A, B = keys[i - 1], keys[j - 1]
        raw.append(A)
        d_ab, d_ba = morph.get_flow(i, j, frames_dir=frames_dir)
        for k in range(1, NB[i] + 1):
            t = k / (NB[i] + 1.0)
            f = morph.warp_premult(A, t * d_ab) if t <= 0.5 else morph.warp_premult(B, (1 - t) * d_ba)
            raw.append(morph.crisp_alpha(f))

    def on_white(f):
        a = f[..., 3:4]
        return ((f[..., :3] * a + (1 - a)).clip(0, 1) * 255).round().astype(np.uint8)

    CW = 352
    mont = Image.new("RGB", (CW * 4, CW * ((len(raw[::4]) + 3) // 4)), (255, 255, 255))
    for k, f in enumerate(raw[::4]):
        r, c = divmod(k, 4)
        mont.paste(Image.fromarray(on_white(f), "RGB"), (c * CW, r * CW))

    for ncol in (254, 160, 96):
        pal = mont.quantize(colors=ncol, method=Image.MEDIANCUT, dither=Image.NONE)
        err = 0.0
        pf = []
        for f in raw:
            ref = on_white(f).astype(np.int16)
            q = Image.fromarray(on_white(f), "RGB").quantize(palette=pal, dither=Image.NONE)
            back = np.asarray(q.convert("RGB")).astype(np.int16)
            err += np.abs(ref - back).mean()
            p = Image.fromarray(np.asarray(q).astype(np.uint8), "P")
            p.putpalette(pal.getpalette()[:ncol * 3])
            pf.append(p)
        tmp = os.path.join(outdir, "_pal_test_%d.gif" % ncol)
        pf[0].save(tmp, save_all=True, append_images=pf[1:], duration=durs, loop=0, format="GIF")
        print("%3d colours -> %7.1f KB   mean quantisation error %.2f/255" %
              (ncol, os.path.getsize(tmp) / 1024, err / len(raw)))
        os.remove(tmp)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify the 24 fps GIF (montage, timing, palette probe).")
    parser.add_argument("--gif", default=str(ROOT / "mimo2_24fps.gif"),
                        help="GIF to verify (default: the historical v2/mimo2_24fps.gif)")
    parser.add_argument("--plan", default=str(ROOT / "_plan24.json"),
                        help="in-between plan JSON for the palette experiment "
                             "(default: v2/_plan24.json; skipped when missing)")
    parser.add_argument("--frames-dir", default=None,
                        help="key frame directory for the palette experiment "
                             "(default: morph's bundled v2/frames_key)")
    parser.add_argument("--outdir", help="directory for _check_<stem>.png (default: next to the GIF)")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.gif):
        parser.error("GIF not found: %s" % args.gif)

    frames, durs = load_gif(args.gif)
    motion = sum(d for d in durs if d <= 50)
    print("frames=%d  total=%.2fs  motion avg=%.2f fps" %
          (len(frames), sum(durs) / 1000,
           sum(1 for d in durs if d <= 50) / max(1e-9, motion / 1000)))

    outdir = args.outdir or os.path.dirname(os.path.abspath(args.gif))
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.gif))[0]
    out = os.path.join(outdir, "_check_%s.png" % stem)
    montage_sheet(frames, 8, 176).save(out)
    print("saved %s" % out)

    if not os.path.isfile(args.plan):
        print("plan not found (%s); skipping palette-size experiment" % args.plan)
        return
    if args.frames_dir and not os.path.isdir(args.frames_dir):
        parser.error("frames directory not found: %s" % args.frames_dir)
    palette_experiment(args.plan, args.frames_dir, durs, outdir)


if __name__ == "__main__":
    main()
