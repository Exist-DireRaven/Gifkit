"""Motion-compensated in-between synthesis (library).

For a transition A -> B we estimate bidirectional dense flow:
  d_ab(p): feature at A-pixel p moves to B-pixel p + d_ab(p)
  d_ba(q): feature at B-pixel q moves to A-pixel q + d_ba(q)
Large global displacement is pre-compensated with phase correlation so the
variational solver only has to resolve the residual (limb / hair) motion.

An in-between at phase t warps A forward by t*d_ab and B backward by
(1-t)*d_ba, then blends with alpha-weighted normalisation.  This follows the
real motion trajectory instead of cross-fading the two drawings.
"""
import os, json
import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree
from skimage.registration import optical_flow_tvl1, phase_cross_correlation

from pathlib import Path
OUT = str(Path(__file__).resolve().parent)
FRAMES = os.path.join(OUT, "frames_key")
CACHE = os.path.join(OUT, "_flow_cache")
# Cache directory creation is deferred until a cache entry is written.
N = 16


def load_key(i, frames_dir=None, pattern="key_%02d.png"):
    """i in 1..16 -> RGBA float32 (H,W,4). frames_dir defaults to the bundled v2 case."""
    from PIL import Image
    directory = frames_dir or FRAMES
    return np.asarray(Image.open(os.path.join(directory, pattern % i)).convert("RGBA")
                      ).astype(np.float32) / 255.0


def _sample(f, y, x):
    """Bilinear sample of (H,W,C) array at float coords."""
    out = np.empty(f.shape[:2] + (f.shape[2],), np.float32)
    for ch in range(f.shape[2]):
        out[..., ch] = ndimage.map_coordinates(f[..., ch], [y, x], order=1, mode="constant", cval=0.0)
    return out


def _flow_pair(alpha_a, alpha_b):
    """Return (d_ab, d_ba) in (row,col) units."""
    s, _, _ = phase_cross_correlation(alpha_a, alpha_b, upsample_factor=10, normalization=None)
    b_al = ndimage.shift(alpha_b, s, order=1, mode="constant", cval=0.0)
    v, u = optical_flow_tvl1(alpha_a, b_al, attachment=15, num_warp=8, num_iter=25, tol=1e-4)
    d_ab = np.stack([v, u], -1) - s.astype(np.float32)      # A -> B

    s2, _, _ = phase_cross_correlation(alpha_b, alpha_a, upsample_factor=10, normalization=None)
    a_al = ndimage.shift(alpha_a, s2, order=1, mode="constant", cval=0.0)
    v2, u2 = optical_flow_tvl1(alpha_b, a_al, attachment=15, num_warp=8, num_iter=25, tol=1e-4)
    d_ba = np.stack([v2, u2], -1) - s2.astype(np.float32)   # B -> A
    return d_ab.astype(np.float32), d_ba.astype(np.float32)


def get_flow(i, j, cache=True, frames_dir=None, pattern="key_%02d.png"):
    """Flow for key i -> key j (j may wrap to 1). Cached on disk.

    The cache key digests the frame contents, so entries from different
    frames_dir sources never collide.
    """
    import hashlib
    import inspect
    import tempfile
    import zipfile
    import scipy
    import skimage

    A, B = load_key(i, frames_dir, pattern), load_key(j, frames_dir, pattern)
    if A.shape != B.shape or A.ndim != 3 or A.shape[-1] != 4:
        raise ValueError("Flow inputs must have matching HxWx4 shapes")
    expected = A.shape[:2] + (2,)
    digest = hashlib.sha256(b"gifkit-flow-v2")
    digest.update(inspect.getsource(_flow_pair).encode("utf-8"))
    digest.update(repr((np.__version__, scipy.__version__, skimage.__version__)).encode("utf-8"))
    for frame in (A, B):
        digest.update(repr((frame.shape, frame.dtype.str)).encode("ascii"))
        digest.update(np.ascontiguousarray(frame).tobytes())
    path = os.path.join(CACHE, "flow" + digest.hexdigest() + ".npz")
    if cache and os.path.isfile(path):
        try:
            with np.load(path, allow_pickle=False) as saved:
                forward = saved.get("d_ab")
                backward = saved.get("d_ba")
                if (isinstance(forward, np.ndarray) and isinstance(backward, np.ndarray)
                        and forward.shape == expected and backward.shape == expected
                        and np.isfinite(forward).all() and np.isfinite(backward).all()):
                    return forward, backward
        except (OSError, ValueError, TypeError, KeyError, EOFError, zipfile.BadZipFile):
            pass  # Recompute corrupt or incompatible cache entries.
    d_ab, d_ba = _flow_pair(A[..., 3], B[..., 3])
    if (d_ab.shape != expected or d_ba.shape != expected
            or not np.isfinite(d_ab).all() or not np.isfinite(d_ba).all()):
        raise ValueError("Flow backend returned invalid arrays")
    if cache:
        os.makedirs(CACHE, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=CACHE, suffix=".npz", delete=False) as handle:
                temporary = handle.name
                np.savez_compressed(handle, d_ab=d_ab, d_ba=d_ba)
            os.replace(temporary, path)
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)
    return d_ab, d_ba


def warp_premult(f, disp):
    """Sample f at (grid - disp). disp is (row,col) forward displacement."""
    h, w = f.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    pm = np.concatenate([f[..., :3] * f[..., 3:4], f[..., 3:4]], -1)   # premultiplied
    out = _sample(pm, ys - disp[..., 0], xs - disp[..., 1])
    a = np.clip(out[..., 3:4], 0, 1)
    rgb = np.where(a > 1e-4, out[..., :3] / np.maximum(a, 1e-4), 0.0)
    return np.concatenate([rgb, a], -1)


def tween(A, B, d_ab, d_ba, t):
    """Synthesize the in-between at phase t in [0,1] (motion compensated)."""
    wa = warp_premult(A, t * d_ab)
    wb = warp_premult(B, (1.0 - t) * d_ba)
    aa, ab = wa[..., 3:4], wb[..., 3:4]
    ga, gb = (1.0 - t) * aa, t * ab
    denom = ga + gb + 1e-6
    rgb = (wa[..., :3] * ga + wb[..., :3] * gb) / denom
    alpha = np.maximum(aa, ab)
    out = np.concatenate([rgb, alpha], -1)
    return np.clip(out, 0, 1)


def crisp_alpha(f, lo=0.30, hi=0.72):
    """Tighten the silhouette edge that bilinear warping softened."""
    a = f[..., 3]
    a2 = np.clip((a - lo) / (hi - lo), 0, 1)
    a2 = np.where(a > 0.05, a2, 0.0)
    out = f.copy()
    out[..., 3] = a2
    return out


# ---------- palette snapping (keeps the original limited palette) ----------
_pal_tree = None
_pal = None


def build_palette(keys):
    global _pal_tree, _pal
    cols = []
    for k in keys:
        m = k[..., 3] > 0.6
        cols.append((k[..., :3][m] * 255).round().astype(np.uint8))
    pal = np.unique(np.concatenate(cols), axis=0).astype(np.float32)
    _pal = pal
    _pal_tree = cKDTree(pal)
    return pal


def snap_palette(f):
    if _pal_tree is None:
        raise RuntimeError("call build_palette first")
    out = f.copy()
    m = f[..., 3] > 0.5
    if m.sum():
        px = (f[..., :3][m] * 255).astype(np.float32)
        _, idx = _pal_tree.query(px, workers=-1)
        out[..., :3][m] = _pal[idx] / 255.0
    return out


def to_image(f):
    from PIL import Image
    a8 = (np.clip(f[..., 3], 0, 1) * 255).round().astype(np.uint8)
    rgb8 = (np.clip(f[..., :3], 0, 1) * 255).round().astype(np.uint8)
    return Image.fromarray(np.dstack([rgb8, a8]), "RGBA")
