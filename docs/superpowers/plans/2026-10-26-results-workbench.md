# Results Workbench Implementation Plan

**Goal:** 合并回放与分析，让同一次运行的画面、居民状态、曲线与事件使用统一时间。

**Architecture:** 在现有 analytics.html 中挂载独立回放工作区，保留专题统计和导出。纯数据模块提供运行合并、逐帧状态曲线、事件索引；UI 控制器拥有唯一运行和帧状态；现有 Analytics 通过同页控制器按需加载。

**Tech Stack:** 原生 HTML/CSS/JavaScript、现有 CityMapView/IndoorView、Node test runner、pytest。

## 1. 数据契约与测试
- [x] 新增 `site/dashboard/results-core.test.js`，覆盖运行副本合并及别名、不同世界不合并、不等距时间轴、缺失值与居民、重复事件、无帧。
- [x] 运行 `node --test site/dashboard/results-core.test.js`，验证缺失模块失败。
- [x] 新增 `site/dashboard/results-core.js`，实现并通过上述测试；所有动态文本安全转义在 UI 层完成。

## 2. 同页工作台
- [x] 新增 `site/dashboard/results-workbench.js` 和 `.css`；在 `analytics.html` 放入统一页首、筛选、回放、统计和系统三视图，复用地图与室内依赖。
- [x] 修改 `analytics.js`：受控加载、请求序号隔离、选中居民同步、报告仅包含统计内容、清除切换残留。
- [x] 核对 DOM id、事件绑定与各空态，运行 Node 与相关 pytest。

## 3. 兼容与文案
- [x] 在 `site/community/navigation.js` 将 simviz 解析为 analytics；控制台删除重复入口并更新中英文标题。
- [x] 旧 `site/simviz/index.html` 保留查询和 hash 重定向；更新针对旧页面结构的回归测试，新增规范入口与兼容参数测试。
- [x] 中英文工作台文案随既有语言事件更新；所有自定义色彩定义深色 token。

## 4. 实际验收
- [x] 用本地真实存档验证拖动、逐帧、播放停止、刷新保留、居民与事件跳转、曲线、专题导出和系统权限。
- [x] 检查桌面浅／深色与英文；保存最终截图。
- [ ] 390px 真实窄屏验证：浏览器尺寸覆盖未生效，已在验收记录中披露。
- [x] 运行 `pytest tests/test_replay_runs.py tests/test_dashboard_analytics.py`、Node 工作台／导航／导出测试、`pytest --suite core`、差异与 lint 检查，记录既有失败。

验收细节见 `2026-10-26-results-workbench-validation.md`。最终全仓 lint ratchet 通过，未修改无关文件。
