# walker 示例：第二套素材

一个完全程序化生成的步行循环角色，与 Mimo 没有任何共同参数：3×4 网格（非 4×4）、
160px 格子、白底瓦片（非透明底）、12 fps 步行（非 24 fps 格斗）。
它证明"换素材不改算法"，同时充当仓库里无授权问题的可公开素材。

## 用法

```bash
python examples/walker/make_material.py     # 生成素材（sheet、boxes、tiles）
gifkit build --case walker_grid             # 网格路径 → runs/walker-grid-*/
python v3/build_v3.py --tiles-dir examples/walker/tiles --out-dir examples/walker \
       --tiles-count 16 --frames-per-block 8 --canvas 320 320 --baseline 296 --target-height 180
gifkit build --case walker_loop             # 瓦片路径 → v3/runs/walker-loop-*/
```

素材由 `make_material.py` 确定性生成（无随机），生成物已 gitignore；
案例配置在 `cases/walker_grid.json` 与 `cases/walker_loop.json`。

## 已知现象（继承自 v3 抠底算法，非 bug）

瓦片路径的边界洪填充只移除**与图像边界连通**的白底。当姿势的四肢与躯干
围出封闭白色区域时（如两腿交叉的帧），该区域会被保留为不透明白色，
在深色背景上显示为小的白色楔形。Mimo 的 GPT 素材同样存在此现象。
"检测/报告封闭背景区域"是未来显式修复能力的候选。
