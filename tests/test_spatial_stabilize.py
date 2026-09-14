"""Sequence-level spatial stabilization: unit + placement integration tests."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from spatial_stabilize import stabilize_axis, stabilize_spatial_sequence  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_column_offset_is_removed():
    vals = []
    for r in range(6):
        for c in range(8):
            vals.append(40.0 + (3.0 if c == 0 else 0.0) + [0.0, 0.3, -0.2][(r + c) % 3])
    corr, ret, snap, out, med = stabilize_axis(vals, period=8, mad_k=3.0, snap_cap=12.0)
    placed = [vals[i] + corr[i] for i in range(len(vals))]
    assert max(placed) - min(placed) < 1.0


def test_ground_leakage_is_snapped():
    vals = [40.0] * 16
    vals[9] = 46.0
    corr, ret, snap, out, med = stabilize_axis(vals, period=8, mad_k=3.0, snap_cap=12.0)
    placed = [vals[i] + corr[i] for i in range(len(vals))]
    assert abs(placed[9] - 40.0) < 1.5   # leakage pulled back near the reference


def test_coherent_drift_is_kept():
    vals = [40.0 + i * 1.2 for i in range(16)]
    corr, ret, snap, out, med = stabilize_axis(vals, period=8, mad_k=3.0, snap_cap=12.0)
    placed = [vals[i] + corr[i] for i in range(len(vals))]
    assert placed == pytest.approx(vals)   # real motion untouched


def test_large_isolated_jump_is_flagged():
    vals = [40.0, 40.0, 60.0, 40.0, 40.0]
    corr, ret, snap, out, med = stabilize_axis(vals, mad_k=3.0, snap_cap=8.0)
    assert len(out) == 1 and out[0]["frame"] == 3
    placed = [vals[i] + corr[i] for i in range(len(vals))]
    assert placed[2] == pytest.approx(60.0)   # kept as real motion


def test_stabilize_sequence_contract():
    meas = [{"anchor_x": 40.0, "ground_y": 100.0},
            {"anchor_x": 41.5, "ground_y": 100.8},
            {"anchor_x": 40.1, "ground_y": 100.1}]
    corr, report = stabilize_spatial_sequence(meas, 3, 1)
    assert len(corr) == 3 and all(set(c) == {"dx", "dy"} for c in corr)
    assert isinstance(report["snapped"], list)


def test_cut_frames_stabilize_removes_anchor_jitter():
    import importlib
    spec = importlib.util.spec_from_file_location("mg", os.path.join(ROOT, "make_gif.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rgba = np.full((120, 200, 4), 255, np.uint8)
    rgba[..., 3] = 0
    for x0 in (10, 110):
        rgba[20:90, x0:x0 + 80, :3] = (40, 90, 160)
        rgba[20:90, x0:x0 + 80, 3] = 255
    boxes = {(0, 0): [0, 0, 100, 120], (0, 1): [98, 0, 198, 120]}
    frames_on = module.cut_frames(rgba.astype(np.float32) / 255.0, boxes, [1, 2],
                                  [100, 120], baseline=110, oversize_policy="clamp",
                                  stabilize=True)
    frames_off = module.cut_frames(rgba.astype(np.float32) / 255.0, boxes, [1, 2],
                                   [100, 120], baseline=110, oversize_policy="clamp",
                                   stabilize=False)

    def head_x(f):
        a = f[..., 3] >= 0.5
        ys, xs = np.nonzero(a)
        top = ys <= ys.min() + (ys.max() - ys.min()) * 0.2
        return float(xs[top].mean())

    on = [head_x(f) for f in frames_on]
    off = [head_x(f) for f in frames_off]
    assert abs(on[0] - on[1]) < 0.5   # after stabilization both frames align
