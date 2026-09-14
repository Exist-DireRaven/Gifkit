"""GifKit command line interface (minimal build entry).

Usage:
  gifkit --version
  gifkit cases                                  # list the bundled cases
  gifkit build --case mimo_v4 [--out DIR]       # build a bundled case
  gifkit build --config my.json --out DIR       # build from any case config

The build subcommand dispatches to the builder script named by the case
config's "builder" field and passes all remaining options through to it
(--out, --frames-dir, --tiles-dir, --no-tween-pngs, ...).

This CLI is designed for an EDITABLE install from the repository
(pip install -e <repo>): it loads the builder scripts and cases/ from the
repository tree next to the installed package.  A non-editable install is
not supported and fails with a clear message.
"""
import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

from . import __version__

if getattr(sys, "frozen", False):  # PyInstaller bundle: scripts/cases ride along as data
    meipass = getattr(sys, "_MEIPASS", None)
    PROJECT_ROOT = Path(meipass) if meipass else Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = PROJECT_ROOT / "cases"


def _ensure_repo_layout():
    if not (CASES_DIR.is_dir() and (PROJECT_ROOT / "make_gif.py").is_file()):
        raise SystemExit(
            "gifkit is installed without the repository tree next to it.\n"
            "Install editable from the repository instead:\n"
            "  pip install -e <path-to-repo>")


def load_builder(builder_rel):
    """Load a builder script from the repository tree; make its imports work."""
    path = PROJECT_ROOT / builder_rel
    if not path.is_file():
        raise SystemExit("builder script not found: %s" % path)
    script_dir = str(path.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    name = "gifkit_builder_" + re.sub(r"[^0-9A-Za-z_]", "_", builder_rel)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def list_cases():
    """Return (name, config) for every bundled case, sorted by name."""
    out = []
    for path in sorted(CASES_DIR.glob("*.json")):
        with open(path, encoding="utf-8") as handle:
            out.append((path.stem, json.load(handle)))
    return out


def _extract(args, flags):
    """Remove --flag value / --flag=value / --flag (bool) tokens from args."""
    rest, picked, i = [], None, 0
    while i < len(args):
        token = args[i]
        matched = None
        for flag in flags:
            if token == flag:
                matched = ("space", flag)
            elif token.startswith(flag + "="):
                matched = ("eq", flag)
        if matched:
            kind, flag = matched
            if kind == "eq":
                picked = token.split("=", 1)[1]
                i += 1
            else:
                picked = args[i + 1] if i + 1 < len(args) else None
                i += 2
        else:
            rest.append(token)
            i += 1
    return rest, picked


def cmd_build(tail):
    parser = argparse.ArgumentParser(prog="gifkit build", add_help=False,
                                     description="Build a case via its builder script.")
    known, rest = parser.parse_known_args(tail)
    rest, case = _extract(rest, ("--case",))
    rest, config = _extract(rest, ("--config",))

    if case and config:
        raise SystemExit("pass either --case or --config, not both")
    if config is None:
        if case is None:
            names = ", ".join(name for name, _ in list_cases())
            raise SystemExit("choose a case with --case NAME (bundled: %s) or pass --config PATH" % names)
        config = CASES_DIR / (case + ".json")
        if not config.is_file():
            raise SystemExit("unknown case %r; bundled cases: %s"
                             % (case, ", ".join(name for name, _ in list_cases())))
    if not Path(config).is_file():
        raise SystemExit("case config not found: %s" % config)

    with open(config, encoding="utf-8") as handle:
        cfg = json.load(handle)
    builder = cfg.get("builder")
    if not builder:
        raise SystemExit("case config has no \"builder\" field: %s" % config)

    # the resolved config wins: append it last so any stray --config in the
    # passthrough arguments is overridden rather than silently ignored
    module = load_builder(builder)
    module.main(rest + ["--config", str(Path(config).resolve())])
    return 0


def cmd_cases():
    rows = list_cases()
    for name, cfg in rows:
        print("%-16s builder=%-24s %s" % (name, cfg.get("builder", "?"), cfg.get("comment", "")))
    return 0


USAGE = """usage: gifkit <command> [options]

commands:
  build    build a case:  gifkit build --case mimo_v4 [--out DIR]
           or any config: gifkit build --config my.json [--out DIR]
           unknown options are passed through to the builder script
  cases    list the bundled cases
  gui      open the point-and-click window

options:
  -h, --help     show this help
  --version      show the version
"""


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if getattr(sys, "frozen", False) and not args:
        args = ["gui"]      # double-clicking the packed exe must open the window
    if not args or args[0] in ("-h", "--help"):
        print(USAGE, end="")
        return 0
    if args[0] == "--version":
        print("gifkit " + __version__)
        return 0

    _ensure_repo_layout()
    command, tail = args[0], args[1:]
    if command == "build":
        return cmd_build(tail)
    if command == "cases":
        return cmd_cases()
    if command == "gui":
        from .gui import run_gui
        return run_gui()
    raise SystemExit("unknown command %r; expected 'build', 'cases' or 'gui' (see: gifkit --help)" % command)


if __name__ == "__main__":
    sys.exit(main())
