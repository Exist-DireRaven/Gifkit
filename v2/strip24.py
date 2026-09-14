"""Full-res filmstrips of the 24 fps transitions + flow magnitude statistics."""
import argparse
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import morph

ROOT = Path(__file__).resolve().parent
NB = {1: 3, 2: 4, 3: 3, 4: 3, 5: 3, 6: 4, 7: 3, 8: 3,
      9: 3, 10: 3, 11: 4, 12: 3, 13: 5, 14: 3, 15: 3, 16: 2}


def on_white(f):
    a = f[..., 3:4]
    return ((f[..., :3] * a + (1 - a)).clip(0, 1) * 255).round().astype(np.uint8)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Flow statistics + 24 fps transition filmstrips.")
    parser.add_argument("--frames-dir", default=None, help="key frame directory (default: v2/frames_key)")
    parser.add_argument("--count", type=int, default=morph.N, help="number of keys (default: 16)")
    parser.add_argument("--out-dir", default=str(ROOT), help="where the strips are written")
    args = parser.parse_args(argv)

    keys = [morph.load_key(i, args.frames_dir) for i in range(1, args.count + 1)]

    print("%-9s %7s %7s %7s %7s" % ("pair", "p50", "p95", "p99", "max"))
    for i in range(1, args.count + 1):
        j = i % args.count + 1
        d_ab, _ = morph.get_flow(i, j, frames_dir=args.frames_dir)
        mag = np.sqrt(d_ab[..., 0] ** 2 + d_ab[..., 1] ** 2)
        print("%2d -> %-3d %7.1f %7.1f %7.1f %7.1f" %
              (i, j, *np.percentile(mag, [50, 95, 99]), mag.max()))

    for (i, j) in [(2, 3), (13, 14), (9, 10)]:
        if max(i, j) > args.count:
            continue
        A, B = keys[i - 1], keys[j - 1]
        d_ab, d_ba = morph.get_flow(i, j, frames_dir=args.frames_dir)
        n = NB[i]
        frames = [("K%d" % i, A)]
        for k in range(1, n + 1):
            t = k / (n + 1.0)
            if t <= 0.5:
                f, src = morph.warp_premult(A, t * d_ab), "A"
            else:
                f, src = morph.warp_premult(B, (1 - t) * d_ba), "B"
            frames.append(("%.2f%s" % (t, src), morph.crisp_alpha(f)))
        frames.append(("K%d" % j, B))
        tiles = [(lab, Image.fromarray(on_white(f), "RGB")) for lab, f in frames]
        w, h = tiles[0][1].size
        sheet = Image.new("RGB", (w * len(tiles) + 6 * (len(tiles) - 1), h), (255, 0, 200))
        d = ImageDraw.Draw(sheet)
        for k, (lab, t) in enumerate(tiles):
            sheet.paste(t, (k * (w + 6), 0))
            d.text((k * (w + 6) + 6, 4), lab, fill=(0, 120, 255))
        sheet = sheet.resize((int(sheet.width * 0.42), int(sheet.height * 0.42)), Image.LANCZOS)
        sheet.save(os.path.join(args.out_dir, "_strip24_%02d_%02d.png" % (i, j)))
        print("saved _strip24_%02d_%02d.png" % (i, j))


if __name__ == "__main__":
    main()
