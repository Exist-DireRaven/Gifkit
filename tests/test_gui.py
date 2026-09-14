"""GUI helper tests: pure logic always runs; Tk instantiation is skipped
gracefully on headless machines."""
import json
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys_path_ready = True

from gifkit import cli, gui  # noqa: E402


def test_key_white_background_checkerboard(tmp_path):
    """Two-tone fake-transparency checkerboard (darker than any near-white
    threshold) must be learned from the border and fully removed."""
    src = tmp_path / "checker.png"
    arr = np.full((240, 240, 3), 252, np.uint8)
    sq = np.indices((240, 240)).sum(axis=0) // 12 % 2  # 12px checker
    arr[sq == 1] = (213, 213, 213)
    # sprite: dark blob with an enclosed white hole, overlapping both tones
    arr[60:180, 60:180] = (40, 90, 160)
    arr[100:120, 100:120] = (255, 255, 255)
    Image.fromarray(arr, "RGB").save(src)

    dst = tmp_path / "keyed.png"
    gui.key_white_background(src, dst)
    out = np.asarray(Image.open(dst).convert("RGBA"))
    assert out[0, 0, 3] == 0          # light checker gone
    assert out[5, 13, 3] == 0         # dark checker square gone
    assert out[120, 70, 3] == 255     # sprite body opaque
    assert out[110, 110, 3] == 255    # enclosed white hole kept


def test_grid_autodetect_tightly_packed(tmp_path):
    """Near-touching sprites (2px gaps, density dips instead of empty
    gutters): band detection merges them, the density-period method must
    still recover the 3x2 grid."""
    sheet = tmp_path / "packed.png"
    cw, ch, margin = 100, 100, 40
    W, H = margin * 2 + cw * 3, margin * 2 + ch * 2
    arr = np.full((H, W, 3), 255, np.uint8)
    for r in range(2):
        for c in range(3):
            y0, x0 = margin + r * ch, margin + c * cw
            arr[y0 + 8:y0 + 94, x0 + 4:x0 + 98, 0] = 50    # body, 2px from the neighbour
            arr[y0 + 20:y0 + 60, x0 + 30:x0 + 70, 2] = 150  # head, extra density dip
    Image.fromarray(arr, "RGB").save(sheet)
    # the full flow must recover the grid (bands here; periodic is the fallback)
    config_path, info = gui.write_own_sheet_case(
        tmp_path / "out", sheet, rows=1, cols=1, duration_ms=100)
    assert info["grid_detected"] == (2, 3)


def test_grid_autodetect_and_no_top_clipping(tmp_path):
    """Auto-detected grid + band boxes: a sprite much taller than the rest
    keeps its ahoge, and the ground line sits below the tallest frame."""
    sheet = tmp_path / "grid.png"
    arr = np.full((400, 600, 3), 255, np.uint8)
    # two columns x two rows; row-0 col-0 sprite reaches up to y=2 (ahoge)
    for (ry, rx), (h0, h1, w0, w1) in {
        (0, 0): (2, 180, 20, 270),      # tall sprite, nearly touches the top
        (0, 1): (40, 180, 320, 560),    # shorter
        (1, 0): (230, 380, 20, 270),
        (1, 1): (230, 380, 320, 560),
    }.items():
        arr[ry + h0:ry + h1, rx + w0:rx + w1, 0] = 50
        arr[ry + h0:ry + h1, rx + w0:rx + w1, 1] = 90
        arr[ry + h0:ry + h1, rx + w0:rx + w1, 2] = 170
    Image.fromarray(arr, "RGB").save(sheet)

    out = tmp_path / "out"
    config_path, info = gui.write_own_sheet_case(out, sheet, rows=4, cols=4,  # wrong on purpose
                                                 duration_ms=100)
    assert info["grid_detected"] == (2, 2)           # detected, spinner ignored
    boxes = json.loads((out / "boxes.json").read_text(encoding="utf-8"))
    assert boxes["0,0"][1] <= 3                      # ahoge box reaches the ink top
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    assert cfg["grid"] == [2, 2]
    # tallest box must fit between canvas top and the ground line
    bh = boxes["0,0"][3] - boxes["0,0"][1] + 1
    assert cfg["baseline"] >= bh

    module = cli.load_builder("make_gif.py")
    build_dir = tmp_path / "out" / "build"
    build_dir.mkdir()
    module.main(["--config", str(config_path), "--out", str(build_dir)])
    frames = sorted((build_dir / "frames").glob("*.png"))
    assert len(frames) == 4
    # decode the tall frame: ink must start at y>=1 (nothing clipped at y=0)
    f0 = np.asarray(Image.open(frames[0]).convert("RGBA"))
    ys, _xs = np.nonzero(f0[..., 3] > 96)
    assert ys.min() >= 1


def test_boxes_align_with_sprites_when_ink_is_off_centre(tmp_path):
    """Regression (run Gifkit-20260913-235926): a sheet whose ink leaves a
    large empty strip at one edge must not be sliced into equal full-image
    cells — equal division drifts off the real sprite pitch, splits every
    sprite across two cells, and normalize_height then blows the clipped
    crops up (frames grow row by row, last row a giant clipped bust).
    Cut lines follow the content box's gutters instead."""
    sheet = tmp_path / "offcentre.png"
    W, H = 600, 500
    arr = np.full((H, W, 3), 255, np.uint8)
    for r in range(2):
        for c in range(3):
            y0, x0 = 20 + r * 190, 10 + c * 200   # pitch 190 of a 500-tall image, 120px empty below
            arr[y0:y0 + 170, x0:x0 + 160, 0] = 50
            arr[y0:y0 + 170, x0:x0 + 160, 2] = 150
    Image.fromarray(arr, "RGB").save(sheet)

    out = tmp_path / "out"
    config_path, info = gui.write_own_sheet_case(out, sheet, rows=1, cols=1, duration_ms=100)
    assert info["grid_detected"] == (2, 3)
    boxes = json.loads((out / "boxes.json").read_text(encoding="utf-8"))
    assert boxes["0,0"][3] <= 200          # row-0 box stays clear of row-1's sprite
    assert boxes["1,0"][1] >= 200          # row-1 box keeps its sprite's head
    assert boxes["1,0"][3] >= 379          # ...and its feet

    module = cli.load_builder("make_gif.py")
    build_dir = out / "build"
    build_dir.mkdir()
    module.main(["--config", str(config_path), "--out", str(build_dir)])
    heights = []
    for p in sorted((build_dir / "frames").glob("*.png")):
        a = np.asarray(Image.open(p).convert("RGBA"))[..., 3]
        ys, _xs = np.nonzero(a >= 96)
        heights.append(int(ys.max() - ys.min() + 1))
    assert max(heights) - min(heights) <= 3    # every frame the same size


def test_manual_grid_mode_is_respected(tmp_path):
    """Manual mode (detect_grid=False) must use the typed rows/cols verbatim:
    no detection override, no extra cells, boxes sliced on the given grid."""
    sheet = tmp_path / "grid.png"
    arr = np.full((420, 600, 3), 255, np.uint8)
    for r in range(2):                      # a sheet whose real grid is 2x3
        for c in range(3):
            arr[r * 210 + 10:r * 210 + 200, c * 200 + 10:c * 200 + 190, 0] = 50
            arr[r * 210 + 10:r * 210 + 200, c * 200 + 10:c * 200 + 190, 2] = 150
    Image.fromarray(arr, "RGB").save(sheet)

    out = tmp_path / "out"
    config_path, info = gui.write_own_sheet_case(out, sheet, rows=1, cols=1,
                                                 duration_ms=100, detect_grid=False)
    assert info["grid_detected"] is None            # detection did not run
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    assert cfg["grid"] == [1, 1]
    boxes = json.loads((out / "boxes.json").read_text(encoding="utf-8"))
    assert set(boxes) == {"0,0"}
    x0, y0, x1, y1 = boxes["0,0"]
    assert x0 <= 10 and x1 >= 590 and y0 <= 10 and y1 >= 410  # whole sheet, one cell


def test_normalize_height_is_an_explicit_option(tmp_path):
    """Default keeps original proportions; opting in lands in the case config
    (and therefore in make_gif's normalize path)."""
    sheet = tmp_path / "one.png"
    arr = np.full((220, 240, 3), 255, np.uint8)
    arr[10:210, 20:220, 0] = 50
    arr[10:210, 20:220, 2] = 150
    Image.fromarray(arr, "RGB").save(sheet)

    out = tmp_path / "out_default"
    config_path, _info = gui.write_own_sheet_case(out, sheet, rows=1, cols=1, duration_ms=100)
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    assert cfg["normalize_height"] is False

    out = tmp_path / "out_on"
    config_path, _info = gui.write_own_sheet_case(out, sheet, rows=1, cols=1,
                                                  duration_ms=100, normalize_height=True)
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    assert cfg["normalize_height"] is True


def test_prep_and_build_worker_runs_off_thread(tmp_path):
    """The GUI's full worker (prep + build) works headlessly and reports one
    done=True — the preprocessing that used to run on the Tk thread is part
    of the same background job."""
    import queue as _queue
    sheet = tmp_path / "worker.png"
    arr = np.full((220, 480, 3), 255, np.uint8)
    for c in range(2):
        arr[10:210, c * 240 + 20:c * 240 + 220, 0] = 50
        arr[10:210, c * 240 + 20:c * 240 + 220, 2] = 150
    Image.fromarray(arr, "RGB").save(sheet)

    out = tmp_path / "out"
    q = _queue.Queue()
    gui.prep_and_build_in_thread(
        {"sheet": str(sheet), "out": str(out), "build_dir": str(out / "build"),
         "rows": 1, "cols": 2, "duration": 100, "detect": True, "normalize": False}, q)
    deadline = time.time() + 120
    while time.time() < deadline:
        kind, *rest = q.get(timeout=30)
        if kind == "done":
            assert rest[0] is True, rest[1]
            break
    else:
        pytest.fail("worker never finished")
    gifs = list((out / "build").glob("*.gif"))
    assert len(gifs) == 4


def test_write_own_sheet_case_and_build(tmp_path):
    """White-background RGB sheet (what image models actually produce):
    the GUI path must key it, measure real sprite bounds (poses may overflow
    the even-grid inset), auto-fit the canvas and build transparent GIFs."""
    sheet = tmp_path / "mysheet.png"
    rows, cols = 2, 3
    cell_w, cell_h = 240, 180
    arr = np.full((cell_h * rows, cell_w * cols, 3), 255, np.uint8)
    for r in range(rows):
        for c in range(cols):
            y0, x0 = r * cell_h, c * cell_w
            # blob overflows the 6% even-grid inset on top and bottom (y=4..176)
            arr[y0 + 4:y0 + 176, x0 + 8:x0 + 224, 0] = 40 + 30 * r
            arr[y0 + 4:y0 + 176, x0 + 8:x0 + 224, 1] = 90
            arr[y0 + 4:y0 + 176, x0 + 8:x0 + 224, 2] = 160 + 20 * c
            arr[y0 + 40:y0 + 60, x0 + 40:x0 + 60, :] = 255  # enclosed white hole
    Image.fromarray(arr, "RGB").save(sheet)

    out = tmp_path / "out"
    config_path, info = gui.write_own_sheet_case(out, sheet, rows=rows, cols=cols,
                                                 duration_ms=120)
    assert info["keyed"] is True
    keyed = np.asarray(Image.open(out / "sheet_keyed.png").convert("RGBA"))
    assert keyed[0, 0, 3] == 0                       # background gone
    assert keyed[90, 50, 3] == 255                   # sprite body opaque
    assert keyed[50, 50, :3].tolist() == [255, 255, 255]
    assert keyed[50, 50, 3] == 255                   # enclosed white hole kept

    boxes = json.loads((out / "boxes.json").read_text(encoding="utf-8"))
    bx0, by0, bx1, by1 = boxes["0,0"]
    # the box must cover the sprite's full measured extent (band coordinates
    # are absolute; the blob reaches y=2 at the top of the sheet)
    assert by0 <= 3 and by1 >= 178

    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    assert Path(cfg["source"]) == (out / "sheet_keyed.png").resolve()

    module = cli.load_builder("make_gif.py")
    build_dir = tmp_path / "out" / "build"
    build_dir.mkdir()  # the GUI builds into a fresh subfolder beside the case files
    module.main(["--config", str(config_path), "--out", str(build_dir)])
    stem = sheet.stem
    for name in (stem + ".gif", stem + "_transparent.gif", stem + "_small.gif"):
        assert (build_dir / name).is_file(), name
    with Image.open(build_dir / (stem + "_transparent.gif")) as gif:
        decoded = np.asarray(gif.convert("RGBA"))
        assert decoded[0, 0, 3] == 0                 # transparent background in the GIF
        assert (decoded[..., 3] == 255).sum() > 100  # sprite present




def test_cut_frames_aligns_ink_bottom_to_ground_line(tmp_path):
    """Frames whose ink bottom sits at different depths inside their box must
    still land their feet on the same ground line (no vertical jumping)."""
    from gifkit import cli
    module = cli.load_builder("make_gif.py")
    rgba = np.full((120, 200, 4), 255, np.uint8)
    rgba[..., 3] = 0
    # cell A: ink bottom 30px above its box bottom; cell B: 2px above
    rgba[20:90, 10:90, :3] = (40, 90, 160); rgba[20:90, 10:90, 3] = 255
    rgba[20:118, 110:190, :3] = (160, 90, 40); rgba[20:118, 110:190, 3] = 255
    boxes = {(0, 0): [0, 0, 100, 120], (0, 1): [100, 0, 200, 120]}
    frames = module.cut_frames(rgba.astype(np.float32) / 255.0, boxes, [1, 2],
                               [140, 120], baseline=100, oversize_policy="clamp")
    bottoms = []
    for f in frames:
        ys, _xs = np.nonzero(f[..., 3] >= 128 / 255.0)
        bottoms.append(int(ys.max()))
    assert bottoms[0] == bottoms[1] == 100  # both feet on the ground line



def test_canvas_dimensions_are_width_height(tmp_path):
    """The built frame must be exactly (canvas_width, canvas_height) — an
    unpacking swap (ch, cw = canvas) silently transposes the canvas and cuts
    the character off at the bottom edge."""
    from gifkit import cli
    module = cli.load_builder("make_gif.py")
    rgba = np.full((200, 300, 4), 255, np.uint8)
    rgba[..., 3] = 0
    rgba[20:190, 20:280, :3] = (40, 90, 160)
    rgba[20:190, 20:280, 3] = 255
    boxes = {(0, 0): [0, 0, 300, 200]}
    frames = module.cut_frames(rgba.astype(np.float32) / 255.0, boxes, [1, 1],
                               [120, 240], baseline=230, oversize_policy="clamp")
    img = Image.fromarray((np.clip(frames[0], 0, 1) * 255).round().astype(np.uint8), "RGBA")
    assert img.size == (120, 240)          # (width, height), not transposed
    ys, _xs = np.nonzero(frames[0][..., 3] >= 0.5)
    assert int(ys.max()) == 230            # feet on the ground line, body intact

def test_prepare_output_dir_uses_empty_and_nests_nonempty(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert Path(gui.prepare_output_dir(str(empty))) == empty.resolve()

    full = tmp_path / "full"
    full.mkdir()
    (full / "user-file.txt").write_text("keep me", encoding="utf-8")
    nested = Path(gui.prepare_output_dir(str(full)))
    assert nested.is_dir() and nested != full
    assert nested.parent == full.resolve()
    assert (full / "user-file.txt").read_text(encoding="utf-8") == "keep me"


def test_default_output_dir_is_a_path():
    assert Path(gui.default_output_dir())


def test_tk_app_smoke():
    try:
        import tkinter as tk
        root = tk.Tk()
    except Exception as exc:  # headless environment
        pytest.skip("no display for Tk: %s" % exc)
    try:
        app = gui.App(root)
        root.update()
        assert app.sheet_build_button is not None
        assert app.log is not None
    finally:
        root.destroy()
