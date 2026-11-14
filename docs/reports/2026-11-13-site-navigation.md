# 网站布局与导航优化交付记录

日期：2026-11-13。范围：两份首页入口、控制台外壳、导航文案及回归测试。改动保留在当前工作区，未提交或部署。

## 实际变化

- 首页主导航整理为“了解 GAWorld / 探索功能 / 研究社区 / 文档”，突出“进入实验室”。辅助菜单容纳外观、语言、GitHub 和注册；桌面登录独立可见。
- 手机保留品牌、实验室入口和菜单按钮；展开后完整显示导航与辅助操作。支持焦点进入、Escape 返回、页面背景隔离及跨屏宽状态清理。
- 首页顶栏与内容容器对齐，收紧首屏和章节间距，保留原有图示、视频和功能卡片的分级网格。
- 控制台工具菜单集中展示外观、语言、账号及独立窗口操作；世界切换和管理保持直接可达。手机顶栏继续显示当前页面名称，世界信息单独占一条紧凑上下文行。
- 侧栏按当前语言显示名称，增强分组和选中项；手机抽屉增加关闭按钮、焦点循环和背景隔离，桌面保留折叠记忆。
- 清理 `site/city-lab.css` 中与控制台新布局冲突的旧覆盖。新界面使用既有深浅色 token，中英文新增词条一致。
- 更新两处旧测试假设：simviz 已是 analytics 的别名，旧静态回放页已是重定向入口。测试现在验证实际跳转与目标页面品牌资源，保留旧入口兼容性。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| 首页、品牌与浏览器回归：`python -m pytest tests/test_landing_frontend.py tests/test_brand_assets.py tests/test_landing_browser.py -q` | **67 passed**，其中浏览器测试 53 项 |
| `node --test site/community/navigation.test.js` | **6 passed** |
| 协作前端、公共资源、文档、i18n 扩展回归 | 56 passed、1 skipped、3 failed；失败均为已有 locale 缺项/顺序断言，见下文 |
| `python -m pytest --suite core -q` | 514 passed、1 skipped、1 failed；另 980 subtests passed，见下文 |
| 两个修改过的 JavaScript 的 `node --check` | 通过 |
| 修改过的 Python 测试的 Ruff 检查及格式检查 | 通过 |
| `python scripts/lint_ratchet.py` | 通过，修改文件没有新增 lint 问题；全库总量因 Ruff 与基线版本不同而未强制比较 |
| `git diff --check`；两份首页逐字比较 | 通过 |

浏览器覆盖 1440、1024、768、390、320px，首页及控制台均覆盖中英文 × 深浅色全部组合。控制台包含长世界名/账号名、单用户、普通成员和管理员状态。账号与世界接口使用固定测试响应，子页面使用静态测试文档，未修改真实账号或世界。

交互检查包括：菜单开关、Escape 和焦点返回；方向键后 Tab/Shift+Tab 循环；账号入口不可见时的侧栏焦点回退；手机/桌面切换清理；世界管理及选择请求；页面草稿缓存、前进后退、折叠记忆以及 worlds/simviz 旧链接和查询参数。

独立代码审查发现并修复了“方向键移动到非活动项后 Tab 可离开抽屉”的问题。补充复现测试后，审查者复核通过，未报告其他待处理问题。

## 尚存的仓库测试问题

1. `tests/test_ownership.py::StoresTest::test_serious_game_seat_links`：预期通过 seat token 返回 200，实际返回 404。单独运行也可复现；相关后端代码和该测试与 HEAD 一致，本轮未修改。
2. i18n 三条失败断言：中文 locale 缺少英文已有的 26 个研究/严肃游戏词条，并因此存在键顺序差异。直接比较 HEAD 和工作区 JSON，缺项集合完全一致。本次新增的 9 个 `console.*` 词条在两种语言中均存在且顺序一致。
3. 核心套件的一项跳过是因为未安装 `openapi-spec-validator`；i18n 的一项跳过是已有键未按字母排序。

本轮没有修改这些无关业务逻辑或补译研究工作台词条，因此不能宣称全库测试全部通过。

## 视觉记录

使用本机运行中的单用户网站进行 Chromium 桌面/手机视口截图与目视检查；自动化权限场景使用测试响应。本轮未进行 Safari、Firefox 或真实手机硬件验证，也未运行付费模型调用。

截图与完整测试日志保存在 `output/playwright/navigation-2026-11-13/`（本地产物，不纳入提交）：

- [首页调整前 · 桌面](../../output/playwright/navigation-2026-11-13/home-before-desktop.png) / [调整后 · 桌面](../../output/playwright/navigation-2026-11-13/home-after-desktop.png)
- [首页调整前 · 手机](../../output/playwright/navigation-2026-11-13/home-before-mobile.png) / [调整后 · 手机](../../output/playwright/navigation-2026-11-13/home-after-mobile.png)
- [手机首页展开导航](../../output/playwright/navigation-2026-11-13/home-menu-mobile.png)
- [控制台调整前 · 桌面](../../output/playwright/navigation-2026-11-13/console-before-desktop.png) / [调整后 · 桌面](../../output/playwright/navigation-2026-11-13/console-after-desktop.png)
- [控制台调整前 · 手机](../../output/playwright/navigation-2026-11-13/console-before-mobile.png) / [调整后 · 手机](../../output/playwright/navigation-2026-11-13/console-after-mobile.png)
- [深色手机工具菜单](../../output/playwright/navigation-2026-11-13/console-tools-dark-mobile.png) / [深色手机导航抽屉](../../output/playwright/navigation-2026-11-13/console-drawer-dark-mobile.png)
