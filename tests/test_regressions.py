"""Focused regression tests; never rebuild the Mimo animations.

The build entry points are import-safe (no top-level work), so the palette
round-trip and output-setup tests load the real modules and call their
functions directly on synthetic input.
"""
import ast
import importlib.util
import os
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
BUILDERS = ("make_gif.py", "v2/build_gifs.py", "v2/build_24fps.py", "v3/build_gifs_v3.py", "v3/build_melee_v4.py")


def load_module(relative, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _roundtrip_rgba():
    """8x8 RGBA test frame: three solid colour bars + one transparent column."""
    rgba = np.zeros((8, 8, 4), dtype=np.float32)
    rgba[:, :3] = (1, 0, 0, 1)
    rgba[:, 3:5] = (0, 1, 0, 1)
    rgba[:, 5:7] = (0, 0, 1, 1)
    rgba[:, 7] = (0, 0, 0, 0)
    return rgba


@pytest.mark.parametrize("relative", BUILDERS)
@pytest.mark.parametrize("transparent", (False, True))
def test_palette_roundtrip(relative, transparent, tmp_path):
    rgba = _roundtrip_rgba()
    rgb = (rgba[..., :3] * rgba[..., 3:4] + 1 - rgba[..., 3:4])
    reference = Image.fromarray((rgb * 255).round().astype(np.uint8))
    palette = reference.quantize(colors=254, dither=Image.Dither.NONE)
    expected = np.asarray(reference.quantize(palette=palette, dither=Image.NONE).convert("RGB"))

    name = "gifkit_builder_" + relative.replace("/", "_").replace(".", "_")
    module = load_module(relative, name)
    target = tmp_path / "roundtrip.gif"
    seq = [(rgba, 40, "test")]
    if relative == "v3/build_gifs_v3.py":
        module.save("roundtrip.gif", seq, palette, transparent, out_dir=str(tmp_path))
    elif relative == "v3/build_melee_v4.py":
        module.save_gif("roundtrip.gif", seq, [40], palette, str(tmp_path), transparent)
    else:
        argument = seq if relative.endswith("build_gifs.py") else [rgba]
        frames = module.to_p(argument, transparent, palette)
        options = dict(format="GIF", optimize=False, duration=40)
        if transparent:
            options.update(transparency=0, disposal=2)
        frames[0].save(target, **options)
    with Image.open(target) as result:
        decoded = np.asarray(result.convert("RGBA"))
        assert result.info.get("duration") == 40
    solid = rgba[..., 3] >= 0.5
    np.testing.assert_array_equal(decoded[..., :3][solid], expected[solid])
    assert np.all(decoded[..., 3][solid] == 255)
    assert np.all(decoded[..., 3][~solid] == (0 if transparent else 255))


@pytest.fixture
def morph(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("gifkit_morph_test", ROOT / "v2" / "morph.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "CACHE", str(tmp_path / "cache"))
    return module


def test_cache_hit_change_corruption_and_disabled(morph, tmp_path, monkeypatch):
    frames = {1: np.zeros((8, 8, 4), np.float32), 2: np.ones((8, 8, 4), np.float32)}
    calls = []
    def backend(a, b):
        calls.append(1)
        return np.zeros(a.shape + (2,), np.float32), np.zeros(b.shape + (2,), np.float32)
    monkeypatch.setattr(morph, "load_key", lambda i, frames_dir=None, pattern="key_%02d.png": frames[i].copy())
    monkeypatch.setattr(morph, "_flow_pair", backend)
    morph.get_flow(1, 2)
    morph.get_flow(1, 2)
    assert len(calls) == 1
    frames[1][0, 0, 3] = 0.5
    morph.get_flow(1, 2)
    assert len(calls) == 2
    cached = tuple(Path(morph.CACHE).glob("*.npz"))
    assert len(cached) == 2
    for path in cached:
        path.write_bytes(b"broken cache")
    morph.get_flow(1, 2)
    assert len(calls) == 3
    monkeypatch.setattr(morph, "CACHE", str(tmp_path / "disabled"))
    morph.get_flow(1, 2, cache=False)
    assert len(calls) == 4
    assert not Path(morph.CACHE).exists()


def test_cache_backend_change(morph, monkeypatch):
    frame = np.zeros((4, 4, 4), np.float32)
    def first(a, b):
        return np.zeros(a.shape + (2,), np.float32), np.zeros(b.shape + (2,), np.float32)
    def second(a, b):
        return np.ones(a.shape + (2,), np.float32), np.ones(b.shape + (2,), np.float32)
    monkeypatch.setattr(morph, "load_key", lambda i, frames_dir=None, pattern="key_%02d.png": frame.copy())
    monkeypatch.setattr(morph, "_flow_pair", first)
    morph.get_flow(1, 2)
    monkeypatch.setattr(morph, "_flow_pair", second)
    forward, backward = morph.get_flow(1, 2)
    assert np.all(forward == 1)
    assert np.all(backward == 1)


def test_all_scripts_compile_and_no_old_paths():
    paths = list(ROOT.glob("*.py")) + list((ROOT / "v2").glob("*.py")) + list((ROOT / "v3").glob("*.py"))
    assert len(paths) >= 27
    for path in paths:
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        compile(tree, str(path), "exec")
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "D:" + chr(92) + "MimoGif" not in node.value, str(path)


def test_morph_import_has_no_mkdir(tmp_path, monkeypatch):
    copied = tmp_path / "morph.py"
    shutil.copyfile(ROOT / "v2" / "morph.py", copied)
    monkeypatch.chdir(tmp_path)
    spec = importlib.util.spec_from_file_location("isolated_morph", copied)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert Path(module.OUT) == tmp_path
    assert not (tmp_path / "_flow_cache").exists()


def test_v4_output_setup_preserves_existing_files(tmp_path):
    """A fresh melee-v4 run directory must not delete pre-existing seq_melee_v4 content."""
    module = load_module("v3/build_melee_v4.py", "gifkit_builder_v4_setup")
    sentinel = tmp_path / "seq_melee_v4" / "keep.txt"
    sentinel.parent.mkdir()
    sentinel.write_text("user data", encoding="utf-8")
    cfg = {"run_prefix": "v4test-"}
    first_run, first_seq = module.open_run_dir(tmp_path, cfg, str(tmp_path / "one"))
    second_run, second_seq = module.open_run_dir(tmp_path, cfg, str(tmp_path / "two"))
    assert first_run != second_run
    assert Path(first_seq).is_dir()
    assert Path(second_seq).is_dir()
    assert sentinel.read_text(encoding="utf-8") == "user data"
    with pytest.raises(SystemExit, match="not empty"):
        module.open_run_dir(tmp_path, cfg, str(tmp_path / "one"))
