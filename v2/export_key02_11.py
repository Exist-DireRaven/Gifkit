"""Export key02..key11 as a clean image set for hand-drawing in-betweens.

Layout of the output directory:
  <stem>02.png .. <stem>11.png    352x352, white background (safest input for image models)
  transparent/<stem>02.png ..     352x352, alpha
  pairs/pair_02_03.png ..         adjacent keyframes side by side (for "draw the in-between")
  sheet_<stem>02_11.png           5x2 labelled contact sheet
  README.txt                      what each key is
"""
import argparse
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import morph

ROOT = Path(__file__).resolve().parent
KEYS = list(range(2, 12))
LABEL = {
    2:  "step in (turn to 3/4, one leg forward)",
    3:  "big lunge / running push-off",
    4:  "low charge crouch, both fists forward",
    5:  "raise the cannon, held at chest (swing arc)",
    6:  "thrust the cannon forward, aiming",
    7:  "fire - muzzle flash, recoil back",
    8:  "lower the cannon, hug it to the chest",
    9:  "idle with plush rabbit, cannon slung",
    10: "straight punch, right arm extended",
    11: "spin attack, both arms sweeping",
}

CW = CH = 352


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export keyframes as a hand-off image set.")
    parser.add_argument("--frames-dir", default=None, help="key frame directory (default: v2/frames_key)")
    parser.add_argument("--out-dir", default=str(ROOT / "key02_11"),
                        help="output directory (default: v2/key02_11)")
    args = parser.parse_args(argv)

    dst = args.out_dir
    os.makedirs(os.path.join(dst, "transparent"), exist_ok=True)
    os.makedirs(os.path.join(dst, "pairs"), exist_ok=True)

    tiles = []
    for i in KEYS:
        f = morph.load_key(i, args.frames_dir)
        im = morph.to_image(f)
        im.save(os.path.join(dst, "transparent", "key%02d.png" % i))

        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        rgb = bg.convert("RGB")
        rgb.save(os.path.join(dst, "key%02d.png" % i))
        tiles.append((i, rgb))
        print("key%02d.png  <- %s" % (i, LABEL[i]))

    # ---- adjacent pairs, side by side with a divider ----
    for a, b in zip(KEYS[:-1], KEYS[1:]):
        ta = next(t for i, t in tiles if i == a)
        tb = next(t for i, t in tiles if i == b)
        gap = 8
        pair = Image.new("RGB", (CW * 2 + gap, CH), (0, 0, 0))
        pair.paste(ta, (0, 0))
        pair.paste(tb, (CW + gap, 0))
        d = ImageDraw.Draw(pair)
        d.text((8, 8), "key%02d" % a, fill=(0, 110, 255))
        d.text((CW + gap + 8, 8), "key%02d" % b, fill=(255, 0, 160))
        pair.save(os.path.join(dst, "pairs", "pair_%02d_%02d.png" % (a, b)))

    # ---- contact sheet, 5 x 2 ----
    cols, rows = 5, 2
    pad = 6
    lblh = 26
    sheet = Image.new("RGB", (cols * CW + (cols + 1) * pad,
                              rows * (CH + lblh) + (rows + 1) * pad), (238, 238, 242))
    d = ImageDraw.Draw(sheet)
    for k, (i, t) in enumerate(tiles):
        r, c = divmod(k, cols)
        x = pad + c * (CW + pad)
        y = pad + r * (CH + lblh + pad)
        sheet.paste(t, (x, y))
        d.rectangle([x, y, x + CW - 1, y + CH - 1], outline=(200, 200, 210))
        d.text((x + 4, y + CH + 6), "key%02d  %s" % (i, LABEL[i]), fill=(40, 40, 40))
    sheet.save(os.path.join(dst, "sheet_key02_11.png"))
    print("\nsheet_key02_11.png", sheet.size)

    with open(os.path.join(dst, "README.txt"), "w", encoding="utf-8") as fh:
        fh.write("key02 - key11 keyframe set (352x352, aligned: same ground line, body mass centred)\n")
        fh.write("Source: v2/mimo2.png cells r1c2..r3c3, alpha-segmented, no retouching.\n\n")
        for i in KEYS:
            fh.write("key%02d  %s\n" % (i, LABEL[i]))
        fh.write("\nFiles:\n")
        fh.write("  key02.png..key11.png     white background, RGB  (recommended for image models)\n")
        fh.write("  transparent/*.png        same frames with alpha\n")
        fh.write("  pairs/pair_XX_YY.png     adjacent pair side by side, for 'draw the in-between'\n")
        fh.write("  sheet_key02_11.png       all 10 in one labelled sheet\n")


if __name__ == "__main__":
    main()
