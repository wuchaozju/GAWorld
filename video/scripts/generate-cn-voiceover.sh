#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TTS_GEN="${CODEX_HOME:-$HOME/.codex}/skills/speech/scripts/text_to_speech.py"
JOBS="$ROOT/tmp/speech/gaworld-tutorial-cn.jsonl"

if [[ ! -f "$TTS_GEN" ]]; then
  echo "Missing TTS generator: $TTS_GEN" >&2
  exit 1
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY is not set. Export it before generating voiceover audio." >&2
  exit 1
fi

mkdir -p "$ROOT/tmp/speech"
mkdir -p "$ROOT/video/public/voiceover/GAWorldTutorialCN"

cat > "$JOBS" <<'JSONL'
{"out":"voiceover/GAWorldTutorialCN/01-opening.mp3","input":"大家好，这段视频面向 GAWorld 的开发社区。GAWorld 的定位不是简单地跑一群智能体聊天，而是把城市居民、地图空间、社会关系、环境事件、长期记忆和模型推理，组织成一个可以复现、可以对照、可以回放的社会实验场。你可以用同一批 Agent 和同一个随机种子，比较有政策事件和没有政策事件时，城市行为系统到底发生了什么变化。"}
{"out":"voiceover/GAWorldTutorialCN/02-data.mp3","input":"第一层是数据启动。GAWorld 的 Agent 不是在运行时随便捏出来的，而是由多个数据源共同构成。CSV 文件提供可计算的初始状态，比如年龄、职业、健康、情绪和资金。Markdown profile 提供人物叙事、偏好和关系线索。citymap 文件提供地点节点、类别和移动空间。开发者可以替换这些数据，也可以通过脚本从新的城市描述生成地图，或者从社交内容创建新的 Agent。"}
{"out":"voiceover/GAWorldTutorialCN/03-loop.mp3","input":"第二层是主仿真循环。入口仍然是 generative_city_sim.py，它负责 CLI、天数推进、时间步调度和输出落盘。每个 Agent 在一天里会经历感知、计划、行动和反思。感知阶段读取位置、事件、社交上下文和状态。计划阶段生成日程和意图。行动阶段执行移动、消费、工作、社交或者休息。反思阶段把经历写进 episode 记忆，并影响未来的习惯和关系。"}
{"out":"voiceover/GAWorldTutorialCN/04-memory.mp3","input":"GAWorld 重要的一点是跨天一致性。memory_store.py 负责记忆持久化和向量检索，human_realism.py 负责习惯、意图、关系和人物真实感。Agent 每天产生 episode memory，系统再把长期经历压缩成 summary，避免上下文无限增长。当你添加外部 RAG 信息，或者采访某个 Agent 时，系统会把这些记忆重新带回推理上下文，因此 Agent 的回答和后续行动会受到过去经历影响。"}
{"out":"voiceover/GAWorldTutorialCN/05-city-economy.mp3","input":"第三个核心功能是把行为落到城市约束上。city_map_system.py 不再依赖硬编码地点，而是通过地点类别解析活动，比如教育、医疗、商业和休闲。移动会计算交通方式、时间成本、天气影响和高峰时段。economy_module.py 则模拟个人收入、税费、消费结构、储蓄、投资和宏观经济周期。这样，Agent 的选择不只是语言上的选择，也会影响钱、时间、位置和后续状态。"}
{"out":"voiceover/GAWorldTutorialCN/06-dynamic.mp3","input":"动态行为模块解决的是计划过于僵硬的问题。dynamic_behavior.py 会在每个时间步评估是否发生中断。比如饥饿、疲劳、时间压力、未读消息、社交偶遇，或者天气和交通事件，都可能让 Agent 改变原计划。关键设计是承诺度：考试、手术、正式会议很难被打断，个人休闲更容易被打断。这让行为既有计划性，也保留城市生活里的临场变化。"}
{"out":"voiceover/GAWorldTutorialCN/07-llm.mp3","input":"模型调用集中在 llm_providers.py。仿真器不应该到处直接访问某个厂商 API，而是通过 call_llm 传入任务名、Agent、prompt 和路由配置。配置里可以选择 Ollama、本地模型、OpenAI 兼容接口，或者 Anthropic 兼容接口。路由还支持 fallback，某个 provider 失败时自动尝试备用模型。做测试时，原则是 mock call_llm，不让单元测试依赖真实网络。"}
{"out":"voiceover/GAWorldTutorialCN/08-compare.mp3","input":"如果只推荐一个入口，我会推荐 compare-event。它会自动创建无事件 baseline 和有事件分支，使用同一批 Agent 和同一个随机种子运行，然后汇总差异。输出里包含 comparison metrics 和 summary。这里不仅比较常规状态，也可以比较 PolicySim 风格指标，比如立场分数、风险、跨观点曝光和干预 reward。这个接口非常适合做政策情景、交通事件、公共议题传播和平台干预的演示。"}
{"out":"voiceover/GAWorldTutorialCN/09-tools.mp3","input":"实验跑完之后，最重要的是能检查证据。GAWorld 提供 CLI、Dashboard、访谈和轨迹回放。Dashboard 可以修改配置、编辑人物 profile、启动和停止仿真、查看记忆并进行访谈。output 目录保存日志、记忆、状态历史、干预指标、对照实验结果和图表。开发社区在调试新机制时，应该优先看这些可复核产物，而不是只看终端最后一行是否成功。"}
{"out":"voiceover/GAWorldTutorialCN/10-structure.mp3","input":"最后是贡献路径。这个项目仍保留 generative_city_sim.py 作为稳定入口，但新的跨模块代码应该优先进入 gaworld 目录。settings 管配置，core 放 typed Agent 和 runner，io 放网络和网页提取，work 放真实任务队列和适配器。新功能必须配测试，尤其要 mock LLM 调用，避免 CI 依赖外部 API。一个好的贡献通常从一个小实验开始：加机制，写测试，跑对照，检查 output，再把接口和文档补齐。"}
JSONL

python "$TTS_GEN" speak-batch \
  --input "$JOBS" \
  --out-dir "$ROOT/video/public" \
  --voice cedar \
  --response-format mp3 \
  --instructions "Voice Affect: 清晰、沉稳、专业。Tone: 面向开源开发者的技术讲解，克制但有引导感。Pacing: 中等偏慢，模块切换处自然停顿。Pronunciation: 清楚读出 GAWorld、Agent、LLM、RAG、PolicySim、Dashboard、compare-event。Delivery: 旁白式教程，不要夸张表演。" \
  --force

rm -f "$JOBS"
