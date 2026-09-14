# Gifkit

把不规则、AI 生成或手绘的 sprite sheet 变成流畅的循环 GIF 动画。核心完全离线，
不依赖任何在线服务；代码以 MIT 许可发布。[walker 示例](examples/walker/README.md)
随仓库即可运行；内置的 Mimo 案例配置展示真实生产用法（其图像素材**不随仓库分发**，
见[许可证与素材](#许可证与素材)）。

## 它解决什么问题

逐格摆拍式 sprite sheet 的动作跨度大、播放起来一顿一顿。Gifkit 在关键帧之间
**按真实运动轨迹合成中间帧**（不是交叉淡化），再把节奏、调色、透明化一次性做好：

- **光流中割**：双向稠密光流 + 全局位移预补偿（相位相关）+ 预乘 Alpha 变形，
  中间帧沿运动轨迹插值；单源变形避免叠影。
- **节奏设计**：关键帧停顿（dramatic beats）单独保留，运动帧落在 1/fps 网格上，
  按 10 ms 累积取整保持运动段帧率精确。
- **人工艺术选择保留在配置里**：每个转场补几帧、哪里停顿停多久、用哪个姿势——
  这些是动画判断，不交给算法猜。它们住在 `cases/*.json`，不在代码里。
- **校验内建**：GIF 回读拼图（白/棋盘/深色背景）、相邻帧轮廓 IoU 与光流连贯性
  度量、色彩保真 MAE。默认只检测报告，不自动"修复"。

## 快速开始

需要 Python ≥3.10（本机仅在 3.13 验证过）与 numpy、pillow、scipy、scikit-image。

```bash
# 1) 从仓库安装（editable 方式；尚无 PyPI 包）
pip install -e .

# 2) 构建内置案例（产物进 gitignored 的 runs/ 独立目录，不覆盖任何历史文件）
gifkit cases                        # 列出内置案例
gifkit build --case mimo_v4         # 20 帧格斗连段
gifkit build --case mimo_v2_24fps   # 68 帧 24fps 连击循环

# 3) 换成自己的素材：写一份案例配置即可，核心算法零改动
gifkit build --config my_case.json --out path/to/out

# 4) 校验产物（拼图回读；--bg dark 用于暴露透明边缘问题）
python verify.py runs/<新运行目录>/xxx.gif --bg dark
```

不安装也能用：直接 `python make_gif.py`、`python v3/build_melee_v4.py` 等
（脚本方式与 CLI 等价）。第二套素材的完整演示见
[examples/walker](examples/walker/README.md)。

> 注：`mimo_*` 案例引用的图像素材不随仓库分发（见文末）。在完整克隆的工作副本里
> 可直接构建；否则把配置指向你自己的素材即可。

## 图形界面与免安装 exe

不想碰命令行：

```bash
gifkit gui          # 打开图形窗口（需 pip install -e . 安装过）
```

窗口就一个页面：选一张整齐排列的 sprite sheet → 点"一键生成 GIF" →
点"打开输出文件夹"。行列数自动检测（也可手动指定）、白底和假透明棋盘格
自动抠掉、画布按角色实际大小自动适配，构建日志实时滚动。
内置案例的构建走命令行（`gifkit build --case`）。

打包成免安装的 Windows 程序（输出在 `dist/Gifkit/`，整个文件夹拷走即可用，
双击 `Gifkit.exe` 进图形界面）：

```bash
pip install pyinstaller
python -m PyInstaller Gifkit.spec --noconfirm
```

打包要求本地存在 walker 示例素材（`python examples/walker/make_material.py`
先生成），spec 会自动带上可生成的示例；体积主要来自 numpy/scipy 的 MKL 运行库，
在 Anaconda 环境约 600 MB。

## 工作原理

```
sprite sheet ──分割/对齐──▶ 关键帧序列 ──连贯性分析──▶ 转场计划(停顿+补帧数)
                                │                          │
                                └──────▶ 光流中割 + 节奏排布 + 统一调色板 ◀┘
                                                    │
                                              GIF(白底/透明/小图) ──▶ 回读校验
```

关键实现都在 `v2/morph.py`（中割库）与各构建脚本的纯函数里；
人工选择（PLAN/NB/HOLD、帧序挑选）全部在 `cases/`。

## 内置案例

**随仓库可运行**（素材由脚本确定性生成）：

| 案例 | 配置 | 内容 |
|---|---|---|
| `walker_grid` / `walker_loop` | [examples/walker](examples/walker/README.md) | 3×4 网格表 / 白底瓦片两条路径的 12fps 步行循环 |

![walker 步行循环（深色背景校验拼图）](docs/images/walker-dark.png)

**配置示例**（展示真实生产用法；图像素材不随仓库分发）：

| 案例 | 内容 |
|---|---|
| `mimo_v1` | 4×4 网格表，16 个独立姿势循环 |
| `mimo_v2_key` / `mimo_v2_24fps` | 16 关键帧：纯关键帧版 / 68 帧 24fps 连击循环 |
| `mimo_v3` | 72 张中割瓦片装配的枪械 38 帧 + 格斗 14 帧两条循环 |
| `mimo_v4` | 20 帧深度优化连段 |

历史产物清单与 v1→v4 的演进指标见 [docs/mimo-history.md](docs/mimo-history.md)。

## 能力清单

**已实现**（有测试与重建证据）：
配置驱动构建（5 类案例）、`gifkit build/cases` CLI、光流中割库（内容寻址缓存）、
24fps 网格排布、统一调色板 + 透明索引、9 个验证/分析工具（含深色背景检查）、
全部 26 个入口导入无副作用、材质边界显式报错（空帧/越界/超尺寸）、
72 项自动化测试、真实重建与历史逐字节同尺寸。

**规划中**（未实现，勿当事实引用）：PyPI 安装、`gifkit verify` 子命令、
多格式输出（APNG/WebP）、AI 补帧插件接口、封闭白底区域检测报告、
边缘修复、综合质量评分、GPU 加速、多 Python 版本/干净环境安装验证。

**实验性**：`evaluate_schemes.py` 的 IoU 评分选方案——轮廓重合度只是平滑度的
粗略代理，跳跃、停顿、快速出拳可能是有意的动作，不要盲信指标（见已知限制）。

## 已知限制

- 透明 GIF 在深色背景上有 1–2px 浅色镶边（白底素材半透明边缘的混色，
  历史成品相同；对比拼图保存在本地工作树，不随仓库分发）。
- 瓦片路径的边界洪填充抠底无法移除四肢围出的**封闭**白色区域。
- 光流中割对大跨度姿势（IoU < 0.6）效果有限；此时应增加关键帧而非补帧。
- 仅验证过 editable 安装与 Python 3.13。

## 开发

```bash
python -B -m pytest tests/ -q -p no:cacheprovider --tb=short   # 72 项，约 4 秒
```

测试全部使用合成小图与临时目录，不重建动画、不触碰素材；在缺少 Mimo 素材的
克隆上，依赖素材的少数用例会自动跳过。

## 文档索引

| 文档 | 内容 |
|---|---|
| [docs/phase1-fixes.md](docs/phase1-fixes.md) | 正确性修复（调色板/路径/覆盖/缓存） |
| [docs/phase2-step1-io.md](docs/phase2-step1-io.md) … [step5](docs/phase2-step5-visual-and-second-case.md) | 工程化五步：IO 统一 → 入口拆分 → 配置抽取 → CLI/安装 → 视觉验证 |
| [docs/mimo-history.md](docs/mimo-history.md) | Mimo v1–v4 历史产物与指标 |
| [examples/walker/README.md](examples/walker/README.md) | 第二套素材演示 |

## 许可证与素材

- **代码：MIT 许可**（见 [LICENSE](LICENSE)），2026 起。
- **Mimo 图像素材不随仓库分发、不在 MIT 许可范围内**：`mimo*.png`、`gpt_*.png`、
  各 `mimo*_*.gif` 及派生帧/拼图仅存在于本地工作副本（已被 .gitignore 排除）。
  案例配置（`cases/mimo_*.json`）只含时序与布局参数，随代码发布。
- 公开发布本仓库前需重写 git 历史以清除早期提交中的素材文件，
  步骤见 [docs/publishing.md](docs/publishing.md)。
