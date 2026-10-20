# A「群体涌现」Logo 接入验证

日期：2026-10-17。用户已选定 A 并授权接入。源图沿用选定的透明 PNG；发布文件与源文件 SHA-256 一致。

## 实现范围

- 首页头部/页尾、控制台、功能页、回放页使用图标配既有文字；登录页和文档使用横向组合。
- 全站 HTML 的 favicon 指向选定图标，文档源配置和已生成页面同步更新。
- 两张 PNG 位于已有公开前缀 `site/auth/brand/`。未改变后端路由和资源权限。
- `site/brand.css` 控制尺寸、移动端布局及深色反白；嵌入控制台时隐藏重复品牌图标。

## 验证结果

- 品牌与主题测试：8 passed。
- 账号、鉴权和首页测试：34 passed。
- 核心套件：489 passed、1 skipped、775 subtests passed。跳过项为可选的 OpenAPI 校验依赖未安装。
- `python scripts/lint_ratchet.py` 通过。当前 Ruff 0.16.7 与基线 0.17.0 不同，因此工具未执行仓库总量约束。
- `git diff --check` 通过。
- Playwright 实际加载检查通过：首页 1440px / 390px / 320px、明暗主题、手机控制台、嵌入品牌去重、独立研究页、回放页、文档、登录/注册/重置和 favicon。
- 截图已检查：`output/playwright/logo-a-home-desktop.png`、`logo-a-home-mobile.png`、`logo-a-console-mobile.png`、`logo-a-research-light.png`、`logo-a-research-dark.png`、`logo-a-login.png`。

## 验证边界

本地未安装 Sphinx/Furo 等文档构建依赖，未重新构建文档；文档源与现有生成页面均已更新，现有页面图像加载通过。未运行真实仿真实验或模型调用。
