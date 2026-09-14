"""Generate the walker example material: a synthetic second case that shares
nothing with Mimo (3x4 grid instead of 4x4, 160px cells, white-background
tiles instead of alpha, a walk cycle instead of combat).

Deterministic (no randomness).  Outputs, next to this script:
  walker_sheet.png   3x4 grid sheet, transparent background (12 poses)
  boxes.json         cell boxes for the grid sheet
  tiles/pair_01..16  2 blocks x 8 frames, white background (v3 tile format)
"""
import json
import math
import os
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent

# grid-sheet geometry (v1-style path)
CELL = 160
COLS, ROWS = 3, 4
SHEET_W, SHEET_H = COLS * CELL, ROWS * CELL
GROUND = 138            # y of the feet inside a cell
HIP_Y = 92

# tile geometry (v3-style path): white background, two 8-frame blocks
TILE_W, TILE_H = 192, 144
TILE_GROUND = 128
TILE_HIP_Y = 82
TILES = 16              # 2 blocks x 8
BLOCK = 8

INK = (29, 53, 87, 255)        # outline
BODY = (42, 157, 143, 255)     # teal fill
HEAD = (231, 111, 81, 255)     # head fill
LEG_L = (38, 70, 83, 255)
LEG_R = (69, 123, 157, 255)

L1 = L2 = 26            # thigh / shin lengths (grid sheet scale)


def leg_targets(phase):
    """Foot targets for (left, right) leg over one walk cycle phase in [0,1)."""
    swing = 22.0
    lift = 9.0
    # left foot: forward at phase 0.0 (contact), back at 0.5; right is anti-phase
    lx = swing * math.cos(2 * math.pi * phase)
    rx = swing * math.cos(2 * math.pi * (phase + 0.5))
    # swinging leg lifts while moving forward fastest
    ly_lift = max(0.0, math.sin(2 * math.pi * phase)) * lift
    ry_lift = max(0.0, math.sin(2 * math.pi * (phase + 0.5))) * lift
    return (lx, GROUND - ly_lift), (rx, GROUND - ry_lift)


def solve_ik(hx, hy, fx, fy, l1=L1, l2=L2):
    """Two-bone IK: return knee position for hip, foot and segment lengths."""
    dx, dy = fx - hx, fy - hy
    d = math.hypot(dx, dy)
    d = min(d, (l1 + l2) * 0.999)
    a = (l1 * l1 - l2 * l2 + d * d) / (2 * d)
    h = math.sqrt(max(0.0, l1 * l1 - a * a))
    ux, uy = dx / max(d, 1e-6), dy / max(d, 1e-6)
    # bend the knee forward (-x direction of travel)
    kx = hx + a * ux - h * uy
    ky = hy + a * uy + h * ux
    return kx, ky


def draw_pose(draw, cx, hip_y, ground_y, phase, scale=1.0):
    """Draw one walk pose centred horizontally at cx."""
    bob = 2.5 * math.cos(4 * math.pi * phase) * scale
    hip = (cx, hip_y + bob)
    (lfx, lfy), (rfx, rfy) = leg_targets(phase)
    # foot lift was computed in grid units; scale it into this canvas
    lfy = ground_y - (GROUND - lfy) * scale
    rfy = ground_y - (GROUND - rfy) * scale

    def draw_leg(fx_scaled, fy_scaled, color):
        knee = solve_ik(hip[0], hip[1], fx_scaled, fy_scaled)
        draw.line([hip, knee], fill=color, width=max(2, int(5 * scale)))
        draw.line([knee, (fx_scaled, fy_scaled)], fill=color, width=max(2, int(4 * scale)))
        draw.ellipse([fx_scaled - 4 * scale, fy_scaled - 3 * scale,
                      fx_scaled + 4 * scale, fy_scaled + 3 * scale], fill=color)

    draw_leg(cx + rfx * scale, rfy, LEG_R)
    # torso
    shoulder = (cx, hip_y + bob - 34 * scale)
    draw.line([hip, shoulder], fill=INK, width=max(3, int(9 * scale)))
    draw_leg(cx + lfx * scale, lfy, LEG_L)
    # arms (anti-phase to the legs)
    arm = 18 * scale
    for side, ph in ((1, 0.5), (-1, 0.0)):
        ax = side * arm * math.cos(2 * math.pi * (phase + ph))
        ay = shoulder[1] + 24 * scale + 4 * math.sin(2 * math.pi * (phase + ph))
        draw.line([shoulder, (cx + ax, ay)], fill=INK, width=max(2, int(5 * scale)))
        draw.ellipse([cx + ax - 3 * scale, ay - 3 * scale, cx + ax + 3 * scale, ay + 3 * scale],
                     fill=HEAD)
    # head
    hx, hy = cx, shoulder[1] - 13 * scale
    r = 12 * scale
    draw.ellipse([hx - r, hy - r, hx + r, hy + r], fill=HEAD, outline=INK, width=2)


def make_grid_sheet(out_dir):
    sheet = Image.new("RGBA", (SHEET_W, SHEET_H), (0, 0, 0, 0))
    boxes = {}
    for r in range(ROWS):
        for c in range(COLS):
            idx = r * COLS + c
            phase = idx / (ROWS * COLS)
            cell = Image.new("RGBA", (CELL, CELL), (0, 0, 0, 0))
            d = ImageDraw.Draw(cell)
            draw_pose(d, CELL // 2, HIP_Y, GROUND, phase, scale=1.0)
            sheet.alpha_composite(cell, (c * CELL, r * CELL))
            x0, y0 = c * CELL + 30, r * CELL + 34
            boxes["%d,%d" % (r, c)] = [x0, y0, x0 + 100, y0 + 108]
    sheet.save(out_dir / "walker_sheet.png")
    with open(out_dir / "boxes.json", "w", encoding="utf-8") as fh:
        json.dump(boxes, fh, indent=1)
    print("walker_sheet.png (%dx%d, %d cells) + boxes.json" % (SHEET_W, SHEET_H, ROWS * COLS))


def make_tiles(out_dir):
    tiles_dir = out_dir / "tiles"
    tiles_dir.mkdir(exist_ok=True)
    scale = 1.25
    for k in range(TILES):
        phase = k / TILES
        tile = Image.new("RGB", (TILE_W, TILE_H), (255, 255, 255))
        d = ImageDraw.Draw(tile)
        draw_pose(d, TILE_W // 2, TILE_HIP_Y, TILE_GROUND, phase, scale=scale)
        tile.save(tiles_dir / ("pair_%02d.png" % (k + 1)))
    print("tiles/pair_01..%02d.png (%dx%d, white bg)" % (TILES, TILE_W, TILE_H))


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Generate the walker example material.")
    parser.add_argument("--out-dir", default=str(HERE), help="output directory (default: examples/walker)")
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    make_grid_sheet(out_dir)
    make_tiles(out_dir)


if __name__ == "__main__":
    main()
