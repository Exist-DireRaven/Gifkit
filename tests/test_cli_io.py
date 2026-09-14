"""CLI wiring tests for the verification/analysis entry points (phase 2, step 1).

Everything runs on synthetic tiny inputs in temporary directories; the
historical Mimo assets are never read or written.  The morph-dependent
scripts are loaded with a stub "morph" module in sys.modules so no flow
cache is touched and no heavy computation runs.
"""
import importlib.util
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent

# Verification/analysis entry points (phase 2 step 1), the five build
# entries (step 2) and the twelve one-off prep/diagnostic tools (step 3):
# importing any of them must do nothing at all.
ENTRY_SCRIPTS = ["verify.py", "v2/verify_gifs.py", "v2/verify_24.py", "v2/check_quality.py",
                 "v2/analyze_continuity.py", "v2/evaluate_schemes.py", "v3/verify_v3.py",
                 "v3/check_frames.py", "v3/diag_seq.py",
                 "make_gif.py", "v2/build_gifs.py", "v2/build_24fps.py",
                 "v3/build_gifs_v3.py", "v3/build_melee_v4.py",
                 "segment.py", "build_frames.py",
                 "v2/segment.py", "v2/align.py", "v2/strip24.py", "v2/export_key02_11.py",
                 "v2/make_chart.py", "v2/export_crops.py",
                 "v3/build_v3.py", "v3/extract_all.py", "v3/locate_sprites.py", "v3/strip_blocks.py"]


def load_script(relative, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_morph_stub(n=2, size=24):
    stub = types.ModuleType("morph")
    stub.N = n
    stub.FRAMES = "stub-frames"
    keys = []
    for k in range(n):
        key = np.zeros((size, size, 4), np.float32)
        key[4 + k:12 + k, 4:16, 0] = 1.0
        key[4 + k:12 + k, 4:16, 3] = 1.0
        keys.append(key)
    stub.load_key = lambda i, frames_dir=None, pattern="key_%02d.png": keys[i - 1].copy()
    stub.get_flow = lambda i, j, cache=True, frames_dir=None, pattern="key_%02d.png": (
        np.zeros((size, size, 2), np.float32), np.zeros((size, size, 2), np.float32))
    stub.warp_premult = lambda f, disp: f.copy()
    stub.crisp_alpha = lambda f: f
    return stub


def make_gif(tmp_path, name="tiny.gif", n=3, size=16):
    colors = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 0, 255)]
    frames = [Image.new("RGBA", (size, size), colors[k % len(colors)]) for k in range(n)]
    path = tmp_path / name
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=40, loop=0)
    return path


def test_verify_root_cli(tmp_path):
    module = load_script("verify.py", "gifkit_verify_root")
    gif = make_gif(tmp_path)
    module.main([str(gif)])
    assert (tmp_path / "_check_tiny.png").is_file()
    outdir = tmp_path / "montages"
    module.main([str(gif), "--outdir", str(outdir), "--cols", "2", "--bg", "white", "--scale", "0.5"])
    assert (outdir / "_check_tiny.png").is_file()


def test_verify_root_cli_rejects_missing_input(tmp_path):
    module = load_script("verify.py", "gifkit_verify_root_missing")
    with pytest.raises(SystemExit):
        module.main([str(tmp_path / "nope.gif")])


@pytest.mark.parametrize("relative,name", [("v2/verify_gifs.py", "gifkit_verify_gifs"),
                                           ("v3/verify_v3.py", "gifkit_verify_v3")])
def test_gif_verifiers_cli(relative, name, tmp_path):
    module = load_script(relative, name)
    gif = make_gif(tmp_path, "seq.gif", n=4, size=32)
    module.main([str(gif)])
    assert (tmp_path / "_check_seq.png").is_file()


def test_diag_seq_cli(tmp_path):
    module = load_script("v3/diag_seq.py", "gifkit_diag_seq")
    seq = tmp_path / "seq"
    seq.mkdir()
    for k in range(3):
        arr = np.zeros((32, 32, 4), np.uint8)
        arr[8:20, 6 + 2 * k:14 + 2 * k, :3] = 200
        arr[8:20, 6 + 2 * k:14 + 2 * k, 3] = 255
        Image.fromarray(arr, "RGBA").save(seq / ("%02d.png" % (k + 1)))
    json_out = tmp_path / "diag.json"
    module.main([str(seq), "--json-out", str(json_out)])
    data = json.loads(json_out.read_text(encoding="utf-8"))
    assert len(data["rows"]) == 3
    assert len(data["steps"]["steps"]) == 2
    with pytest.raises(SystemExit):
        module.main([str(tmp_path / "missing-folder")])
    for k in range(1, 4):
        (seq / ("%02d.png" % k)).unlink()
    with pytest.raises(SystemExit):
        module.main([str(seq)])  # folder without PNGs


def test_analyze_continuity_cli(tmp_path):
    module = load_script("v2/analyze_continuity.py", "gifkit_analyze_cont")
    frames_dir = tmp_path / "frames_key"
    frames_dir.mkdir()
    for k in range(1, 5):
        arr = np.zeros((32, 32, 4), np.uint8)
        x0 = 4 + (k - 1) * 2
        arr[8:24, x0:x0 + 12, :3] = (200, 60, 60)
        arr[8:24, x0:x0 + 12, 3] = 255
        Image.fromarray(arr, "RGBA").save(frames_dir / ("key_%02d.png" % k))
    json_out = tmp_path / "cont.json"
    module.main(["--frames-dir", str(frames_dir), "--count", "4", "--json-out", str(json_out)])
    rows = json.loads(json_out.read_text(encoding="utf-8"))
    assert len(rows) == 4
    assert 0.0 < rows[0]["iou"] <= 1.0


def test_check_frames_cli(tmp_path):
    module = load_script("v3/check_frames.py", "gifkit_check_frames")
    tiles = tmp_path / "tiles"
    tiles.mkdir()

    def save(prefix, k):
        arr = np.full((24, 24), 250, np.uint8)
        ink = ((np.add.outer(np.arange(24), np.arange(24)) * 13 + k * 29) % 180).astype(np.uint8)
        arr[4:16, 4:16] = ink[4:16, 4:16]
        Image.fromarray(arr, "L").save(tiles / ("%s_%02d.png" % (prefix, k)))

    for k in range(1, 3):
        save("full", k)
    for k in range(1, 4):
        save("pair", k)
    json_out = tmp_path / "match.json"
    module.main(["--tiles-dir", str(tiles), "--full-count", "2", "--pair-count", "3",
                 "--json-out", str(json_out)])
    data = json.loads(json_out.read_text(encoding="utf-8"))
    assert len(data["match"]) == 3


def test_verify_24_cli_skips_palette_without_plan(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "morph", make_morph_stub())
    module = load_script("v2/verify_24.py", "gifkit_verify_24")
    gif = make_gif(tmp_path, "anim.gif", n=4, size=24)
    module.main(["--gif", str(gif), "--plan", str(tmp_path / "missing_plan.json")])
    assert (tmp_path / "_check_anim.png").is_file()
    assert not list(tmp_path.glob("_pal_test_*.gif"))


def test_verify_24_cli_palette_experiment_with_stub(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "morph", make_morph_stub(n=2))
    module = load_script("v2/verify_24.py", "gifkit_verify_24_exp")
    gif = make_gif(tmp_path, "anim24.gif", n=4, size=24)
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"labels": ["a", "b"], "NB": {"1": 1, "2": 1}}), encoding="utf-8")
    module.main(["--gif", str(gif), "--plan", str(plan)])
    assert (tmp_path / "_check_anim24.png").is_file()
    assert not list(tmp_path.glob("_pal_test_*.gif"))  # experiment temp files are cleaned up


def test_check_quality_cli_with_stub(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "morph", make_morph_stub(n=4))
    module = load_script("v2/check_quality.py", "gifkit_check_quality")
    gif = make_gif(tmp_path, "key.gif", n=1, size=24)
    module.main(["--gif", str(gif), "--transitions", "1,2", "3,4",
                 "--count", "4", "--outdir", str(tmp_path)])
    assert (tmp_path / "_strip_hard_01_02.png").is_file()
    assert (tmp_path / "_strip_hard_03_04.png").is_file()


def test_evaluate_schemes_cli_with_stub(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "morph", make_morph_stub(n=3))
    module = load_script("v2/evaluate_schemes.py", "gifkit_eval_schemes")
    json_out = tmp_path / "schemes.json"
    module.main(["--count", "3", "--json-out", str(json_out)])
    data = json.loads(json_out.read_text(encoding="utf-8"))
    assert len(data) == 3
    assert data[0]["best"] in ("s0", "s1a", "s1b", "s2a", "s2b", "s3")


@pytest.mark.parametrize("relative", ENTRY_SCRIPTS)
def test_entry_scripts_import_without_side_effects(relative, tmp_path, monkeypatch):
    source = (ROOT / relative).read_text(encoding="utf-8-sig")
    if relative == "v2/make_chart.py":
        # matplotlib is an optional dev-only dep (not in pyproject, excluded
        # from the frozen build); the import test runs wherever it's installed
        pytest.importorskip("matplotlib", reason="make_chart needs optional matplotlib")
    if "import morph" in source:
        monkeypatch.setitem(sys.modules, "morph", make_morph_stub())
    monkeypatch.chdir(tmp_path)
    script_dir = (ROOT / relative).parent
    snapshot = lambda: {p.name: p.stat().st_size for p in script_dir.iterdir()
                        if p.is_file() and not p.name.startswith("__")}
    before = snapshot()
    name = "gifkit_sideeffect_" + relative.replace("/", "_").replace(".", "_")
    module = load_script(relative, name)
    assert callable(module.main)
    assert snapshot() == before  # importing must not create, modify or delete anything


def test_morph_load_key_and_get_flow_honour_frames_dir(tmp_path):
    spec = importlib.util.spec_from_file_location("gifkit_morph_frames", ROOT / "v2" / "morph.py")
    morph = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(morph)
    frames_dir = tmp_path / "keys"
    frames_dir.mkdir()
    arr = np.zeros((12, 12, 4), np.uint8)
    arr[2:10, 2:10, 3] = 255
    Image.fromarray(arr, "RGBA").save(frames_dir / "key_03.png")
    key = morph.load_key(3, frames_dir=str(frames_dir))
    assert key.shape == (12, 12, 4)
    assert key[4, 4, 3] == 1.0
    cache_dir = tmp_path / "cache"
    morph.CACHE = str(cache_dir)
    d_ab, d_ba = morph.get_flow(3, 3, frames_dir=str(frames_dir))
    assert d_ab.shape == (12, 12, 2) and d_ba.shape == (12, 12, 2)
    assert list(cache_dir.glob("*.npz"))  # cache went to the patched dir, not v2/
