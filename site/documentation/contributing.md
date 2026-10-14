# 为 GAWorld 贡献

你可以通过代码、测试、文档、可复现的问题报告和研究示例参与 GAWorld。

## 报告问题

在 [GitHub Issues](https://github.com/wuchaozju/GAWorld/issues) 提供版本、运行环境、复现步骤、预期结果和实际结果。日志中保留定位问题所需的信息，并移除密钥与个人记录。

## 提出功能建议

说明使用场景、需要完成的操作，以及现有功能遇到的具体问题。研究相关建议可以附上变量、实验条件和结果形式。

## 提交修改

从当前 `main` 创建功能分支，完成修改和检查后提交到 `Dev` 审查。维护者将验证后的集成提升到 `main`。

```bash
git clone https://github.com/wuchaozju/GAWorld.git
cd GAWorld
python -m pip install -e ".[dev]"
git switch -c feat/your-change
```

## 提交前检查

1. 描述具体问题、修改后的行为与验证结果。
2. 为新增行为提供有意义的测试，模型调用使用 mock。
3. 运行核心测试和与改动有关的用例。
4. 检查提交范围，保留相关代码、文档和测试。
5. 说明涉及模型语义、数据格式、账号隔离或居民 ID 映射的变化。

```bash
python -m pytest --suite core
git diff --check
```

## 添加模块

新的 Python 实现放在 `gaworld/` 子包中。新增仿真子系统通过插件装配；涉及默认仿真行为变化时，按仓库约定处理可比性版本。

## 改进文档

在线文档源文件位于 `site/documentation/`。修改实际步骤、命令或参数时，同时检查代码对应入口，并完成文档构建。构建命令见 [开发指南](development.md)。

## 贡献者

查看 [GitHub 贡献记录](https://github.com/wuchaozju/GAWorld/graphs/contributors)。

## 项目约定

[CONTRIBUTING.md](https://github.com/wuchaozju/GAWorld/blob/main/CONTRIBUTING.md) 与 [AGENTS.md](https://github.com/wuchaozju/GAWorld/blob/main/AGENTS.md) 包含分支、代码、测试和审查要求。
