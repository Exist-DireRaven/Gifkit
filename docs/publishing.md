# 发布检查单（公开发布前必读）

## 执行记录

- **2026-09-13**：用 git-filter-repo 剥除历史素材路径并强推 `origin/main`。但被替换的
  旧提交在 GitHub 仍可通过直接 SHA 访问（服务端 GC 前），无法保证清除。
- **2026-09-14**：删除 GitHub 仓库并重建，本地丢弃旧 .git、以干净工作树重开单提交
  历史重新推送。素材（GIF/、mimo* 图像及衍生表）从未进入新历史；`.gitignore` 中
  素材规则在首次 add 之前已生效。此为素材泄露的最终解法，今后直接沿用本仓库即可，
  勿再向历史中添加素材。

以下为原始检查单，供将来再次发布参考。

本仓库的 git **历史**中仍包含 Mimo 图像素材（首个提交早于"素材不发布"的决定；
素材已从当前跟踪中移除并加入 .gitignore，但历史对象仍在）。公开发布（push 到
公共远端）之前必须完成以下步骤。

## 1. 重写历史，清除素材对象

使用 git-filter-repo（`pip install git-filter-repo`）。在发布克隆（建议直接复制
一份仓库再操作）上执行：

```bash
git filter-repo --invert-paths \
  --path mimo.png --path v2/mimo2.png \
  --path v3/gpt_full64.png --path v3/gpt_pairs72.png \
  --path v2/frames_key --path v2/frames_tween24 --path v2/key02_11 \
  --path-glob 'mimo*_*.gif' --path-glob 'mimo_loop*.gif' \
  --path v2/_chart_smoothness.png --path v2/_chart_trajectory.png \
  --path v2/_check_24fps.png --path v2/_check_key.png \
  --path v2/_strip24_02_03.png --path v2/_strip24_09_10.png --path v2/_strip24_13_14.png \
  --path v2/_verify_boxes.png --path v3/_aligned_sheet.png \
  --path v3/_check_mimo3_gun.png --path v3/_check_mimo3_melee.png --path v3/_check_v4.png
```

## 2. 验证历史中已无素材对象

```bash
# 任何 blob 的文件名都不应再匹配素材模式
git rev-list --objects --all | grep -iE '\.(gif)$|mimo|gpt_' || echo clean
# 图像 blob 抽查：列出所有剩余 png 的名字，人工确认无 Mimo 衍生物
git rev-list --objects --all | grep '\.png$'
```

注意：`docs/images/walker-dark.png` 是程序化生成素材的拼图，允许保留。

## 3. 其余检查

- [ ] `pip install git-filter-repo` 后重写历史；filter-repo 会移除全部远端配置（防误推），确认后再添加公共远端。
- [ ] `python -B -m pytest tests/ -q`：干净克隆上应通过（依赖本地素材的用例自动跳过）。
- [ ] PyPI：名称 `gifkit` 于 2026-09 查证未被占用；`python -m build` + `twine check` 后再上传（尚未执行过，当前仅支持 editable 安装）。
- [ ] Python 版本矩阵：声明的 >=3.10 仅实测过 3.13，发布前在 3.10–3.12 跑一遍测试。
- [ ] README 中的"仅验证 editable / 仅 3.13"声明按届时情况更新。
