"""Case-config tests (phase 2, step 3).

The bundled cases/mimo_v*.json files must stay valid, and the builders must
run end-to-end on *synthetic* material driven purely by a config file —
that is the "swap material without touching the algorithm" acceptance test.
No historical Mimo output is written: synthetic runs go to tmp_path.
"""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "cases"

REQUIRED_KEYS = {
    "mimo_v1.json": ("source", "boxes_file", "grid", "canvas", "baseline", "duration_ms"),
    "mimo_v2_key.json": ("frames_dir", "pattern", "count", "canvas", "plan"),
    "mimo_v2_24fps.json": ("frames_dir", "pattern", "count", "canvas", "fps", "nb", "hold", "outputs"),
    "mimo_v3.json": ("aligned_dir", "frames_per_block", "canvas", "fps", "nb", "sequences"),
    "mimo_v4.json": ("tiles_dir", "blocks", "canvas", "baseline", "target_height", "holds_ms"),
}


def load_builder(relative, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("filename", sorted(REQUIRED_KEYS))
def test_bundled_cases_are_valid(filename):
    cfg = json.loads((CASES / filename).read_text(encoding="utf-8"))
    for key in REQUIRED_KEYS[filename]:
        assert key in cfg, (filename, key)
    base = CASES
    for key in ("source", "boxes_file", "frames_dir", "aligned_dir", "tiles_dir"):
        if key in cfg:
            path = (base / cfg[key]).resolve()
            if not path.exists():
                # the Mimo imagery is not distributed; walker material is generated
                pytest.skip("local material not present (%s: %s); run make_material.py or "
                            "use a full working copy" % (filename, key))


def test_v1_build_runs_on_synthetic_material(tmp_path):
    """Swap in a synthetic 4x4 sheet: the whole v1 build runs from config alone."""
    # synthetic sheet: 4x4 grid of 128px cells, each holding one coloured blob
    cell, sheet_px = 128, 512
    sheet = Image.new("RGBA", (sheet_px, sheet_px), (0, 0, 0, 0))
    boxes = {}
    for r in range(4):
        for c in range(4):
            x0, y0 = c * cell + 24, r * cell + 30
            sprite = Image.new("RGBA", (64, 70), (0, 0, 0, 0))
            arr = np.zeros((70, 64, 4), np.uint8)
            arr[10:60, 8:56, 0] = 40 + 40 * r
            arr[10:60, 8:56, 1] = 40 + 40 * c
            arr[10:60, 8:56, 2] = 200
            arr[10:60, 8:56, 3] = 255
            sprite = Image.fromarray(arr, "RGBA")
            sheet.alpha_composite(sprite, (x0, y0))
            boxes["%d,%d" % (r, c)] = [x0, y0, x0 + 64, y0 + 70]
    source = tmp_path / "synth.png"
    sheet.save(source)
    boxes_file = tmp_path / "boxes.json"
    boxes_file.write_text(json.dumps(boxes), encoding="utf-8")

    config = tmp_path / "synth_case.json"
    config.write_text(json.dumps({
        "case": "synth_v1", "source": "synth.png", "boxes_file": "boxes.json",
        "output_stem": "synth", "grid": [4, 4], "canvas": [96, 96], "baseline": 88,
        "duration_ms": 40, "alpha_solid": 128, "small_size": [48, 48],
        "oversize_policy": "clamp", "run_prefix": "synth-",
    }), encoding="utf-8")

    module = load_builder("make_gif.py", "gifkit_cfg_v1")
    out = tmp_path / "out"
    module.main(["--config", str(config), "--out", str(out)])

    for name in ("synth.gif", "synth_transparent.gif", "synth_small.gif", "synth_small_white.gif"):
        assert (out / name).is_file(), name
    assert len(list((out / "frames").glob("*.png"))) == 16
    with Image.open(out / "synth.gif") as gif:
        gif.seek(15)
        assert gif.size == (96, 96)


def test_v1_material_policies(tmp_path):
    module = load_builder("make_gif.py", "gifkit_cfg_v1_policy")
    rgba = np.zeros((64, 64, 4), np.float32)
    rgba[..., :3] = 0.5
    rgba[..., 3] = 1.0
    boxes = {(r, c): [c * 16, r * 16, c * 16 + 14, r * 16 + 14] for r in range(4) for c in range(4)}

    # missing cell -> clear error
    broken = dict(boxes)
    del broken[(2, 3)]
    with pytest.raises(SystemExit, match="r3c4"):
        module.cut_frames(rgba, broken, [4, 4], [96, 96], 88, "clamp")

    # oversize with policy=error -> error; with clamp -> cropped placement succeeds
    big = {k: [2, 2, 62, 62] for k in boxes}
    with pytest.raises(SystemExit, match="oversize_policy=error"):
        module.cut_frames(rgba, big, [4, 4], [40, 40], 38, "error")
    frames = module.cut_frames(rgba, big, [4, 4], [40, 40], 38, "clamp")
    assert len(frames) == 16

    # fully transparent cell -> error
    empty = np.zeros_like(rgba)
    with pytest.raises(SystemExit, match="fully transparent"):
        module.cut_frames(empty, boxes, [4, 4], [96, 96], 88, "clamp")


def test_v2_build_runs_on_synthetic_material(tmp_path, monkeypatch):
    """Swap in 3 synthetic keyframes: the v2 key/smooth build runs from config alone."""
    import morph  # the real module the builder will import (v2/ on sys.path via conftest)
    monkeypatch.setattr(morph, "CACHE", str(tmp_path / "flow-cache"))

    frames_dir = tmp_path / "keys"
    frames_dir.mkdir()
    for k in range(1, 4):
        arr = np.zeros((48, 48, 4), np.uint8)
        x0 = 6 + (k - 1) * 4
        arr[12:40, x0:x0 + 20, 0] = 220
        arr[12:40, x0:x0 + 20, 2] = 90
        arr[12:40, x0:x0 + 20, 3] = 255
        Image.fromarray(arr, "RGBA").save(frames_dir / ("key_%02d.png" % k))

    config = tmp_path / "synth_v2.json"
    config.write_text(json.dumps({
        "case": "synth_v2", "output_stem": "synth2",
        "frames_dir": str(frames_dir), "pattern": "key_%02d.png", "count": 3,
        "canvas": [64, 64], "small_size": [32, 32], "alpha_solid": 128,
        "plan": {"1": [40, []], "2": [40, [[0.5, "A", 30]]], "3": [40, [[0.5, "B", 30]]]},
        "run_prefix": "synth2-",
    }), encoding="utf-8")

    module = load_builder("v2/build_gifs.py", "gifkit_cfg_v2")
    out = tmp_path / "out"
    module.main(["--config", str(config), "--out", str(out)])

    for name in ("synth2_key.gif", "synth2_smooth.gif", "synth2_key_transparent.gif",
                 "synth2_smooth_transparent.gif", "synth2_smooth_small.gif", "_plan.json"):
        assert (out / name).is_file(), name
    plan = json.loads((out / "_plan.json").read_text(encoding="utf-8"))
    assert set(plan) == {"1", "2", "3"}
    # the smooth cut has key+key+key + 2 in-betweens = 5 frames
    with Image.open(out / "synth2_smooth.gif") as gif:
        assert gif.n_frames == 5


def test_v2_rejects_plan_count_mismatch_and_empty_frame(tmp_path):
    module = load_builder("v2/build_gifs.py", "gifkit_cfg_v2_policy")
    frames_dir = tmp_path / "keys"
    frames_dir.mkdir()
    for k in range(1, 4):
        arr = np.zeros((24, 24, 4), np.uint8)
        arr[4:20, 4:20, 3] = 255
        Image.fromarray(arr, "RGBA").save(frames_dir / ("key_%02d.png" % k))
    # plan missing transition 3
    with pytest.raises(SystemExit, match="missing transitions"):
        module.main(["--config", str(_write_case(tmp_path, frames_dir, count=3, plan_keys=("1", "2"))),
                     "--out", str(tmp_path / "o1")])
    # key 2 fully transparent
    transparent = np.zeros((24, 24, 4), np.uint8)
    Image.fromarray(transparent, "RGBA").save(frames_dir / "key_02.png")
    with pytest.raises(SystemExit, match="no opaque pixels"):
        module.main(["--config", str(_write_case(tmp_path, frames_dir, count=3, plan_keys=("1", "2", "3"))),
                     "--out", str(tmp_path / "o2")])


def _write_case(tmp_path, frames_dir, count, plan_keys):
    plan = {k: [40, []] for k in plan_keys}
    config = tmp_path / ("case_%s.json" % "_".join(plan_keys))
    config.write_text(json.dumps({
        "frames_dir": str(frames_dir), "pattern": "key_%02d.png", "count": count,
        "canvas": [48, 48], "plan": plan,
    }), encoding="utf-8")
    return config
