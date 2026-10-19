# 首页改版验证

## 第二轮交付：大胆的交互首页与更科学的研究说明

用户进一步要求增加示意图和动画、突破原有板块，并指定「01 / 探索平台」更具体、「02 / 从问题到证据」更科学。本轮已经实现：

- 全幅城市画布，居民沿路移动；支持城市、动态关系球、平行世界三个观察视角。
- 六个真实功能入口配上独立原生矢量场景、输入到产物路径与使用例子，并将本节前移。
- 人物认知循环、可切换家庭/工作/社区的关系网络，以及可操作的分岔示意。
- 六步研究方法流程、政策信息的对照设计示例、共同基线、配对效应公式、置信区间与稳健性检查。方法描述已经核对现有统计模块；明确居民互动与独立重复的区别，未生成或宣称任何真实效果。
- 全局动画暂停与持久化，减少动态效果支持；画布和 SVG 在离开视口或页面隐藏时停止持续动画。
- 保持中英文、明暗主题、手机导航、历史入口、资料和安装功能。

本轮验证：

- `python -m pytest tests/test_landing_browser.py tests/test_landing_frontend.py tests/test_theme_frontend.py -q`：**12 passed**。
- `python -m pytest --suite core -q --disable-warnings`：**489 passed, 1 skipped, 775 subtests passed**，跳过原因仍为可选 OpenAPI 校验依赖未安装。
- Ruff 检查、格式检查、JavaScript 语法检查、diff 空白检查、lint ratchet 通过；Ruff 与历史基线版本不同，ratchet 仍按原规则不执行总量门槛。
- 真实服务浏览器验证通过：1440px 桌面，390px、320px、768px 响应式布局，中英文/主题持久化、手机菜单、安装命令复制、六个实际功能 iframe、平行世界分区、禁用 JavaScript 和减少动态效果后的基础内容。首页未出现 JavaScript 异常。
- 截图和回归检查发现并修复：减少动态效果会将首屏入场动画停在透明首帧；全局恢复时误启动屏外 SVG；手机大标题拆开「世界」。
- 原预览服务在检查时已停止，已重新启动 `python generative_city_sim.py dashboard --port 8766`，当前服务可访问；没有启动仿真或模型调用。本条替代下文第一轮中「未重启用户服务」的状态。

最新截图位于 `output/playwright/homepage-bold-*.png`；浏览器检查脚本为 `output/playwright/verify-homepage-bold.cjs`。原第一轮检查记录保留如下，其中既有终端品牌图片检查失败仍属于未修改页面的边界。

---

日期：2026-10-17（Asia/Tokyo）。用户已选择 A「现代社会实验室」。修改留在本地工作区，未提交或部署。

## 完成内容

- 两个首页共用已跟踪的 `site/home/style.css`、`site/home/app.js`，修复正式首页依赖被忽略资源的问题。
- 新首屏、原生矢量城市/关系/平行世界示意、六个功能入口、研究流程，以及保留的评测、文档、安装说明、贡献者。
- 六个卡片均直达实际控制台功能；平行世界使用既有 `/console#worlds` 映射，定位到研究工作台的 worlds 分区。
- 中英文切换、共用的明暗主题控制、手机菜单、键盘操作、减少动画支持与无 JavaScript 的基础入口。
- 兼容旧页面的 `/#studio`、`/#settings`、`/#dashboard` 等入口，并保留查询参数；`#research` 保持首页内部章节含义。

## 验证结果

使用项目依赖完整的 `python`，系统 `python3` 缺少 numpy，不适合运行本项目测试。

- `python -m pytest tests/test_landing_frontend.py tests/test_theme_frontend.py -q`：7 passed。
- 首页、主题与品牌资源的组合检查：10 passed, 1 deselected。完整组合运行中，既有 `test_pages_do_not_reference_the_missing_brand_image` 因未修改的本地 `site/terminal/guess.html` 引用 `logo-emergent.png` 而失败；未改动该终端页面，也未把此项报告为通过。
- `python -m pytest --suite core -q`：489 passed, 1 skipped, 775 subtests passed。跳过原因是未安装可选 openapi-spec-validator；同时存在既有绘图字体警告。
- `python scripts/lint_ratchet.py`：通过，未增加检查项；当前 Ruff 与基线版本不同，总量门槛按脚本规则未执行。
- `python -m ruff check tests/test_landing_frontend.py`、格式检查、JavaScript 语法检查、`git diff --check`：通过。
- 代码复查发现旧哈希入口兼容问题，已先补失败回归测试、再修复并通过。

## 浏览器验证

在实际服务 `http://127.0.0.1:8766/` 使用独立 Playwright 会话验证：

- 1440px 桌面布局；390px、320px 中英文布局无横向溢出。
- 示意视角切换、Home 键切回首个视角，链接随视角更新。
- 语言与主题选择在刷新后保留。
- 手机菜单展开、Escape 关闭、选择内部链接后关闭。
- 安装命令复制成功。
- 逐个点击六张卡片，核对实际可见 iframe 的页面路径和 HTTP 200；确认平行世界标签处于选中状态。
- 历史入口携带查询参数正确跳转。
- 禁用 JavaScript 后标题、导航和六个功能链接仍可使用。
- 首页检查阶段未出现 JavaScript 异常。功能页仍有既有服务错误：当前运行进程的研究批次 API 返回 404，旧研究详情返回 500，以及功能页 favicon.ico 404；这不影响本次功能入口定位，但不代表这些页面的全部后端行为已验证。未重启用户服务，也未启动模型运行。

复核截图：

- `output/playwright/homepage-desktop.png`
- `output/playwright/homepage-features.png`
- `output/playwright/homepage-mobile-top.png`
- `output/playwright/homepage-mobile.png`
- `output/playwright/homepage-english-dark.png`

浏览器检查脚本保存在本地 `output/playwright/verify-homepage.cjs`。页面最终恢复中文浅色，服务保持运行。
