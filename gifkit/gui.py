"""Gifkit graphical interface (tkinter, standard library only).

One foolproof page: pick an evenly gridded sprite sheet, click build, open
the output folder.  The grid is auto-detected, the background is keyed
automatically, and the canvas auto-fits — the rows/cols spinners are only a
fallback for when detection fails.  Builders run in a worker thread; their
console output streams into the log box.  Building the bundled cases is a
CLI feature (`gifkit build --case`), not a GUI one.
"""
import contextlib
import glob
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageDraw, ImageTk

from .cli import PROJECT_ROOT, cmd_build

MATERIAL_KEYS = ("source", "boxes_file", "frames_dir", "aligned_dir", "tiles_dir")


# ---------------------------------------------------------------- pure helpers
def prepare_output_dir(chosen):
    chosen = os.path.abspath(chosen)
    os.makedirs(chosen, exist_ok=True)
    if os.listdir(chosen):
        run = os.path.join(chosen, time.strftime("Gifkit-%Y%m%d-%H%M%S"))
        os.makedirs(run, exist_ok=True)
        return run
    return chosen


def default_output_dir():
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.expanduser("~"), "Gifkit输出")
    return str(PROJECT_ROOT / "runs")


def sheet_has_alpha(src_path, threshold=250):
    from PIL import Image
    im = Image.open(src_path)
    if im.mode not in ("RGBA", "LA", "PA"):
        return False
    alpha = np.asarray(im.convert("RGBA"))[..., 3]
    return bool((alpha < threshold).any())


def _background_clusters(border, tol=24, max_clusters=4):
    q = (border // tol).astype(np.int64)
    keys = q[:, 0] * 4096 + q[:, 1] * 64 + q[:, 2]
    uniq, cnt = np.unique(keys, return_counts=True)
    order = np.argsort(cnt)[::-1]
    clusters, covered, total = [], 0, len(border)
    for idx in order:
        if covered >= 0.9 * total or len(clusters) >= max_clusters:
            break
        sel = keys == uniq[idx]
        colour = border[sel].mean(axis=0)
        if all(np.abs(colour - e).max() > tol for e in clusters):
            clusters.append(colour)
            covered += int(cnt[idx])
    if not clusters:
        return np.array([[255.0, 255.0, 255.0]])
    return np.array(clusters)


def key_white_background(src_path, dst_path, tol=24):
    from PIL import Image
    from scipy import ndimage as ndi
    im = Image.open(src_path).convert("RGB")
    rgb = np.asarray(im).astype(np.int16)
    border = np.concatenate([rgb[0, :, :], rgb[-1, :, :], rgb[:, 0, :], rgb[:, -1, :]])
    clusters = _background_clusters(border, tol=tol)
    dist = np.full(rgb.shape[:2], 255, np.int16)
    for colour in clusters:
        d = np.abs(rgb - colour[None, None, :]).max(axis=2)
        dist = np.minimum(dist, d)
    candidate = dist <= tol
    lab, _n = ndi.label(candidate, structure=np.ones((3, 3), bool))
    border_labels = set(lab[0, :]) | set(lab[-1, :]) | set(lab[:, 0]) | set(lab[:, -1])
    border_labels.discard(0)
    bg = np.isin(lab, list(border_labels)) if border_labels else np.zeros(candidate, bool)
    alpha = (~bg).astype(np.float32)
    if alpha.sum() < 1:
        raise ValueError("抠底后画面为空——整张图都被识别为背景？")
    alpha = ndi.gaussian_filter(alpha, 0.6)
    rgba = np.dstack([np.asarray(im).astype(np.uint8), (alpha * 255).astype(np.uint8)])
    Image.fromarray(rgba, "RGBA").save(dst_path)
    return dst_path


def _axis_cut_lines(profile, n, rel=0.12):
    """n+1 cut positions along a 1-D ink profile.

    The empty gutters between sprites are the truth; use their centres when
    exactly n-1 interior gutters exist, else fall back to even division of
    the profile.  Lows that touch the profile edges are sheet margins, not
    gutters, and never count."""
    length = len(profile)
    even = [round(length * k / n) for k in range(n + 1)]
    peak = float(profile.max())
    if peak <= 0:
        return even
    low = profile < rel * peak
    gutters, i = [], 0
    while i < length:
        if low[i]:
            j = i
            while j < length and low[j]:
                j += 1
            centre = (i + j - 1) / 2.0
            if 1 <= centre <= length - 2:
                gutters.append(int(round(centre)))
            i = j
        else:
            i += 1
    if len(gutters) == n - 1:
        return [0] + gutters + [length]
    return even


def detect_sheet_boxes(keyed_path, rows, cols, margin=0.06, gap=0.02):
    """Slice the sheet into per-sprite boxes for a known grid.

    detect_grid_exhaustive measures the grid on the sheet's content bounding
    box, so the same box is sliced here: dividing the full image into equal
    cells drifts whenever the ink is off-centre (an empty strip at one edge
    shifts every cut line and splits each sprite across two cells).  Cells
    are then tightened to their own ink extent."""
    from PIL import Image
    alpha = np.asarray(Image.open(keyed_path).convert("RGBA"))[..., 3].astype(np.float32) / 255.0
    ink = alpha > 0.1
    H, W = ink.shape
    ys, xs = np.nonzero(ink)
    if len(ys) == 0:
        top, bottom, left, right = 0, H, 0, W
    else:
        top, bottom, left, right = int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1
    sub = ink[top:bottom, left:right]
    row_lines = _axis_cut_lines(sub.sum(axis=1), rows)
    col_lines = _axis_cut_lines(sub.sum(axis=0), cols)
    boxes = {}
    for r in range(rows):
        for c in range(cols):
            gy0, gy1 = top + row_lines[r], top + row_lines[r + 1]
            gx0, gx1 = left + col_lines[c], left + col_lines[c + 1]
            cw, ch = gx1 - gx0, gy1 - gy0
            mx, my = max(1, int(cw * gap)), max(1, int(ch * gap))
            cell = ink[gy0:gy1, gx0:gx1]
            ys2, xs2 = np.nonzero(cell)
            if len(ys2) == 0:
                boxes["%d,%d" % (r, c)] = [gx0 + int(cw * margin), gy0 + int(ch * margin),
                                           gx1 - int(cw * margin), gy1 - int(ch * margin)]
                continue
            x0 = gx0 + max(0, int(xs2.min()) - mx)
            y0 = gy0 + max(0, int(ys2.min()) - my)
            x1 = gx0 + min(cw, int(xs2.max()) + 1 + mx)
            y1 = gy0 + min(ch, int(ys2.max()) + 1 + my)
            boxes["%d,%d" % (r, c)] = [x0, y0, x1, y1]
    return boxes


def _significant_gaps(profile, rel=0.25):
    n = len(profile)
    mins = []
    for x in range(1, n - 1):
        lo, hi = max(0, x - 6), min(n, x + 7)
        peak = profile[lo:hi].max()
        if profile[x] < rel * peak and profile[x] <= profile[x - 1] and profile[x] <= profile[x + 1]:
            mins.append(x)
    out = []
    for g in mins:
        if not out or g - out[-1][-1] > 4:
            out.append([g])
        else:
            out[-1].append(g)
    return [int(np.mean(g)) for g in out]


def detect_grid_exhaustive(keyed_path, max_rows=12, max_cols=12, min_cell=16,
                           gap_penalty=2.0, empty_penalty=2.0):
    from PIL import Image
    alpha = np.asarray(Image.open(keyed_path).convert("RGBA"))[..., 3].astype(np.float32) / 255.0
    ys, xs = np.nonzero(alpha > 0.1)
    if len(ys) == 0:
        return None
    sub = alpha[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = sub.shape
    colp = sub.sum(axis=0)
    rowp = sub.sum(axis=1)
    v_gaps = _significant_gaps(colp)
    h_gaps = _significant_gaps(rowp)

    def snap(profile, x):
        lo, hi = max(0, x - 8), min(len(profile), x + 9)
        return lo + int(np.argmin(profile[lo:hi]))

    def line_cost(profile, x):
        lo, hi = max(0, x - 6), min(len(profile), x + 7)
        peak = profile[lo:hi].max()
        return profile[x] / max(peak, 1e-6)

    def uncovered(gaps, lines):
        return sum(1 for g in gaps if all(abs(g - line) > 8 for line in lines))

    best, best_cells, best_cost = (1, 1), 1, None
    for r in range(1, max_rows + 1):
        for c in range(1, max_cols + 1):
            cell_h, cell_w = h / r, w / c
            if cell_h < min_cell or cell_w < min_cell:
                continue
            v_lines = [snap(colp, int(round(cell_w * k))) for k in range(1, c)]
            h_lines = [snap(rowp, int(round(cell_h * k))) for k in range(1, r)]
            cost = sum(line_cost(colp, x) for x in v_lines)
            cost += sum(line_cost(rowp, y) for y in h_lines)
            cost += gap_penalty * (uncovered(v_gaps, v_lines) + uncovered(h_gaps, h_lines))
            empty = 0
            for rr in range(r):
                for cc in range(c):
                    if not sub[int(rr * cell_h):int((rr + 1) * cell_h),
                               int(cc * cell_w):int((cc + 1) * cell_w)].any():
                        empty += 1
            cost += empty_penalty * empty
            if best_cost is None or cost < best_cost - 1e-9 or \
                    (abs(cost - best_cost) <= 1e-9 and r * c > best_cells):
                best, best_cells, best_cost = (r, c), r * c, cost
    return best


def write_own_sheet_case(out_dir, sheet_path, rows, cols, duration_ms,
                         detect_grid=True, normalize_height=False):
    """Write boxes.json + gui_case.json for one own-sheet build.

    detect_grid=False honours the caller's rows/cols verbatim (GUI "manual"
    mode); with it on, a successful detection overrides them.  normalize_height
    defaults off: action sheets legitimately change height (crouch, jump), and
    rescaling reads as pumping — AI micro-drift is the case for turning it on.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    info = {"keyed": False, "canvas": None, "baseline": None, "grid_detected": None}
    src = str(sheet_path)
    if not sheet_has_alpha(src):
        keyed = out_dir / "sheet_keyed.png"
        key_white_background(src, keyed)
        src = str(keyed)
        info["keyed"] = True
    if detect_grid:
        detected = detect_grid_exhaustive(src)
        if detected:
            rows, cols = detected
            info["grid_detected"] = detected
    boxes = detect_sheet_boxes(src, rows, cols)
    max_w = max(x1 - x0 for x0, _y0, x1, _y1 in boxes.values()) + 1
    max_h = max(y1 - y0 for _x0, y0, _x1, y1 in boxes.values()) + 1
    baseline = max_h + max(2, int(max_h * 0.01))
    canvas = [max_w + 2, baseline + max(4, int(max_h * 0.04))]
    info["canvas"], info["baseline"] = canvas, baseline
    (out_dir / "boxes.json").write_text(json.dumps(boxes, indent=1), encoding="utf-8")
    stem = Path(sheet_path).stem or "sheet"
    config = {
        "case": "gui_custom_grid",
        "builder": "make_gif.py",
        "comment": "Generated by the Gifkit GUI; auto-keyed, auto-fitted.",
        "source": str(Path(src).resolve()),
        "boxes_file": str((out_dir / "boxes.json").resolve()),
        "output_stem": stem,
        "grid": [rows, cols],
        "canvas": canvas,
        "baseline": baseline,
        "duration_ms": duration_ms,
        "alpha_solid": 96,
        "normalize_height": bool(normalize_height),
        "despeckle": True,
        "stabilize": False,
        "small_size": [max(1, canvas[0] // 2), max(1, canvas[1] // 2)],
        "oversize_policy": "clamp",
        "run_prefix": "gui-",
    }
    config_path = out_dir / "gui_case.json"
    config_path.write_text(json.dumps(config, indent=1, ensure_ascii=False),
                           encoding="utf-8")
    return config_path, info


# ---------------------------------------------------------------- worker
class _LogWriter:
    def __init__(self, line_queue):
        self._queue = line_queue
        self._pending = ""

    def write(self, text):
        self._pending += text
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            self._queue.put(("log", line))

    def flush(self):
        if self._pending:
            self._queue.put(("log", self._pending))
            self._pending = ""


def build_in_thread(argv, out_queue):
    """Build a ready case config in a daemon thread (CLI-style argv)."""
    def worker():
        writer = _LogWriter(out_queue)
        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                cmd_build(list(argv))
            writer.flush()
            out_queue.put(("done", True, ""))
        except SystemExit as exc:
            writer.flush()
            out_queue.put(("done", False, str(exc) or "构建失败"))
        except Exception as exc:
            writer.flush()
            out_queue.put(("done", False, "%s: %s" % (type(exc).__name__, exc)))

    threading.Thread(target=worker, daemon=True).start()


def _run_worker(fn, out_queue):
    def worker():
        writer = _LogWriter(out_queue)
        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                fn()
            writer.flush()
            out_queue.put(("done", True, ""))
        except SystemExit as exc:
            writer.flush()
            out_queue.put(("done", False, str(exc) or "构建失败"))
        except Exception as exc:
            writer.flush()
            out_queue.put(("done", False, "%s: %s" % (type(exc).__name__, exc)))

    threading.Thread(target=worker, daemon=True).start()


def _keyed_for_analysis(path, tag):
    """Return a path whose background is transparent (keying to a temp file
    when the source has no alpha)."""
    if sheet_has_alpha(path):
        return path
    keyed = os.path.join(tempfile.gettempdir(), "gifkit_%s_keyed.png" % tag)
    key_white_background(path, keyed)
    return keyed


def prep_and_build_in_thread(job, out_queue):
    """Whole own-sheet pipeline off the Tk thread.

    Keying a large sheet and the exhaustive grid scan each take seconds —
    running them on the main thread froze the window before the build even
    started.  job keys: sheet, out, build_dir, rows, cols, duration,
    detect (bool), normalize (bool)."""
    def fn():
        out_queue.put(("log", "— 预处理：抠底%s —" %
                       ("、网格检测" if job["detect"] else "")))
        config_path, info = write_own_sheet_case(
            job["out"], job["sheet"], job["rows"], job["cols"], job["duration"],
            detect_grid=job["detect"], normalize_height=job["normalize"])
        if info.get("keyed"):
            out_queue.put(("log", "已自动移除背景（原图不含透明通道）"))
        if info.get("grid_detected"):
            out_queue.put(("log", "自动检测到网格：%d 行 × %d 列" % info["grid_detected"]))
        elif job["detect"]:
            out_queue.put(("log", "未检测到可靠网格，按设定的 %d 行 × %d 列切割"
                           % (job["rows"], job["cols"])))
        else:
            out_queue.put(("log", "按手动指定的 %d 行 × %d 列切割" % (job["rows"], job["cols"])))
        out_queue.put(("log", "画布自动适配为 %dx%d，地线 y=%d"
                       % (*info["canvas"], info["baseline"])))
        if job["normalize"]:
            out_queue.put(("log", "已开启统一角色高度（蹲伏/跳跃类动作建议改回保持原始尺寸）"))
        out_queue.put(("log", "— 构建 —"))
        cmd_build(["--config", str(config_path), "--out", job["build_dir"]])

    _run_worker(fn, out_queue)


def detect_grid_in_thread(path, out_queue):
    """Best-effort grid detection off the Tk thread; result via ("grid", (r, c))."""
    def fn():
        detected = detect_grid_exhaustive(_keyed_for_analysis(path, "pick"))
        if detected:
            out_queue.put(("grid", detected))

    def runner():
        try:
            fn()
        except Exception:
            pass

    threading.Thread(target=runner, daemon=True).start()


def preview_boxes_in_thread(path, rows, cols, out_queue):
    """Compute per-sprite boxes for the cut preview; result via ("preview", ...)."""
    def fn():
        boxes = detect_sheet_boxes(_keyed_for_analysis(path, "preview"), rows, cols)
        out_queue.put(("preview", path, boxes))

    def runner():
        try:
            fn()
        except Exception as exc:
            out_queue.put(("log", "切割预览失败：%s" % exc))

    threading.Thread(target=runner, daemon=True).start()


# ---------------------------------------------------------------- GUI
class App:
    def __init__(self, root):
        self.root = root
        root.title("Gifkit — sprite sheet 转循环 GIF")
        root.geometry("860x620")
        self.out_queue = queue.Queue()
        self.last_outdir = None
        self._building = False
        self._trim_selected = set()
        self._trim_photos = []
        self._trim_labels = {}

        page = ttk.Frame(root, padding=10)
        page.pack(fill="both", expand=False)

        ttk.Label(page, text="选择 sprite sheet → 一键生成 → 点击不需要的帧剪掉。"
                             "网格、背景、画布全部自动处理。").pack(anchor="w")

        pick = ttk.Frame(page)
        pick.pack(fill="x", pady=6)
        ttk.Button(pick, text="1. 选择 sprite sheet 图片…", command=self.pick_sheet).pack(side="left")
        self.sheet_var = tk.StringVar(value="（未选择）")
        ttk.Label(pick, textvariable=self.sheet_var).pack(side="left", padx=8)

        grid = ttk.Frame(page)
        grid.pack(fill="x", pady=4)
        self.grid_auto = tk.BooleanVar(value=True)
        self.sheet_rows = tk.IntVar(value=4)
        self.sheet_cols = tk.IntVar(value=4)
        self.duration = tk.IntVar(value=120)
        mode = ttk.Frame(grid)
        mode.pack(side="left", padx=(0, 14))
        ttk.Label(mode, text="网格").pack(anchor="w")
        radio_row = ttk.Frame(mode)
        radio_row.pack()
        ttk.Radiobutton(radio_row, text="自动检测", variable=self.grid_auto, value=True,
                        command=self._grid_mode_changed).pack(side="left")
        ttk.Radiobutton(radio_row, text="手动指定", variable=self.grid_auto, value=False,
                        command=self._grid_mode_changed).pack(side="left")
        self._spinboxes = {}
        for text, var, lo, hi in (("行数", self.sheet_rows, 1, 16),
                                  ("列数", self.sheet_cols, 1, 16),
                                  ("每帧毫秒", self.duration, 20, 2000)):
            box = ttk.Frame(grid)
            box.pack(side="left", padx=(0, 14))
            ttk.Label(box, text=text).pack(anchor="w")
            spin = ttk.Spinbox(box, from_=lo, to=hi, textvariable=var, width=7)
            spin.pack()
            self._spinboxes[text] = spin
        self.preview_button = ttk.Button(grid, text="预览切割线",
                                         command=self.show_cut_preview, state="disabled")
        self.preview_button.pack(side="left", padx=(0, 4))
        self._grid_mode_changed()

        height = ttk.Frame(page)
        height.pack(fill="x", pady=4)
        self.normalize_height = tk.BooleanVar(value=False)
        hbox = ttk.Frame(height)
        hbox.pack(side="left")
        ttk.Label(hbox, text="各帧高度").pack(anchor="w")
        hrow = ttk.Frame(hbox)
        hrow.pack()
        ttk.Radiobutton(hrow, text="保持原始尺寸", variable=self.normalize_height,
                        value=False).pack(side="left")
        ttk.Radiobutton(hrow, text="统一角色高度", variable=self.normalize_height,
                        value=True).pack(side="left")
        ttk.Label(height, text="统一高度专为 AI 生成素材的轻微漂移设计，"
                               "会缩放蹲伏/跳跃等真实的高低动作",
                  foreground="#888").pack(side="left", padx=8)

        buttons = ttk.Frame(page)
        buttons.pack(fill="x", pady=(4, 0))
        self.sheet_build_button = ttk.Button(buttons, text="2. 一键生成 GIF",
                                             command=self.start_own_sheet_build)
        self.sheet_build_button.pack(side="left")
        self.open_button = ttk.Button(buttons, text="打开输出文件夹", command=self.open_outdir,
                                      state="disabled")
        self.open_button.pack(side="left", padx=8)

        # ---- 帧剪辑（缩略图点选）----
        clip = ttk.LabelFrame(page, text="帧剪辑（点击不需要的帧选中，然后剪掉）", padding=6)
        clip.pack(fill="x", pady=(8, 0))
        clip_bar = ttk.Frame(clip)
        clip_bar.pack(fill="x")
        self.trim_button = ttk.Button(clip_bar, text="剪掉选中帧", command=self.trim_frames,
                                      state="disabled")
        self.trim_button.pack(side="left")
        self.trim_status = ttk.Label(clip_bar, text="", foreground="#888")
        self.trim_status.pack(side="left", padx=8)
        self.trim_canvas = tk.Canvas(clip, height=92, bg="#f0f0f0", highlightthickness=0)
        h_scroll = ttk.Scrollbar(clip, orient="horizontal", command=self.trim_canvas.xview)
        self.trim_canvas.configure(xscrollcommand=h_scroll.set)
        h_scroll.pack(side="bottom", fill="x")
        self.trim_canvas.pack(fill="x")
        self.trim_inner = ttk.Frame(self.trim_canvas)
        self.trim_canvas.create_window((0, 0), window=self.trim_inner, anchor="nw")
        self.trim_inner.bind("<Configure>", lambda e: self.trim_canvas.configure(
            scrollregion=self.trim_canvas.bbox("all")))

        self._build_log_area(root)

    def _build_log_area(self, root):
        log_box = ttk.LabelFrame(root, text="输出日志", padding=4)
        log_box.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        self.log = tk.Text(log_box, height=10, state="disabled", font=("Consolas", 9))
        scroll = ttk.Scrollbar(log_box, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)
        self.root.after(120, self._poll_log)

    def log_line(self, text):
        self.log.config(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _poll_log(self):
        try:
            while True:
                item = self.out_queue.get_nowait()
                if item[0] == "log":
                    self.log_line(item[1])
                elif item[0] == "grid":
                    self._on_grid_detected(item[1])
                elif item[0] == "preview":
                    self._show_preview(item[1], item[2])
                elif item[0] == "done":
                    self._build_finished(item[1], item[2])
        except queue.Empty:
            pass
        self.root.after(120, self._poll_log)

    def _on_grid_detected(self, detected):
        """Detection result arriving from the worker thread: fill the
        spinners as the auto-mode suggestion (never overrides manual mode's
        pending values — the user switched modes before this returned)."""
        self.sheet_rows.set(detected[0])
        self.sheet_cols.set(detected[1])
        if self.grid_auto.get():
            self.log_line("自动检测到网格：%d 行 × %d 列（可点“预览切割线”确认）" % detected)

    # ---- actions ---------------------------------------------------------
    def _grid_mode_changed(self):
        """Auto mode: the spinners display detection results and stay read-only;
        manual mode: the user's numbers are used verbatim, never overridden."""
        for text in ("行数", "列数"):
            self._spinboxes[text].config(
                state="disabled" if self.grid_auto.get() else "normal")

    def pick_sheet(self):
        path = filedialog.askopenfilename(title="选择 sprite sheet",
                                          filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp"), ("所有文件", "*.*")])
        if not path:
            return
        self.sheet_var.set(path)
        self.preview_button.config(state="normal")
        self.log_line("正在分析背景与网格…")
        detect_grid_in_thread(path, self.out_queue)

    def show_cut_preview(self):
        """Open a window with the sheet and the exact cut boxes that would be
        used (auto mode: the detected grid; manual mode: the typed numbers)."""
        path = self.sheet_var.get()
        if not os.path.isfile(path) or self._building:
            return
        self.preview_button.config(state="disabled")
        preview_boxes_in_thread(path, int(self.sheet_rows.get()),
                                int(self.sheet_cols.get()), self.out_queue)

    def _show_preview(self, sheet_path, boxes):
        im = Image.open(sheet_path).convert("RGB")
        scale = min(560 / im.width, 420 / im.height, 1.0)
        disp = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))),
                         Image.LANCZOS)
        draw = ImageDraw.Draw(disp)
        for x0, y0, x1, y1 in boxes.values():
            draw.rectangle([x0 * scale, y0 * scale, x1 * scale - 1, y1 * scale - 1],
                           outline=(224, 32, 32), width=max(1, int(round(2 * scale))))
        photo = ImageTk.PhotoImage(disp)
        win = tk.Toplevel(self.root)
        win.title("切割预览（%d 行 × %d 列）" % (self.sheet_rows.get(), self.sheet_cols.get()))
        lbl = tk.Label(win, image=photo, bg="#1c1c24")
        lbl.image = photo
        lbl.pack(padx=10, pady=10)
        ttk.Label(win, text="红线即每格切割框；不贴合就换“手动指定”调整行列数",
                  foreground="#888").pack(pady=(0, 8))
        self.preview_button.config(state="normal")

    def start_own_sheet_build(self):
        sheet = self.sheet_var.get()
        if not os.path.isfile(sheet):
            messagebox.showinfo("Gifkit", "请先选择一张 sprite sheet 图片")
            return
        out = filedialog.askdirectory(title="选择输出文件夹", initialdir=default_output_dir())
        if not out:
            return
        out = prepare_output_dir(out)
        build_dir = os.path.join(out, "build")
        os.makedirs(build_dir, exist_ok=True)
        job = {"sheet": sheet, "out": out, "build_dir": build_dir,
               "rows": int(self.sheet_rows.get()), "cols": int(self.sheet_cols.get()),
               "duration": int(self.duration.get()),
               "detect": bool(self.grid_auto.get()),
               "normalize": bool(self.normalize_height.get())}
        self._start_build(job, build_dir)

    def _start_build(self, job, outdir):
        if self._building:
            return
        self._building = True
        self.last_outdir = outdir
        self.sheet_build_button.config(state="disabled")
        self.preview_button.config(state="disabled")
        self.open_button.config(state="disabled")
        self.trim_button.config(state="disabled")
        self.log_line("— 开始构建 %s —" % time.strftime("%H:%M:%S"))
        prep_and_build_in_thread(job, self.out_queue)

    def _build_finished(self, ok, message):
        self._building = False
        self.sheet_build_button.config(state="normal")
        if os.path.isfile(self.sheet_var.get()):
            self.preview_button.config(state="normal")
        if ok:
            self.open_button.config(state="normal")
            self.log_line("✓ 构建完成，输出目录：%s" % self.last_outdir)
            self._load_frame_thumbs()
        else:
            self.log_line("✗ 构建失败：%s" % message)
            messagebox.showerror("Gifkit 构建失败", message)

    def open_outdir(self):
        if self.last_outdir and os.path.isdir(self.last_outdir):
            os.startfile(self.last_outdir)

    def trim_frames(self):
        if not self._trim_selected:
            messagebox.showinfo("Gifkit", "请先点击不需要的帧")
            return
        if not self.last_outdir:
            messagebox.showinfo("Gifkit", "请先构建一次")
            return
        build = self.last_outdir
        gifs = sorted(glob.glob(os.path.join(build, "*.gif")))
        if not gifs:
            messagebox.showinfo("Gifkit", "输出文件夹里没有 GIF")
            return
        for g in gifs:
            backup = g.replace(".gif", "_full.gif")
            if not os.path.isfile(backup):
                import shutil as _sh
                _sh.copy2(g, backup)
            im = Image.open(g)
            nf = im.n_frames
            keep = [i for i in range(nf) if (i + 1) not in self._trim_selected]
            if not keep:
                messagebox.showerror("Gifkit", "不能剪掉所有帧")
                return
            out_frames = []
            durations = []
            for k in keep:
                im.seek(k)
                out_frames.append(im.copy())
                durations.append(im.info.get("duration", 100))
            out_frames[0].save(g, save_all=True, append_images=out_frames[1:],
                               duration=durations, loop=0, disposal=2,
                               transparency=im.info.get("transparency"))
        removed = sorted(self._trim_selected)
        self.log_line("✓ 剪辑完成：去掉第 %s 帧，%d → %d 帧 | 原始版本保留为 *_full.gif" %
                      (",".join(str(d) for d in removed), nf, len(keep)))
        self.trim_status.config(text="已剪掉 %s" % ",".join(str(d) for d in removed))
        self._trim_selected.clear()
        self._load_frame_thumbs()

    def _load_frame_thumbs(self):
        for w in self.trim_inner.winfo_children():
            w.destroy()
        self._trim_photos.clear()
        self._trim_labels.clear()
        self._trim_selected.clear()
        build = self.last_outdir
        gifs = sorted(glob.glob(os.path.join(build, "*.gif")))
        if not gifs:
            self.trim_button.config(state="disabled")
            return
        main = max(gifs, key=os.path.getsize)
        try:
            im = Image.open(main)
        except Exception:
            self.trim_button.config(state="disabled")
            return
        nf = im.n_frames
        ts = 64
        for k in range(nf):
            im.seek(k)
            fr = im.copy().convert("RGBA")
            bg = Image.new("RGBA", fr.size, (30, 30, 36, 255))
            bg.alpha_composite(fr)
            ratio = min(ts / bg.width, ts / bg.height, 1.0)
            tw = max(1, int(bg.width * ratio))
            th = max(1, int(bg.height * ratio))
            bg = bg.resize((tw, th), Image.LANCZOS)
            photo = ImageTk.PhotoImage(bg)
            self._trim_photos.append(photo)
            lbl = tk.Label(self.trim_inner, image=photo, cursor="hand2",
                           highlightthickness=2, highlightbackground="#bbbbbb")
            lbl.grid(row=0, column=k, padx=1, pady=2)
            lbl.bind("<Button-1>", lambda e, k=k: self._toggle_trim(k))
            lbl.bind("<Double-Button-1>", lambda e, k=k, im=bg.copy(): self._zoom_frame(k, im))
            cap = tk.Label(self.trim_inner, text=str(k + 1), font=("Consolas", 7))
            cap.grid(row=1, column=k)
            self._trim_labels[k] = lbl
        self.trim_button.config(state="normal")

    def _zoom_frame(self, frame_idx, pil_image):
        """Double-click a thumbnail to open a large preview in a separate window."""
        win = tk.Toplevel(self.root)
        win.title("帧 %d 预览（点击关闭）" % (frame_idx + 1))
        ratio = 1.0
        max_dim = 500
        if max(pil_image.width, pil_image.height) > max_dim:
            ratio = max_dim / max(pil_image.width, pil_image.height)
        disp = pil_image.resize((max(1, int(pil_image.width * ratio)),
                                 max(1, int(pil_image.height * ratio))), Image.LANCZOS)
        bg = Image.new("RGBA", disp.size, (30, 30, 36, 255))
        bg.alpha_composite(disp.convert("RGBA"))
        photo = ImageTk.PhotoImage(bg.convert("RGB"))
        lbl = tk.Label(win, image=photo, bg="#1c1c24")
        lbl.image = photo
        lbl.pack(padx=10, pady=10)
        info = tk.Label(win, text="帧 %d / %d px" % (frame_idx + 1, pil_image.width),
                        font=("Consolas", 9))
        info.pack(pady=(0, 8))
        lbl.bind("<Button-1>", lambda e: win.destroy())

    def _toggle_trim(self, frame_idx):
        if frame_idx in self._trim_selected:
            self._trim_selected.discard(frame_idx)
        else:
            self._trim_selected.add(frame_idx)
        lbl = self._trim_labels.get(frame_idx)
        if lbl:
            lbl.config(highlightbackground="#e02020" if frame_idx in self._trim_selected
                       else "#bbbbbb")


def run_gui(argv=None):
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()
