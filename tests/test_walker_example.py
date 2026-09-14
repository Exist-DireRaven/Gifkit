"""The walker example: a synthetic second case, nothing like Mimo."""
import importlib.util
import json
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent


def load_generator():
    spec = importlib.util.spec_from_file_location("gifkit_walker_gen",
                                                  ROOT / "examples" / "walker" / "make_material.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_walker_material_is_generated_and_valid(tmp_path):
    gen = load_generator()
    gen.main(["--out-dir", str(tmp_path)])

    sheet = Image.open(tmp_path / "walker_sheet.png")
    assert sheet.size == (480, 640) and sheet.mode == "RGBA"
    boxes = json.loads((tmp_path / "boxes.json").read_text(encoding="utf-8"))
    assert len(boxes) == 12  # 3x4 grid, not Mimo's 4x4
    tiles = sorted((tmp_path / "tiles").glob("pair_*.png"))
    assert len(tiles) == 16  # 2 blocks x 8
    first = Image.open(tiles[0])
    assert first.size == (192, 144) and first.mode == "RGB"  # white background, no alpha


def test_walker_cases_exist_and_point_at_material():
    for name in ("walker_grid", "walker_loop"):
        cfg = json.loads((ROOT / "cases" / (name + ".json")).read_text(encoding="utf-8"))
        assert cfg["builder"]
        assert (ROOT / cfg["builder"]).is_file()
    grid = json.loads((ROOT / "cases" / "walker_grid.json").read_text(encoding="utf-8"))
    base = ROOT / "cases"
    if not (base / grid["source"]).is_file():
        pytest.skip("walker material not generated; run examples/walker/make_material.py")
    assert (base / grid["boxes_file"]).is_file()
