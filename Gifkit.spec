# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Gifkit GUI (one-folder build, no console).

The builders and case configs are bundled as data files and loaded at
runtime (gifkit.cli.load_builder adds their folder to sys.path), so the
analysis only needs the static imports of the CLI/GUI itself — scipy and
skimage are pinned via hiddenimports because the dynamic import hides them
from the analyzer.
"""
import os
import sys

ROOT = os.path.abspath(SPECPATH)

def py_files(rel):
    return [(os.path.join(rel, f), rel) for f in sorted(os.listdir(os.path.join(ROOT, rel)))
            if f.endswith(".py")]

datas = [
    ("cases", "cases"),
    ("make_gif.py", "."), ("spatial_stabilize.py", "."), ("segment.py", "."),
    ("build_frames.py", "."), ("verify.py", "."),
    ("examples/walker/make_material.py", "examples/walker"),
    ("LICENSE", "."),
]
# walker material is generated (gitignored); bundle it when present so the
# frozen build can run the example out of the box
for rel in ("examples/walker/walker_sheet.png", "examples/walker/boxes.json"):
    if os.path.exists(os.path.join(ROOT, rel)):
        datas.append((rel, os.path.dirname(rel)))
datas += py_files("v2") + py_files("v3")
walker_aligned = os.path.join(ROOT, "examples/walker/frames_aligned")
if os.path.isdir(walker_aligned):
    datas += [(os.path.join("examples/walker/frames_aligned", f), "examples/walker/frames_aligned")
              for f in sorted(os.listdir(walker_aligned)) if f.endswith(".png")]

# Anaconda builds of Pillow keep their codec DLLs in <base_prefix>/Library/bin,
# which the PyInstaller Pillow hook does not collect. Bundle exactly what the
# PIL .pyd modules import (parsed with pefile) plus their common chain deps.
ana_bin = os.path.join(os.path.dirname(sys.executable), "Library", "bin")
pil_dlls = ["avif.dll", "freetype.dll", "jpeg8.dll", "lcms2.dll", "libwebp.dll",
            "libwebpdemux.dll", "libwebpmux.dll", "openjp2.dll", "tiff.dll",
            "zlib.dll", "libsharpyuv.dll", "liblzma.dll", "libdeflate.dll",
            "zlib-ng2.dll", "turbojpeg.dll"]
binaries = [(os.path.join(ana_bin, name), ".") for name in pil_dlls
            if os.path.exists(os.path.join(ana_bin, name))]

a = Analysis(
    ["entry.py"],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "scipy", "scipy.ndimage", "scipy.spatial",
        "skimage", "skimage.registration",
        "PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFilter", "PIL.ImageSequence",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "pytest", "setuptools",
              "PyQt5", "PyQt6", "PySide2", "PySide6", "qtpy", "shiboken6",
              "IPython", "notebook", "jupyter",
              # pulled in by over-eager collection; nothing in Gifkit uses them
              "botocore", "boto3", "boto", "s3transfer", "jmespath",
              "panel", "bokeh", "holoviews", "param", "pyviz_comms",
              "numba", "llvmlite", "pandas", "dask", "distributed",
              "networkx", "numexpr", "tables", "h5py"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="Gifkit",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Gifkit",
)
