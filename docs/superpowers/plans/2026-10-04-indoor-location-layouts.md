# 地点室内布局实施计划

**Goal:** 根据地点用途展示不同的精细像素布局。
**Architecture:** 现有 spatial-tree 保存蓝图与稳定分类，Phaser 只渲染；IndoorView 选择全部实际地点；运行和回放共用实现。
**Tech Stack:** 原生 JavaScript、Phaser、Node 测试与 pytest。

- [x] 在 tests/indoor-pixel.test.js 增加失败测试：用途识别、未知用途、几何、镜像稳定性、地点选择器。运行确认失败。
- [x] 修改 site/simviz/spatial-tree.js，扩充蓝图、优先分类和稳定变体；更新旧别名测试。
- [x] 修改 site/simviz/phaser-app.js 新增所需家具和标签；修改 site/dashboard/indoor-view.js 展示类型、列出 kind=place 地点。
- [x] 更新三个页面脚本版本，运行 Node/pytest 相关回归。
- [x] 浏览器验证运行与回放的不同用途、地点稳定及隐藏恢复；保存截图。
- [x] 请求代码审查并处理问题，记录验证结果。

验证完成：41 项 Node 检查、spatial-tree 几何零失败；相关 pytest 9 项通过；core 472 项通过、1 项可选 OpenAPI 验证依赖跳过、671 subtests 通过。两项审查意见（用途标签优先级、休息坐姿）均有新增回归并修复。浏览器验证 8765 控制台运行/回放及 8767 离线预设展示。脚本缓存版本为 pixel10。
