"""Build aligned frames for the v1 sheet; compare two anchor strategies; save contact sheets.

One-off analysis tool: writes _align_bottom.png / _align_anchor.png,
_frames_meta.npy and _canvas.json next to the source.  Requires _boxes.json.
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

ROOT = Path(__file__).resolve().parent


def anchor_dense(sub_alpha, blur=31):
    """Anchor = centroid of squared blurred alpha -> sits on the character's dense body core."""
    b = ndimage.uniform_filter(sub_alpha, size=blur, mode="constant")
    w = b ** 2
    if w.sum() <= 0:
        return sub_alpha.shape[1] / 2, sub_alpha.shape[0] / 2
    ys, xs = np.mgrid[0:sub_alpha.shape[0], 0:sub_alpha.shape[1]]
    return float((xs * w).sum() / w.sum()), float((ys * w).sum() / w.sum())


def compose(f, mode, cw, ch):
    """Return RGBA canvas for one frame under an alignment mode."""
    out = np.zeros((ch, cw, 4), np.float32)
    if mode == "bottom":          # bbox bottom on baseline, bbox centre-x centred
        cx = f["w"] / 2.0
        base = ch - 20
        oy = base - f["h"]
    else:                          # dense-mass anchor centred
        cx, cy = f["ax"], f["ay"]
        oy = round(ch / 2 - cy)
    ox = round(cw / 2 - cx)
    ox = max(0, min(cw - f["w"], ox))
    oy = max(0, min(ch - f["h"], oy))
    out[oy:oy + f["h"], ox:ox + f["w"]] = f["img"]
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="v1 anchor-strategy comparison sheets.")
    parser.add_argument("--source", default=str(ROOT / "mimo.png"), help="sheet image")
    parser.add_argument("--boxes", default=str(ROOT / "_boxes.json"), help="boxes JSON")
    parser.add_argument("--out-dir", default=str(ROOT), help="where the sheets/metadata are written")
    args = parser.parse_args(argv)

    im = Image.open(args.source).convert("RGBA")
    rgba = np.asarray(im).astype(np.float32) / 255.0
    alpha = rgba[..., 3]

    # --- alpha diagnostics -------------------------------------------------
    a8 = (alpha * 255).round().astype(np.uint8)
    nz = a8[a8 > 0]
    print("alpha percentiles (nonzero):", np.percentile(nz, [1, 5, 25, 50, 75, 95, 99]).round(0))
    print("alpha==255 px:", int((a8 == 255).sum()), " alpha>=250 px:", int((a8 >= 250).sum()),
          " alpha in 1..254:", int(((a8 > 0) & (a8 < 255)).sum()))
    hist = np.bincount(a8.ravel(), minlength=256)
    print("alpha hist top bins:", sorted(enumerate(hist), key=lambda t: -t[1])[:8])

    with open(args.boxes, encoding="utf-8") as handle:
        boxes = {tuple(map(int, k.split(","))): v for k, v in json.load(handle).items()}

    frames = []
    for r in range(4):
        for c in range(4):
            x0, y0, x1, y1 = boxes[(r, c)]
            crop = rgba[y0:y1, x0:x1].copy()
            sa = crop[..., 3]
            ax, ay = anchor_dense(sa)
            # ground line: lowest row whose alpha mass is >= 1% of the sprite's total
            row_mass = sa.sum(axis=1)
            thr = 0.01 * sa.sum()
            ys = np.nonzero(row_mass > thr)[0]
            ground = float(ys[-1]) if len(ys) else float(sa.shape[0] - 1)
            frames.append(dict(rc=(r, c), img=crop, ax=ax, ay=ay, ground=ground,
                               w=crop.shape[1], h=crop.shape[0]))
            print("  r%dc%d %3dx%3d  anchor=(%.0f,%.0f) ground=%.0f" % (r + 1, c + 1, crop.shape[1], crop.shape[0], ax, ay, ground))

    CW = max(f["w"] for f in frames) + 40
    CH = max(f["h"] for f in frames) + 40
    print("canvas:", CW, CH)

    for mode in ("bottom", "anchor"):
        sheet = Image.new("RGBA", (CW * 4, CH * 4), (245, 245, 248, 255))
        for i, f in enumerate(frames):
            cvs = compose(f, mode, CW, CH)
            tile = Image.fromarray((cvs * 255).round().astype(np.uint8), "RGBA")
            bg = Image.new("RGBA", tile.size, (255, 255, 255, 255))
            bg.alpha_composite(tile)
            r, c = divmod(i, 4)
            sheet.paste(bg, (c * CW, r * CH))
        d = ImageDraw.Draw(sheet)
        for i in range(1, 4):
            d.line([0, i * CH, CW * 4, i * CH], fill=(200, 200, 210, 255), width=2)
            d.line([i * CW, 0, i * CW, CH * 4], fill=(200, 200, 210, 255), width=2)
        # guides: centre cross + baseline
        for r in range(4):
            for c in range(4):
                x, y = c * CW, r * CH
                d.line([x + CW // 2, y, x + CW // 2, y + CH], fill=(0, 170, 255, 255), width=1)
                d.line([x, y + CH - 20, x + CW, y + CH - 20], fill=(255, 0, 200, 255), width=1)
        sheet.convert("RGB").save(os.path.join(args.out_dir, "_align_%s.png") % mode)
        print("saved _align_%s.png" % mode)

    np.save(os.path.join(args.out_dir, "_frames_meta.npy"),
            np.array([[f["w"], f["h"], f["ax"], f["ay"], f["ground"]] for f in frames], np.float32))
    json.dump({"CW": CW, "CH": CH}, open(os.path.join(args.out_dir, "_canvas.json"), "w"))


if __name__ == "__main__":
    main()
