# 工作空间与主网站融合

完成日期：2026-11-14。承接此前网站布局优化，落实用户要求将 `/workspace` 融合进主网站。

## 原因与变化

此前 `/workspace` 只在已登录个人账号后重定向到控制台；用户提供的 8766 服务处于单用户模式，因此页面一直保留社区独立顶栏和侧栏，并显示账号登录提示。

- `/workspace`、`/workspace/` 和旧静态工作空间地址统一进入 `/console#workspace` 或对应个人视图，保留查询参数及定位信息。
- 首页顶栏“进入实验室”和首屏主要入口指向统一空间总览。
- 工作空间模板删除独立顶栏和侧栏，与仿真、研究等页面共用控制台的导航、主题、工具菜单和移动抽屉。
- 单用户模式提供本地研究、仿真、城市、人口、居民编辑和结果分析入口；不请求需要个人账号的 overview API。
- 账号成员继续读取原有个人研究、世界、发布等内容，权限与世界隔离逻辑保持原有实现。
- 令牌管理员没有个人账号 ID，使用管理员概览及明确说明；不会请求并遭到个人 overview API 的 401 拒绝。
- 单用户和令牌管理员打开个人内容深链接时，在同一外壳中显示账号要求及返回总览入口，不把无关总览冒充个人内容。原 URL 和参数保留。
- 新增概览和提示文案提供中英文，跟随控制台语言和深浅色切换。

## 验证

`python -m pytest tests/test_landing_browser.py tests/test_landing_frontend.py tests/test_brand_assets.py tests/test_community_api.py -q`：**78 passed**。

新增工作空间浏览器场景覆盖单用户、普通成员、令牌管理员 × 桌面/手机。检查统一外壳、无重复顶栏/侧栏、无嵌套控制台、研究入口跳转和返回、参数保留、个人内容提示、主题/语言传播及无个人账号时不调用私人 API。HTTP 测试验证个人页面与 API 的原有登录权限仍生效。账号状态使用测试响应或临时数据库，未修改真实账号、世界或研究数据。

`site/community/common.test.js` 与 `site/community/navigation.test.js` 的 13 项 Node 测试通过。修改脚本语法检查、Ruff lint/格式检查、lint ratchet、`git diff --check` 以及两份首页一致性检查通过。

独立审查发现并推动修复令牌管理员概览问题；修复后复核通过，无剩余可操作问题。

已在用户提供的 `http://127.0.0.1:8766/workspace` 实际验证：地址进入 `http://127.0.0.1:8766/console#workspace`，显示统一导航和可用的本地概览。静态资源直接生效，无需重启后端。本次没有重新运行全库核心套件；上一轮记录的无关核心/i18n 失败见 [网站导航验证报告](2026-11-13-site-navigation.md)。

## 截图与交付

截图和日志仍存放在开始执行时建立的 `output/playwright/workspace-integration-2026-11-13/`：

- [融合前](../../output/playwright/workspace-integration-2026-11-13/before.png)
- [融合后桌面](../../output/playwright/workspace-integration-2026-11-13/after-desktop.png)
- [融合后手机](../../output/playwright/workspace-integration-2026-11-13/after-mobile.png)

变更保留在当前工作区，未提交、未部署；浏览器验证使用 Chromium，未声称完成其他浏览器或真实手机硬件测试。
