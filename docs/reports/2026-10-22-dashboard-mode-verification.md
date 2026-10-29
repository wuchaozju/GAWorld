# Dashboard 多用户启动开关

日期：2026-10-22。实现用户确认的明确启动参数语义。

## 使用

```bash
# 默认单用户；不因已有账号库或旧注册环境变量自动开启登录限制
python generative_city_sim.py dashboard
python generative_city_sim.py dashboard --multi-user False

# 开启账号登录、用户隔离与功能访问限制
python generative_city_sim.py dashboard --multi-user True
```

另外两个入口 `python dashboard_server.py`、`python -m gaworld.apps.dashboard_server` 使用同一参数解析器。兼容 `--multi_user`；裸 `--multi-user` 等同于 True。

开启前若尚未设置管理员，使用 `python -m gaworld.accounts init --admin <用户名>` 交互初始化。开启模式缺少账号库或管理员时启动失败，不会退回匿名单用户模式。运行中账号库失效继续由请求和健康检查返回 503。

## 行为

- 启动参数默认 False，优先于已有账号数据库、`GAWORLD_REQUIRE_ACCOUNTS`、注册策略和父进程遗留模式环境。
- 单用户模式保留原有研究、仿真、居民、游戏、设置等功能，不使用账号隔离、验证或按人配额；忽略旧账号/世界 Cookie，不写账号调用计数。原有独立运维 token 配置仍保留。
- 多用户模式下，匿名功能页 GET/HEAD 跳转登录，匿名读写功能 API 返回 401。用户登录成功后可进入权限允许的功能。
- 首页、登录注册与公共社区维持公开。首页样式及脚本同步列入公共静态路径；目录穿越仍按实际解析的路径鉴权。
- 进程模式传入后台任务和子进程；服务结束或启动失败后恢复调用方环境。
- 保留模块入口的 canonical 导入，避免 `__main__` 和正式模块出现两套用户/世界上下文。
- 主仿真 CLI 仅替换参数装配与启动转发，没有增加内联子系统逻辑；文件维持 4264 行。

## 验证

- 核心套件：489 passed、1 skipped；跳过项为未安装的可选 OpenAPI schema 校验库，另有既有中文绘图字体警告。
- 新增模式检查：14 passed，包含三个启动入口 × 两种模式的真实子进程和 HTTP 请求验证。
- 账号、世界、部署保护、行数预算与社区接口回归：72 passed。
- 模式、鉴权、邮箱、属主与部署专项：69 passed。
- lint ratchet 与 `git diff --check` 通过；Ruff 版本差异仅影响全仓基线总数比较，逐文件检查通过。
- 独立复查已验证参数优先级、子进程继承、canonical 入口和环境恢复，无已知阻断问题。

以上测试集有重叠，不相加为总数。验证使用临时账号库及测试账号，不修改生产账号、不运行真实模型实验。

部署说明同步更新于 `docs/COMMUNITY.md`、`docs/SERVER_DEPLOYMENT.md` 与 `deployment/multi-user/README.md`；多用户 systemd 配置显式添加 `--multi-user True`，防止升级后误用默认单用户模式。
