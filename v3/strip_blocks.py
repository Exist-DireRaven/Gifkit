"""Render full-resolution strips for selected 8-frame blocks (inspection aid)."""
import argparse
import os
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
BLOCKS = {1: (1, 8), 4: (25, 32), 7: (49, 56), 8: (57, 64), 9: (65, 72)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render tile-block filmstrips.")
    parser.add_argument("--tiles-dir", default=str(ROOT / "tiles"),
                        help="directory holding pair_NN.png tiles")
    parser.add_argument("--out-dir", default=str(ROOT), help="where _block*.png are written")
    parser.add_argument("--blocks", nargs="*", type=int, default=None,
                        help="block numbers to render (default: the historically inspected set)")
    args = parser.parse_args(argv)

    blocks = {b: BLOCKS[b] for b in (args.blocks or BLOCKS) if b in BLOCKS}
    if not blocks:
        raise SystemExit("no known blocks selected; known: %s" % sorted(BLOCKS))
    for b, (a, z) in blocks.items():
        imgs = [Image.open(os.path.join(args.tiles_dir, "pair_%02d.png" % k)).convert("RGB")
                for k in range(a, z + 1)]
        w = max(i.width for i in imgs); h = max(i.height for i in imgs)
        pad = 5
        S = Image.new("RGB", (len(imgs) * (w + pad) + pad, h + 26), (230, 230, 236))
        d = ImageDraw.Draw(S)
        for k, im in enumerate(imgs):
            x = pad + k * (w + pad)
            S.paste(im, (x + (w - im.width) // 2, 22 + (h - im.height)))
            d.text((x + 2, 4), "%d" % (a + k), fill=(200, 0, 120))
        S = S.resize((int(S.width * 1.25), int(S.height * 1.25)), Image.LANCZOS)
        S.save(os.path.join(args.out_dir, "_block%d.png" % b))
        print("saved _block%d.png  %s" % (b, S.size))


if __name__ == "__main__":
    main()
