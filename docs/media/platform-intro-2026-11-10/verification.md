# 交付核对

核对日期：2026-11-11。制作起始日期：2026-11-10。

## 首页入口

- `site/index.html`：发现 3 个目标仓库链接，导航与页脚的新窗口链接带 `noopener noreferrer`。
- `site/home/index.html`：发现 3 个目标仓库链接，导航与页脚的新窗口链接带 `noopener noreferrer`。

本次没有修改首页或控制台代码，入口已满足指定仓库地址。

## 图文材料

- 7 张 PNG 均为 1920 × 1080，7 个 SVG 均通过 XML 解析。
- 已查看全部画面联系表，并放大检查总览图与采访图；修正采访图标签间距、文字箭头的字体兼容性。
- 文档中的相对交付链接及内容依据链接已检查存在。
- 旁白为 9 段、约 670 个汉字，180 秒为含界面展示停顿的剪辑目标，尚未录制配音。
- 所有图片标明功能示意，不以图中的连线或节点作为研究结果。

## 现有首页检查

运行 `python -m pytest tests/test_landing_frontend.py -q`：4 通过，2 失败。

两条失败均来自 `test_homepage_links_directly_to_feature_views`（两份首页各一次）：测试要求控制台存在字面量 `id: "simviz"`；当前 `site/console/console.js` 已将 `simviz` hash 转到 `analytics`。首页及该控制台文件均无本次差异（`git diff --stat -- site/index.html site/home/index.html site/console/console.js` 为空）。本次记录现状，未扩展到导航或测试迁移。

范围：本次仅新增此目录内的介绍材料，不运行新的仿真实验、不部署、不生成成片。
