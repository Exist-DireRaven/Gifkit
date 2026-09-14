"""Align the 16 keyframes of the NEW sheet onto a common canvas (v2 material prep).

Alignment: x = dense-alpha mass anchor (character body stays put),
           y = sprite bottom on a fixed ground line.
Writes frames_key/key_NN.png, _align_meta.json and _align_check.png.
NOTE: this overwrites frames_key/ content.
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

ROOT = Path(__file__).resolve().parent
CW = CH = 352
BASELINE = 332
BLUR = 31


def dense_anchor(sub_alpha, blur=BLUR):
    b = ndimage.uniform_filter(sub_alpha, size=blur, mode="constant")
    w = b ** 2
    ys, xs = np.mgrid[0:sub_alpha.shape[0], 0:sub_alpha.shape[1]]
    if w.sum() <= 0:
        return sub_alpha.shape[1] / 2.0, sub_alpha.shape[0] / 2.0
    return float((xs * w).sum() / w.sum()), float((ys * w).sum() / w.sum())


def main(argv=None):
    parser = argparse.ArgumentParser(description="Align the v2 sheet cells onto the shared canvas.")
    parser.add_argument("--source", default=str(ROOT / "mimo2.png"), help="sheet image")
    parser.add_argument("--boxes", default=str(ROOT / "_boxes.json"), help="boxes JSON")
    parser.add_argument("--out-dir", default=str(ROOT), help="where frames_key/ is written")
    parser.add_argument("--grid", type=int, default=4, help="grid size (default: 4 -> 4x4)")
    args = parser.parse_args(argv)

    frames_dir = os.path.join(args.out_dir, "frames_key")
    os.makedirs(frames_dir, exist_ok=True)

    im = Image.open(args.source).convert("RGBA")
    rgba = np.asarray(im).astype(np.float32) / 255.0
    with open(args.boxes, encoding="utf-8") as handle:
        boxes = {tuple(map(int, k.split(","))): v for k, v in json.load(handle).items()}

    meta = []
    aligned = []
    for r in range(args.grid):
        for c in range(args.grid):
            x0, y0, x1, y1 = boxes[(r, c)]
            crop = rgba[y0:y1, x0:x1].copy()
            h, w = crop.shape[:2]
            ax, ay = dense_anchor(crop[..., 3])
            row_mass = crop[..., 3].sum(axis=1)
            thr = 0.01 * row_mass.sum()
            ys = np.nonzero(row_mass > thr)[0]
            ground = float(ys[-1]) if len(ys) else float(h - 1)

            canvas = np.zeros((CH, CW, 4), np.float32)
            ox = int(round(CW / 2 - ax))
            oy = int(round(BASELINE - ground))
            ox = max(0, min(CW - w, ox)); oy = max(0, min(CH - h, oy))
            canvas[oy:oy + h, ox:ox + w] = crop
            aligned.append(canvas)
            meta.append(dict(rc=(r + 1, c + 1), w=w, h=h, ax=ax, ay=ay, ground=ground, ox=ox, oy=oy))
            idx = len(aligned)
            Image.fromarray((canvas * 255).round().astype(np.uint8), "RGBA").save(
                os.path.join(frames_dir, "key_%02d.png" % idx))
            print("key_%02d r%dc%d %3dx%3d anchor=(%6.1f,%6.1f) ground=%5.1f -> offset=(%4d,%4d)"
                  % (idx, r + 1, c + 1, w, h, ax, ay, ground, ox, oy))

    json.dump(meta, open(os.path.join(args.out_dir, "_align_meta.json"), "w"), indent=1)

    # contact sheet with anchor crosshair + ground line
    sheet = Image.new("RGB", (CW * args.grid, CH * args.grid), (245, 245, 248))
    for i, f in enumerate(aligned):
        tile = Image.new("RGBA", (CW, CH), (255, 255, 255, 255))
        tile.alpha_composite(Image.fromarray((f * 255).round().astype(np.uint8), "RGBA"))
        tile = tile.convert("RGB")
        d = ImageDraw.Draw(tile)
        d.line([CW // 2, 0, CW // 2, CH], fill=(0, 170, 255), width=1)
        d.line([0, BASELINE, CW, BASELINE], fill=(255, 0, 200), width=1)
        r, c = divmod(i, args.grid)
        sheet.paste(tile, (c * CW, r * CH))
    sheet.resize((CW * 2, CH * 2), Image.LANCZOS).save(os.path.join(args.out_dir, "_align_check.png"))
    print("\nsaved %s (%d) and _align_check.png" % (frames_dir, len(aligned)))


if __name__ == "__main__":
    main()
