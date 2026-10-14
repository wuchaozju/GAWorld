# 开发与贡献

从 `main` 创建功能分支，完成修改与检查后提交到 `Dev` 审查。维护者将验证后的集成提升到 `main`。

## 准备开发环境

```bash
git clone https://github.com/wuchaozju/GAWorld.git
cd GAWorld
python -m pip install -e ".[dev]"
git switch -c feat/your-change
```

## 定位代码

| 目录 | 内容 |
| --- | --- |
| `gaworld/` | 正式运行实现 |
| `gaworld/settings/` | 配置片段 |
| `gaworld/kernel/` | 微内核、事件总线与插件注册 |
| `gaworld/plugins/` | 内置插件装配 |
| `gaworld/apps/` | 控制台服务与 HTTP 接口 |
| `gaworld/client.py` | Python HTTP 客户端 |
| `site/` | 控制台与可视化界面 |
| `tests/` | 自动化测试 |
| `data/` | 初始输入与居民资料 |

新增运行逻辑放在 `gaworld/` 中；新增仿真子系统通过插件接入。新增控制台接口时，同步更新 `gaworld/apps/openapi.py`。

## 运行检查

提交前运行核心测试和与改动相关的用例：

```bash
python -m pytest --suite core
git diff --check
```

需要完整覆盖时运行：

```bash
python -m pytest --suite full
```

核心套件覆盖主要仿真路径，完整套件覆盖更广的模块与集成场景。测试耗时随环境和用例变化；结果应记录对应的提交。

## 提交修改

1. 描述具体问题、修改后的行为和验证结果。
2. 为新增行为补充有意义的测试，模型调用使用 mock。
3. 检查提交内容，保留与本次修改相关的源码、文档和测试。
4. 对模型语义、数据格式、账号隔离与居民 ID 映射的修改作出说明。

## 项目参考

- [贡献指南](https://github.com/wuchaozju/GAWorld/blob/main/CONTRIBUTING.md)：分支、审查与协作流程。
- [仓库约定](https://github.com/wuchaozju/GAWorld/blob/main/AGENTS.md)：目录、命名、测试与提交要求。
- [测试说明](https://github.com/wuchaozju/GAWorld/blob/main/docs/TEST_CASES.md)：套件划分与用例覆盖。
- [更新日志](https://github.com/wuchaozju/GAWorld/blob/main/CHANGELOG.md)：版本变更记录。

## 构建文档

文档源文件位于 `site/documentation/`：

```bash
python -m pip install -r site/documentation/requirements.txt
python -m sphinx -W -b html site/documentation /tmp/gaworld-docs
python site/documentation/publish.py /tmp/gaworld-docs site/home/docs
```

构建后检查目录、页内链接、搜索与代码示例。

## 报告问题与提出建议

在 [GitHub Issues](https://github.com/wuchaozju/GAWorld/issues) 提供版本、运行环境、复现步骤、预期结果与实际结果。日志中保留定位信息，并移除密钥与个人记录。

功能建议说明使用场景、需要完成的操作以及现有功能遇到的问题。研究建议可以附上变量、条件和希望得到的结果形式。

## 贡献者

项目的代码与文档贡献记录见 [GitHub Contributors](https://github.com/wuchaozju/GAWorld/graphs/contributors)。
