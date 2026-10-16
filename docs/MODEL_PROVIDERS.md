# 模型选择与个人 API Key

平台不限定 MiniMax。模型定义由管理员维护，云端密钥按登录账号隔离。
新增模型不改变已有世界、实验或全局的默认路由。

## 使用方式

1. 使用自己的账号登录，在“配置 → 模型”找到要使用的模型。
2. 云端模型：填写该服务商的“我的 API Key”，保存后测试连通性。
3. 打开自己的世界，在仿真页面把“默认模型”和“日程模型”都选为目标模型，保存配置。
4. 先运行小规模实验；服务商权限、余额、并发限制仍由各账号承担。

不要把 GLM 或 DeepSeek 的 Key 填入 MiniMax 的输入框。密钥按账号、协议和完整
Base URL 绑定。同一账号的两个 DeepSeek 预设共用相同端点，因此可复用已保存的 Key；
其他账号不会获得该 Key。

## 预设（2026-10-09 核对官方文档）

| 页面名称 | 模型 ID | Base URL | 凭证 |
| --- | --- | --- | --- |
| `deepseek_flash` | `deepseek-flash` | `https://api.deepseek.com` | 个人 DeepSeek Key |
| `deepseek_pro` | `deepseek-v4-pro` | `https://api.deepseek.com` | 个人 DeepSeek Key |
| `glm_5` | `glm-5` | `https://open.bigmodel.cn/api/paas/v4` | 个人智谱标准 API Key |
| `qwen_27b_server13` | `qwen3.5:27b-q4_K_M` | 13 号机本地 Ollama | 无云端 Key，共享服务器算力 |

GLM 和 DeepSeek 使用 `openai` 兼容协议；这里的 `openai` 表示接口格式，不要求购买
OpenAI 的 Key。新增的云端预设显式关闭思考模式，避免仿真任务的短输出预算被推理耗尽。
已有模型的思考模式不变。更改模型或思考模式会改变实验语义，应在实验记录中保留配置。

GLM Coding Plan 不等于标准 API 额度。官方说明自建应用必须使用标准 API，不能假定
编码套餐可用于此平台。网页聊天会员同样不应被当作已具备 API 余额。

## 管理与部署

- 管理员可在“配置 → 模型 → 新增后端”登记其他服务商；普通用户只管理自己的 Key、
  选择自己世界的模型，不获得修改全站端点的权限。
- GLM/DeepSeek 预设来自 `gaworld/settings/llm.py`，没有内置密钥。
- 13 号机的本地地址不能作为所有部署的默认值，因此使用独立配置文件
  `deployment/multi-user/provider-qwen27b-server13.json`。
  管理员登录后将该 JSON 提交到 `POST /api/settings/llm/provider`，随后刷新页面。
- Qwen 参数固定为 `think: false`、`num_ctx: 65536`，匹配本次核对的已加载实例，
  避免默认上下文大小不同而反复装载模型。首次加载可能较慢，仿真超时设为 600 秒。
  若以后调整服务器模型或上下文配置，应重新验证这些参数。
- 该选项不会开启新的公网推理端口，也不构成 GPU 资源隔离。多人同时使用时会争用
  本地推理资源；不要据此承诺大规模并发实验的性能。
- 添加到列表、保存 Key、短文本探测、完整仿真是不同层级的验证。
  未提供个人云端 Key 时，不能宣称 GLM/DeepSeek 的真实生成已通过。

## 官方依据

- [DeepSeek 接口与当前模型](https://api-docs.deepseek.com/zh-cn/)
- [DeepSeek 思考开关与请求参数](https://api-docs.deepseek.com/api/create-chat-completion/)
- [GLM-5 接口示例](https://docs.bigmodel.cn/cn/guide/models/text/glm-5)
- [GLM 思考模式](https://docs.bigmodel.cn/cn/guide/capabilities/thinking)
- [GLM Coding Plan 使用范围](https://docs.bigmodel.cn/cn/coding-plan/faq)
- [Ollama 生成接口](https://docs.ollama.com/api/generate)
