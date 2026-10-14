# 安装

## 系统要求

GAWorld 需要 **Python 3.11 或更高版本**。从 GitHub 安装时还需要 Git。先在终端确认：

```bash
python --version
git --version
```

建议为 GAWorld 创建独立的 Python 环境：

```bash
python -m venv .venv
```

macOS 与 Linux 激活环境：

```bash
source .venv/bin/activate
```

Windows PowerShell 激活环境：

```powershell
.venv\Scripts\Activate.ps1
```

## 使用 pip 安装

```bash
python -m pip install "git+https://github.com/wuchaozju/GAWorld.git@main"
```

该命令安装 GitHub `main` 分支中的 GAWorld 及其 Python 依赖。

## 从源码安装

开发或修改 GAWorld 时，克隆仓库并使用可编辑安装：

```bash
git clone https://github.com/wuchaozju/GAWorld.git
cd GAWorld
python -m pip install -e ".[dev]"
```

## 验证安装

```bash
python -m pip show gaworld
gaworld --help
```

## 创建工作区

```bash
gaworld init ./my-world
cd my-world
gaworld dashboard
```

在浏览器打开 <http://127.0.0.1:8766>。工作区保存运行代码、数据、配置和输出。

```{note}
直接运行 `gaworld dashboard` 时，首次启动会创建默认工作区 `~/.local/share/gaworld/workspaces/default`。使用 `gaworld init` 可以为不同项目指定各自的目录。
```

## 配置模型

本地单人使用在启动控制台的终端设置模型密钥；团队服务器用户登录后保存个人密钥。按 [模型与运行配置](models.md) 选择对应路径、测试连接，再设置默认模型与日程模型。

## 升级

```bash
python -m pip install --upgrade "git+https://github.com/wuchaozju/GAWorld.git@main"
```

已有工作区保留初始化时的代码版本。升级安装包后，在新目录初始化新版工作区，再迁移项目需要的数据：

```bash
gaworld init ./my-world-new
```
