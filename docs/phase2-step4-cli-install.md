# 第二阶段第四步：最小 CLI 与安装配置

日期：2026-09-13（基于第三步案例配置之上的增量改动）

## 目标与验收

目标：一个可靠 build 入口、参数校验、依赖声明、真实安装流程。

已达成：
- `gifkit build` 统一入口：按案例配置分发到五个构建脚本，参数透传，配置被篡改/缺失均有明确报错。
- 依赖声明进 `pyproject.toml`；在干净 venv 中完成 editable 安装并从 console script 端到端构建成功。
- 未做任何未被验证的声明：不含 license 字段（第六步决定）、不声称 PyPI 可安装、未验证除本机外的 Python 版本。

## 新增内容

### gifkit 包（三个小文件）

- `gifkit/cli.py`：`gifkit build --case NAME | --config PATH [透传参数...]`、`gifkit cases`、`gifkit --version`、`python -m gifkit`。
  - 分发依据：案例配置新增的 `"builder"` 字段（五个捆绑案例已补齐，指向对应构建脚本）。
  - CLI 把解析出的配置路径**追加到透传参数末尾**再交给构建脚本的 `main()`——构建脚本自带的 `--config` 默认值永远不可能悄悄盖掉用户的选择（有测试锁定此行为）。
  - `--case` 与 `--config` 互斥；未知案例列出全部可选项；`--out`、`--frames-dir`、`--no-tween-pngs` 等原样透传。
  - 设计为**仅支持 editable 安装**：CLI 从安装包旁边的仓库树加载构建脚本与 cases/；非 editable 安装会得到明确报错而非静默错误。
- `gifkit/__main__.py`、`gifkit/__init__.py`（版本号单一来源）。

### pyproject.toml

- 名称 `gifkit` —— **临时名**，正式名（GigKit/Gifkit/其他）仍待定；2026-09-13 查询 PyPI 上 `gifkit` 未被占用（404）。
- 运行依赖：numpy、pillow、scipy、scikit-image；可选依赖：`charts`（matplotlib，仅 v2/make_chart 用）、`test`（pytest）。
- `requires-python = ">=3.10"`；console script：`gifkit = "gifkit.cli:main"`。
- 刻意**不含** license 字段与 PyPI 分类器列表——授权方式和"已验证的版本范围"都是第六步/后续的事，不在元数据里预先声明。

## 安装与使用（本仓库现状）

```bash
# 在仓库内（推荐 --system-site-packages 以复用现有科学计算栈；或正常 venv 后 pip install -e .）
python -m venv --system-site-packages .venv-test
.venv-test/Scripts/python -m pip install -e . --no-deps --no-build-isolation
.venv-test/Scripts/gifkit cases
.venv-test/Scripts/gifkit build --case mimo_v4 --out path/to/out
```

`.venv-test/` 已加入 .gitignore；保留在仓库中可直接使用，也可删除后随时重建。

## 验证证据

- 测试：**70 项全部通过**（新增 8 项 CLI/打包测试：pyproject 元数据、案例清单、version/help、cases 列表、真实分发构建 v1、错误路径×4、morph 可导入性）。
- 真实安装链路：干净 venv → `pip install -e . --no-deps --no-build-isolation` 成功 → `pip show gifkit` 显示 0.1.0 → `.venv-test/Scripts/gifkit --version` / `cases` 正常 → `gifkit build --case mimo_v1 --out <仓库外临时目录>` 完整构建，产物 635.9 KB 与此前逐字节同尺寸 → `python -m gifkit --version` 正常 → 未知案例报错信息完整。
- `git diff --check` 通过；`.venv-test/` 与所有 runs 输出均在 .gitignore 内。

## 验证边界（诚实声明）

- **PyPI 完整依赖解析未验证**：venv 使用了 `--system-site-packages` 复用现有环境，`--no-deps` 跳过依赖下载。"在完全没有科学计算栈的机器上 pip install -e . 能否一次成功"仍属待确认（依赖本身都是常见包，风险低但未证）。
- **Python 版本只在本机 3.13 验证**：`>=3.10` 是按语法特性定的保守下限，未在 3.10/3.11/3.12 实测。
- **仅支持 editable 安装**：非 editable 安装会得到明确报错。真正的 wheel/数据打包（把 cases/ 与脚本装进包内）留待有真实需求时做。
- 正式包名未定；所有 `gifkit` 命名集中在一处（pyproject + gifkit/），改名成本已刻意压到最低。

## 下一步

第五步：完整流程与视觉验证——重建全部 Mimo 成品并逐帧目检（动作连贯性、深色背景透明边缘），然后接一套与 Mimo 不同的素材走通全流程。
