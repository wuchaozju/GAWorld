# 模型与运行配置

模型配置决定居民使用哪个服务生成日程、行动和回答。先按自己的使用方式配置密钥，再选择默认模型与日程模型。

## 选择配置方式

| 使用方式 | 密钥放在哪里 | 配置作用于哪里 |
| --- | --- | --- |
| 本地单人控制台 | 启动控制台的终端环境变量 | 工作区的模型后端与运行配置 |
| 团队服务器 | 登录后在“我的 API Key”保存 | 个人密钥；仿真参数保存在当前世界 |
| 本地命令行 | 执行命令的终端环境变量 | 当前工作区配置及命令行覆盖项 |

“我的 API Key”在服务器已配置 `GAWORLD_LLM_SECRETS_PATH`、且用户登录后显示。本地单人模式直接按下面的环境变量方式接入；命令行独立读取环境与配置。

(local-model)=
## 本地单人：接入一个模型

本例使用一个 OpenAI 兼容服务。准备服务商提供的 **Base URL、模型 ID、API Key**，给后端取名 `tutorial`。

### 1. 在终端设置密钥并启动控制台

macOS / Linux：

```bash
export GAWORLD_TUTORIAL_KEY="替换为你的 API Key"
gaworld dashboard
```

Windows PowerShell：

```powershell
$env:GAWORLD_TUTORIAL_KEY="替换为你的 API Key"
gaworld dashboard
```

环境变量属于当前终端及其启动的进程。已经运行的控制台需要重新启动，才能读取后来设置的变量。

### 2. 新增后端

打开控制台的 **配置 → 模型 → 新增后端**，填写：

| 字段 | 本例填写 | 作用 |
| --- | --- | --- |
| 后端名称 | `tutorial` | GAWorld 内部选择这个后端的名称 |
| 协议 | OpenAI 兼容 | 与服务商提供的协议一致 |
| Base URL | 服务商给出的完整 API 基础地址 | 请求发送到此地址 |
| 模型 ID | 服务商支持、且账号可调用的模型名称 | 传给服务商的模型标识 |
| 密钥环境变量 | `GAWORLD_TUTORIAL_KEY` | 填变量名；变量的值已在终端设置 |

保存后点击测试。测试成功表示当前后端可以完成一次短调用。

### 3. 选择默认模型与日程模型

回到仿真页面，把 **默认 LLM** 与 **日程 LLM** 都设为 `tutorial`，点击 **保存配置**。重新打开配置，确认两个选择仍为 `tutorial`，然后进行 [第一次仿真](quickstart.md)。

Ollama 后端使用其服务地址与已加载的模型名称，可直接测试，无需填写云服务密钥。Anthropic 兼容服务选择对应协议，并使用该服务商自己的地址和密钥。

(team-model)=
## 团队服务器：保存个人密钥

1. 用自己的账号登录，打开 **配置 → 模型**。
2. 在管理员登记的后端中选择服务商。
3. 在 **我的 API Key** 保存个人密钥，再测试连接。
4. 切换到自己的世界，设置默认模型与日程模型，保存运行配置。

同一账号、协议与完整 Base URL 下的预设可以复用个人密钥。管理员维护可选后端和密钥存储位置，部署步骤见 [团队部署](deployment.md)。

(cli-model)=
## 命令行：使用同一后端

在刚才设置了 `GAWORLD_TUTORIAL_KEY` 的终端和工作区中运行：

```bash
gaworld run --sim-days 1
```

命令行使用工作区的 `dashboard_config.json` 与运行覆盖项。网页选中的团队世界通过网页会话传递；终端运行应明确选择自己的工作区与数据配置。需要操作服务器上的已有世界时，使用 [Python 与 HTTP 接口](integration.md)。

可在工作区中检查路由和密钥变量名：

```python
from gaworld.settings import build_config
config = build_config()
print(config["llm"]["routing"]["default"])
print(config["llm"]["routing"]["tasks"]["schedule"])
print(config["llm"]["providers"]["tutorial"]["api_key_env"])
```

预期依次输出 `tutorial`、`tutorial`、`GAWORLD_TUTORIAL_KEY`。

## 参数保存与生效

| 设置 | 保存或读取位置 | 生效方式 |
| --- | --- | --- |
| 模型后端、默认路由 | 控制台配置覆盖文件 | 保存后测试；新运行读取配置 |
| 单人密钥 | 启动进程的环境变量 | 设置后启动控制台或 CLI |
| 团队个人密钥 | 服务器指定的个人密钥文件 | 按账号和服务端点读取 |
| 居民、时长、步长、种子 | 当前世界或工作区的运行配置 | 新运行按保存值启动 |
| 最终运行覆盖 | `GAWORLD_CONFIG_OVERRIDES` JSON | 运行配置组装时最后合并 |

并发、超时与输出长度影响调用过程。对照实验中，各组采用相同的模型与调用设置。配置字段及来源可在配置页查看，完整配置通过 `GET /api/config` 读取。

## 连接问题与处理

| 现象 | 检查位置与操作 |
| --- | --- |
| 本地没有“我的 API Key” | 按本页“本地单人”设置终端环境变量；该输入框属于账号密钥功能 |
| 提示缺少密钥 | 核对后端的 `api_key_env` 与终端变量名；重新启动读取该变量的进程 |
| 返回 401 / 403 | 核对服务商、密钥权限和额度 |
| 返回模型不存在 | 核对模型 ID；它与后端名称是两个字段 |
| 请求超时 | 查看服务端运行状态、网络和后端超时值 |
| 网页测试成功，CLI 失败 | 检查 CLI 所在终端的环境变量及工作区配置 |

更多后端选项见仓库的 [模型接入说明](https://github.com/wuchaozju/GAWorld/blob/main/docs/MODEL_PROVIDERS.md)。

## 代码结构与执行流程

### 模块分工

```{container} code-map

| 源码位置 | 职责 |
| --- | --- |
| [site/dashboard/settings.js](https://github.com/wuchaozju/GAWorld/blob/main/site/dashboard/settings.js) | 配置页面：读取配置、编辑模型后端、保存个人密钥与发起测试。 |
| [gaworld/apps/settings\_api.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/apps/settings_api.py) | 配置接口：汇总配置来源，校验保存内容，处理模型测试和密钥保存。 |
| [gaworld/settings/\_\_init\_\_.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/settings/__init__.py) | build_config() 从默认值和运行覆盖项组装 CONFIG。 |
| [gaworld/settings/overrides.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/settings/overrides.py) | 合并控制台配置、环境文件、城市配置和最终运行覆盖项。 |
| [gaworld/llm/credentials.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/llm/credentials.py) | 按账号、协议与服务地址保存和查找个人密钥。 |
| [gaworld/llm/providers.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/llm/providers.py) | 构造模型后端，通过 call_llm() 路由实际调用。 |

```

### 执行流程

```text
配置页面 → settings_api → 配置文件 / 个人密钥文件
运行启动 → build_config() → LLMRouter → 对应模型后端
```

界面保存的参数进入配置覆盖文件；个人密钥通过 credentials 单独读写。运行进程启动后重新组装 CONFIG，模型调用由 providers 选择后端。`GAWORLD_CONFIG_OVERRIDES` 在城市配置加载后再次合并，因此具有最终覆盖权。

### 从哪里修改

修改默认参数从 `gaworld/settings/` 开始；修改配置界面的字段与保存行为，查看 `settings.js` 和 `settings_api.py`；增加模型协议支持，查看 `providers.py`。
