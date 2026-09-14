"""Tests for the gifkit CLI package and pyproject metadata (phase 2, step 4).

The dispatch test runs the real bundled v1 build into a temporary directory;
everything else is metadata and error-path checking.
"""
import importlib
import json
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gifkit import __version__, cli  # noqa: E402

PYPROJECT = ROOT / "pyproject.toml"


def test_pyproject_metadata():
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = data["project"]
    assert project["name"] == "gifkit"
    assert project["version"] == __version__   # keep pyproject in sync with the package
    deps = {d.split("[")[0].lower() for d in project["dependencies"]}
    assert {"numpy", "pillow", "scipy", "scikit-image"} <= deps
    assert project["scripts"]["gifkit"] == "gifkit.cli:main"
    assert project["requires-python"] == ">=3.10"
    floor = tuple(int(x) for x in project["requires-python"].lstrip(">=").split(".")[:2])
    assert (3, sys.version_info.minor) >= floor


def test_bundled_cases_declare_existing_builders():
    for name, cfg in cli.list_cases():
        assert cfg.get("builder"), name
        assert (ROOT / cfg["builder"]).is_file(), (name, cfg["builder"])


def test_cli_version_and_help(capsys):
    assert cli.main(["--version"]) == 0
    assert __version__ in capsys.readouterr().out
    assert cli.main([]) == 0
    assert "build" in capsys.readouterr().out


def test_frozen_no_args_launches_gui(monkeypatch):
    """Double-clicking the packed exe passes no arguments — it must open the
    GUI instead of printing help (which is invisible in a windowed app)."""
    calls = []
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(ROOT), raising=False)

    def fake_gui():
        calls.append(1)
        return 0

    monkeypatch.setattr("gifkit.gui.run_gui", fake_gui)
    assert cli.main([]) == 0
    assert calls == [1]
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert cli.main([]) == 0  # dev mode still prints usage


def test_cli_cases_listing(capsys):
    assert cli.main(["cases"]) == 0
    out = capsys.readouterr().out
    for name in ("mimo_v1", "mimo_v2_key", "mimo_v2_24fps", "mimo_v3", "mimo_v4"):
        assert name in out, name


MIMO_LOCAL = (ROOT / "mimo.png").is_file()  # the Mimo imagery is not distributed


def test_cli_build_dispatch_runs_bundled_v1(tmp_path, capsys):
    if not MIMO_LOCAL:
        pytest.skip("Mimo material not present in this checkout")
    out = tmp_path / "v1out"
    assert cli.main(["build", "--case", "mimo_v1", "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "New output directory" in text
    for name in ("mimo_loop.gif", "mimo_loop_transparent.gif"):
        assert (out / name).is_file(), name


def test_cli_build_rejects_unknown_case_and_bad_config(tmp_path):
    with pytest.raises(SystemExit, match="unknown case"):
        cli.main(["build", "--case", "nope"])
    with pytest.raises(SystemExit, match="not found"):
        cli.main(["build", "--config", str(tmp_path / "missing.json")])
    with pytest.raises(SystemExit, match="either --case or --config"):
        cli.main(["build", "--case", "mimo_v1", "--config", str(tmp_path / "x.json")])
    bare = tmp_path / "bare.json"
    bare.write_text(json.dumps({"case": "no_builder_here"}), encoding="utf-8")
    with pytest.raises(SystemExit, match="builder"):
        cli.main(["build", "--config", str(bare)])


def test_cli_config_only_usage_builds(tmp_path):
    """--config (without --case) drives the build end-to-end; the CLI appends the
    resolved path to the builder's argv so the builder's bundled default can
    never silently override the user's choice."""
    if not MIMO_LOCAL:
        pytest.skip("Mimo material not present in this checkout")
    out = tmp_path / "out"
    assert cli.main(["build", "--config", str(ROOT / "cases" / "mimo_v1.json"),
                     "--out", str(out)]) == 0
    assert (out / "mimo_loop.gif").is_file()


def test_cli_load_builder_makes_morph_importable():
    module = cli.load_builder("v2/build_gifs.py")
    assert hasattr(module, "main")
    assert "v2" in sys.path or str(ROOT / "v2") in sys.path
