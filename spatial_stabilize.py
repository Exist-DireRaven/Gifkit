"""Sequence-level spatial stabilization (group-aware).

Per-frame anchor/ground measurements are noisy estimators of the
character's true position.  The sequence reference is therefore computed
PER GROUP: the X axis is grouped by grid column and the Y axis by grid
row, so systematic per-column / per-row offsets in the source sheet are
absorbed by the group median instead of being misread as jitter.

Within a group, an isolated single-frame deviation beyond mad_k x MAD is
snapped to the group consensus (estimator jitter), while deviations
consistent with the neighbouring frames are kept as real motion.

Detached fragments and adjacent-cell leakage never reach this stage:
they are excluded upstream by despeckle and the width-robust ground
reference.
"""
from statistics import median


def stabilize_axis(vals, period=None, mad_k=3.0, snap_cap=None,
                   mad_floor=0.25, snap_slack=3.0):
    """Stabilize one axis.  Returns (correction, retained, snapped, outliers, med).

    correction[i] = offset to ADD to the naive placement of frame i (naive =
    put the measured anchor/ground at the canvas reference position).  It has
    two parts:
      1. group alignment shift — if the sheet is near-static (within-group
         MAD << between-group span), per-column/per-row systematic offsets
         are drawing noise and are removed by aligning every group to the
         global median; otherwise the per-group median IS the reference and
         this term is zero
      2. isolated spike snap — a single frame deviating from its neighbours
         beyond mad_k x MAD (within snap_slack of sprite scale) is snapped
         to the neighbour consensus; deviations beyond snap_slack are kept
         as real motion and reported
    """
    vals = [float(v) for v in vals]
    n = len(vals)
    if n == 0:
        return [], [], [], [], 0.0
    period = period if (period and period >= 2 and n > period) else None

    def group_of(i):
        return (i % period) if period else 0

    groups = {}
    for i, v in enumerate(vals):
        groups.setdefault(group_of(i), []).append(v)
    gmed = {g: median(vs) for g, vs in groups.items()}
    global_med = median(vals)

    # ---- part 1: group alignment shift (adaptive) ----
    use_global = False
    if period and len(gmed) > 1:
        within = [abs(v - gmed[group_of(i)]) for i, v in enumerate(vals)]
        within_mad = median(within) if within else 0.0
        between_span = max(abs(m - global_med) for m in gmed.values())
        if within_mad * 3 < between_span:
            use_global = True

    correction = [0.0] * n
    for i in range(n):
        g = group_of(i)
        target = global_med if use_global else gmed[g]
        correction[i] = target - gmed[g]

    # ---- part 2: isolated spike snap (after group alignment) ----
    dev_after = [vals[i] + correction[i] - global_med for i in range(n)]
    mad = median([abs(d) for d in dev_after]) if dev_after else 0.0
    mad_eff = max(mad, mad_floor)
    retained = list(dev_after)
    snapped = []
    for i in range(n):
        neighbours = [retained[j] for j in (i - 1, i + 1) if 0 <= j < n]
        if not neighbours:
            continue
        consensus = median(neighbours)
        residual = retained[i] - consensus
        if abs(residual) <= mad_k * mad_eff:
            continue
        if snap_cap is not None and abs(residual) > snap_cap:
            continue   # large: kept as real motion, reported below
        correction[i] += consensus - retained[i]
        retained[i] = consensus
        snapped.append({"frame": i + 1, "jitter_px": round(residual, 2)})
    correction = [round(c, 2) for c in correction]
    retained = [round(d, 2) for d in retained]
    # outlier report AFTER snapping: only frames still far from the reference
    outliers = [{"frame": i + 1, "dev_px": round(retained[i], 2)}
                for i in range(n) if abs(retained[i]) > mad_k * mad_eff]
    return correction, retained, snapped, outliers, round(global_med, 2)


def stabilize_spatial_sequence(measurements, grid_cols, grid_rows,
                               mad_k=3.0, width_frac=0.03):
    """Stabilize anchor_x (grouped by grid column) and ground_y (grouped by
    grid row) across the sequence.

    measurements: per-frame dicts with "anchor_x" and "ground_y".
    Returns (corrections, report): corrections[i] = {"dx", "dy"} to ADD to
    the naive placement offset (naive = anchor at canvas centre, ground row
    at the baseline).
    """
    n = len(measurements)
    xs = [m["anchor_x"] for m in measurements]
    ys = [m["ground_y"] for m in measurements]
    cap_x = max(8.0, grid_cols and 12.0 or 3.0)
    cap_y = max(8.0, grid_rows and 12.0 or 3.0)
    corr_x, ret_x, snap_x, out_x, med_x = stabilize_axis(xs, period=grid_cols, mad_k=mad_k, snap_cap=cap_x)
    corr_y, ret_y, snap_y, out_y, med_y = stabilize_axis(ys, period=grid_rows, mad_k=mad_k, snap_cap=cap_y)
    corrections = [{"dx": corr_x[i], "dy": corr_y[i]} for i in range(n)]
    report = {
        "reference_x_by_column": {g: round(m, 2) for g, m in sorted(med_x.items())} if isinstance(med_x, dict) else med_x,
        "reference_ground_y_by_row": {g: round(m, 2) for g, m in sorted(med_y.items())} if isinstance(med_y, dict) else med_y,
        "snapped": snap_x + snap_y,
        "outliers_kept_as_motion": {"x": out_x, "y": out_y},
    }
    return corrections, report
