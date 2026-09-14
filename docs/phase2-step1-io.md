# 第二阶段第一步：统一输入/输出参数

日期：2026-09-13（基于第一阶段修复之上的增量改动）

## 目标与验收

目标：构建、分析、验证都能显式选择文件或目录；优先解决旧验证脚本只读历史位置的问题。

验收标准（已达成）：
- 新产物（`runs/` 目录里的 GIF、帧序列）可以直接交给验证器，不需要改源码或复制回历史目录。
- 无参数运行时，行为与历史用法一致（校验历史案例素材）。

## 改动范围

### 1. 九个验证/分析脚本加入 argparse CLI

每个脚本都改为 `main(argv)` + `if __name__ == "__main__"` 结构：**导入不再执行任何处理**（这是第二阶段第二步"拆开入口与算法"在本子集上的提前落地）。默认值保留历史行为；显式传参时输出默认写到输入文件旁边（或 `--outdir` 指定的目录），使每个 runs 目录自包含。

| 脚本 | 输入参数 | 默认输入 | 输出 |
|---|---|---|---|
| `verify.py` | 位置参数 GIF 列表、`--outdir/--cols/--scale/--bg` | 根目录 3 个 `mimo_loop*.gif` | `_check_<stem>.png` |
| `v2/verify_gifs.py` | 同上、`--tile` | `mimo2_smooth.gif`、`mimo2_key.gif`（缺失自动跳过） | `_check_<stem>.png` |
| `v2/verify_24.py` | `--gif/--plan/--frames-dir/--outdir` | `mimo2_24fps.gif` | `_check_<stem>.png`；plan 缺失时跳过调色板实验 |
| `v2/check_quality.py` | `--gif/--transitions/--frames-dir/--count/--outdir` | `mimo2_key.gif` | `_strip_hard_<i>_<j>.png` |
| `v2/analyze_continuity.py` | `--frames-dir/--pattern/--start/--count/--json-out` | `v2/frames_key`（16 帧） | `_continuity.json` |
| `v2/evaluate_schemes.py` | `--frames-dir/--count/--json-out` | `morph` 默认关键帧 | `_schemes.json` |
| `v3/verify_v3.py` | GIF 列表、`--outdir/--cols/--tile` | `mimo3_gun.gif`、`mimo3_melee.gif` | `_check_<stem>.png` |
| `v3/check_frames.py` | `--tiles-dir/--full-count/--pair-count/--json-out` | `v3/tiles` | `_match.json` |
| `v3/diag_seq.py` | 位置参数目录（路径或 v3/ 相对名）、`--json-out` | `v3/seq_melee_v4` | 可选 JSON 摘要 |

用法示例：

```bash
# 校验新一轮构建的产物（不用改源码、不用复制回历史目录）
python v3/verify_v3.py v3/runs/melee-v4-xxxx/mimo4_melee.gif
python v3/diag_seq.py v3/runs/melee-v4-xxxx/seq_melee_v4 --json-out v3/runs/melee-v4-xxxx/diag.json
python v2/verify_24.py --gif v2/runs/v2-24fps-xxxx/mimo2_24fps.gif

# 换一套素材
python v2/analyze_continuity.py --frames-dir path/to/keys --count 12 --pattern "key_%02d.png"
```

### 2. `v2/morph.py` 支持自定义关键帧目录

`load_key(i, frames_dir=None)` 与 `get_flow(i, j, cache=True, frames_dir=None)` 新增可选 `frames_dir`。缓存键以帧内容为摘要，不同来源不会串缓存；默认值仍为 `v2/frames_key`，全部既有调用点不受影响。

### 3. 顺带的小修正（不改变成功路径的行为）

- `verify.py` / `verify_gifs.py` / `verify_v3.py`：默认 GIF 缺失时自动跳过或明确报错（旧版直接 `FileNotFoundError` 崩溃；`v2/mimo2_smooth.gif` 在当前工作区已不存在，旧版必崩）。
- `v2/verify_24.py`：运动 fps 统计加了除零保护；调色板实验在 plan 缺失时明确跳过。
- `v3/check_frames.py`：空白片（无墨迹）从 `ys.max()` 崩溃改为明确报错；`full_*` 切片缺失时给出再生指引（见下方"已知依赖"）。
- `v3/diag_seq.py`：目录不存在、目录无 PNG、帧全透明时均为明确报错；新增 `--json-out`。
- `v2/analyze_continuity.py`：帧目录/命名模式/数量参数化；删除未使用的 `scipy` 导入。

## 验证证据

- 单元/CLI 测试：`python -B -m pytest tests/ -q -p no:cacheprovider --tb=short` → **36 项全部通过**（第一阶段 15 项 + 新增 21 项：9 个脚本的"导入无副作用"检查、合成小图的 CLI 端到端、morph `frames_dir` 行为）。
- 真实历史素材冒烟（输出全部重定向到仓库外临时目录，工作区无新文件）：
  - `verify.py`、`v2/verify_gifs.py`、`v3/verify_v3.py`：6 张历史 GIF 全部成功出拼图。
  - `v2/check_quality.py`：色彩 MAE 2.8/255，3 张转场胶片正常（光流缓存命中）。
  - `v2/evaluate_schemes.py`：16 组转场完成评估并写出 JSON（缓存命中，证明 morph 签名变更未影响缓存键）。
  - `v2/analyze_continuity.py`：真实 16 关键帧全流程 9.2 s，IoU 最低 13→14（0.559），JSON 正常。
  - `v3/diag_seq.py`：默认 `seq_melee_v4` 20 帧，min IoU 0.773 / mean 0.851。
  - `v2/verify_24.py`：真实 68 帧 GIF，montage + 时序统计正常（motion avg 23.79 fps）。
- `git diff --check` 通过；`git status` 与第一阶段结束时一致，未产生新的仓库内文件。

## 已知依赖与限制（待确认/后续步骤）

- `v3/check_frames.py` 目前无法在当前工作区完整运行：`v3/tiles` 只有 72 张 `pair_*`，缺 64 张 `full_*`（两者都是 gitignore 的可再生中间产物）。需要先运行 `v3/extract_all.py` 再生切片——**但它会覆盖现有 `pair_*` 文件，未经确认不执行**。这是历史遗留的数据依赖，非本次改动引入。
- 五个构建入口的输入侧尚未参数化：其流水线仍是 Mimo 专用逻辑，硬编码参数的抽取属于第二步（main() 化）与第三步（案例配置）。
- `check_quality` 的颜色保真检查假设 GIF 第 1 帧对应关键帧 1，这一对应关系随案例配置（第三步）显式化。
- 真实重建 Mimo 的完整视觉验收（第二阶段第五步）尚未进行；本次冒烟只证明验证入口可用。
