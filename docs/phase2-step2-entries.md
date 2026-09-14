# 第二阶段第二步：拆开入口与算法

日期：2026-09-13（基于第一步统一输入输出之上的增量改动）

## 目标与验收

目标：构建行为收进 `main()`/可调用函数，消除导入副作用。

验收标准（已达成）：
- 导入五个构建入口（以及全部九个验证/分析入口）**不读取、不生成、不删除任何文件**——由测试强制保证。
- 每个构建脚本真实重建一轮，产物与历史成品一致（见下方证据）。

## 改动范围

五个 GIF 构建入口全部重构为「顶层只有常量与纯函数，流水线在 `main()`，`if __name__ == "__main__"` 守卫」：

| 脚本 | 关键重构 |
|---|---|
| `make_gif.py` | `to_p(frames_alpha, transparent, pal_src)`——调色板从模块级流水线状态改为参数 |
| `v2/build_gifs.py` | `to_p(seq, transparent, pal_src)`、`save_gif(path, seq, transparent, pal_src)`；调色板拼图抽成 `build_palette(sample)` |
| `v2/build_24fps.py` | 同上；10 ms 累积取整抽成 `snap_durations(raw)` 纯函数 |
| `v3/build_gifs_v3.py` | `A(b, local)` 闭包改为 `frame_at(aligned, b, local)`；`build_gun(aligned)` / `build_melee(aligned)` / `pick_by_motion(aligned, b, n)` 显式接收帧序列；`save()` 增加 `out_dir` 参数 |
| `v3/build_melee_v4.py` | 输出目录创建抽成 `prepare_run_dir(base_dir)`（只新建、永不删除既有内容）；`save_gif(name, seq, durs, pal, out_dir, transparent)` 全参数化 |

设计约束：
- **不改变任何算法语义**：迁移的是"哪些代码在导入时执行"，不是算法本身。输出目录创建的时机也保持原序（v4 仍是先算完序列再建目录，中途崩溃不留空目录）。
- Mimo 专属参数（`PLAN`、`NB`、`HOLD`、帧序挑选、停顿等人工选择）原样保留为模块级常量——它们是第三步"案例配置"的抽取对象，本轮不动物理。
- 构建入口本轮不加 CLI 参数（输入侧参数化与第三步配置抽取一起做，避免半吊子接口）。

## 测试升级

`tests/test_regressions.py` 原先用 AST 提取函数、手工注入命名空间来绕开顶层副作用——重构后改为**直接导入模块、调用真实函数**：

- `test_palette_roundtrip`（10 项）：导入真实构建模块，直接调 `to_p`/`save`/`save_gif` 验证透明/不透明调色板往返。
- `test_v4_output_setup_preserves_existing_files`：直接调用 `prepare_run_dir()`，断言两次运行目录不同、既有 `seq_melee_v4` 内容不被删除。
- `tests/test_cli_io.py` 的"导入无副作用"参数化测试扩展到 14 个入口脚本（9 验证 + 5 构建）。
- 新增 `tests/conftest.py`：把 `v2/` 加入 `sys.path`，让进程内加载的构建脚本能像脚本运行时一样 `import morph`。

全套 `python -B -m pytest tests/ -q -p no:cacheprovider --tb=short` → **41 项全部通过**。

## 真实构建证据（重构后全量重建）

输出全部进入 gitignored 的独立运行目录，历史成品未触碰：

| 构建 | 运行目录 | 结果 | 与历史对照 |
|---|---|---|---|
| `make_gif.py` | `runs/v1-l8ae4hth` | 4 个 GIF 均 16 帧 | 一致 |
| `v2/build_gifs.py` | `v2/runs/v2-legacy-*` | key 16 帧 4.12 s、smooth 52 帧 4.12 s | 与当前源码 PLAN 精确吻合 |
| `v2/build_24fps.py` | `v2/runs/v2-24fps-ngfjwnf6` | 68 帧 4.20 s | 与历史 GIF 完全一致 |
| `v3/build_gifs_v3.py` | `v3/runs/v3-gt4trkw8` | gun 38 帧 1.83 s、melee 14 帧 1.47 s | 与历史成品精确一致 |
| `v3/build_melee_v4.py` | `v3/runs/melee-v4-23zlfs35` | 20 帧 1.68 s | 与历史成品精确一致 |

新产物随即交给第一步的验证器 CLI 交叉验证（"新产物可直接交给验证器"验收）：
- `v3/verify_v3.py <新 v4 运行目录>/mimo4_melee.gif` → 20 帧 1.68 s，motion 23.88 fps。
- `v3/diag_seq.py <新 v4 运行目录>/seq_melee_v4` → min IoU 0.773 / mean 0.851，与历史序列诊断完全相同。
- `v2/verify_24.py --gif <新 24fps 运行目录>/mimo2_24fps.gif --plan <同目录>/_plan24.json` → motion 23.79 fps（与历史 GIF 用同一口径测得同一数值），调色板实验完整跑通：254 色 3111.7 KB（误差 2.93/255）、160 色 2818.8 KB（3.75）、96 色 2494.2 KB（3.31）。

注：构建日志的 23.96 fps 与验证器的 23.79 fps 是两种统计口径（按中割标签统计 vs 按"时长 ≤50 ms"阈值统计，后者会混入 50 ms 关键帧停顿）——新旧产物在两种口径下各自一致，属既有定义差异，不是回归。

## 限制与下一步

- 构建产物的**视觉验收**（逐帧目检动作连贯性、透明边缘质量）仍属第二阶段第五步；本轮只做指标级一致性验证。
- 剩余仍有顶层副作用的脚本：`segment.py`、`build_frames.py`、`v2/segment.py`、`v2/align.py`、`v2/strip24.py`、`v2/export_key02_11.py`、`v2/make_chart.py`、`v2/export_crops.py`、`v3/build_v3.py`、`v3/extract_all.py`、`v3/locate_sprites.py`、`v3/strip_blocks.py` 等一次性工具脚本，将在第三步案例配置抽取时一并收编。
- 运行目录 `runs/v1-*` 等为本次验证新产物，可自行查看或删除；`.gitignore` 已覆盖。
