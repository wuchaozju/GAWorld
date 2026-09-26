# 附录 B　GAWorld CLI 速查

> 本附录收录 GAWorld 全部 CLI 命令,按用途分类。每个命令给出语法、常用参数、典型用法。读者可以在终端直接拷贝使用。

---

## B.1　核心运行命令

### `python generative_city_sim.py run`

运行仿真。

```bash
python generative_city_sim.py run [OPTIONS]

OPTIONS:
  --city TEXT              城市包(slug)
  --sim-days INTEGER       仿真天数(默认 30)
  --sim-years INTEGER      仿真年数(与 --sim-days 互斥)
  --sim-months INTEGER     仿真月数
  --time-unit [day|month|year]  步长单位
  --fast-forward           快进模式(每个 agent 每天 1 次 LLM 调用)
  --seed INTEGER           随机种子(默认 42)
  --output PATH            输出目录(默认 output/run_<ts>)
  --no-llm                 不调用 LLM(纯规则)
  --size INTEGER           居民数(覆盖默认)
  --start-day INTEGER      起始仿真日(默认 1)
  --end-day INTEGER        结束仿真日(默认 sim-days)
  --config-overrides TEXT  配置覆盖项(JSON 字符串)
```

**典型用法**:

```bash
# 标准 30 天仿真
python generative_city_sim.py run --sim-days 30

# 10 年仿真(以年为单位)
python generative_city_sim.py run --sim-years 10 --time-unit year

# 快进 600 天
python generative_city_sim.py run --sim-days 600 --fast-forward

# 用绍兴柯桥城市包
python generative_city_sim.py run --city shaoxing_keqiao --sim-days 7
```

### `python generative_city_sim.py reset`

重置仿真(清除缓存、日志,重置 Day 1)。

```bash
python generative_city_sim.py reset [--city TEXT]
```

### `python generative_city_sim.py parallel-worlds`

平行世界实验。

```bash
python generative_city_sim.py parallel-worlds [OPTIONS]

OPTIONS:
  --spec PATH              平行世界 spec JSON
  --output PATH            输出目录
  --seeds INTEGER          种子数(默认 5)
  --max-worlds INTEGER     最大世界数(默认 8)
```

**典型用法**:

```bash
python generative_city_sim.py parallel-worlds \
  --spec examples/case-03-policy/worlds.json \
  --output output/case03
```

### `python generative_city_sim.py compare-event`

事件对照实验(2 个世界:有事件 vs 无事件)。

```bash
python generative_city_sim.py compare-event [OPTIONS]

OPTIONS:
  --event-name TEXT        事件名
  --sim-days INTEGER       仿真天数
  --seed INTEGER           种子
```

### `python generative_city_sim.py dashboard`

启动本地 Dashboard。

```bash
python generative_city_sim.py dashboard --port 8766
# → http://127.0.0.1:8766/dashboard
```

### `python generative_city_sim.py serve-viz`

启动仿真回放查看器。

```bash
python generative_city_sim.py serve-viz --port 8000
# → http://127.0.0.1:8000/site/simviz/index.html
```

### `python generative_city_sim.py serve-distributed`

启动分布式 relay 节点(多机协同)。

```bash
python generative_city_sim.py serve-distributed --host 0.0.0.0 --port 8877
```

---

## B.2　采访与调查命令

### `python generative_city_sim.py interview`

采访单个智能体。

```bash
python generative_city_sim.py interview [OPTIONS]

OPTIONS:
  --agent-id INTEGER       智能体 ID(必填)
  --question TEXT          单个问题
  --questions-file PATH    多问题文件(每行一个问题)
  --followup INTEGER       追问轮数(默认 0)
  --city TEXT              跨城市采访
```

**典型用法**:

```bash
# 单个问题
python generative_city_sim.py interview --agent-id 31 \
  --question "你支持加征拥堵费吗?"

# 多问题 + 追问
python generative_city_sim.py interview --agent-id 31 \
  --questions-file questions.txt --followup 3
```

### `python -m gaworld.interview`

群体采访(可跨城市)。

```bash
python -m gaworld.interview --spec round.json --out answers.json
```

```json
// round.json 示例
{
  "round_name": "拥堵费态度调查",
  "city": "shaoxing_keqiao",
  "sample_size": 1000,
  "questions": [
    {
      "id": "main",
      "type": "open",
      "prompt": "你支持加征拥堵费吗?"
    }
  ]
}
```

### `python generative_city_sim.py create-agent-from-social`

从社交内容创建智能体。

```bash
python generative_city_sim.py create-agent-from-social \
  --url "https://example.com/user-profile" \
  --name "林素"

# 或从文件
python generative_city_sim.py create-agent-from-social \
  --file profile.txt --name "林素"
```

---

## B.3　外部信息注入

### `python generative_city_sim.py rag-add`

向单个智能体注入外部信息。

```bash
python generative_city_sim.py rag-add --agent-id 31 \
  --text "市政府公告:加征拥堵费,每月 200 元"
```

### `python generative_city_sim.py rag-import`

从文件批量导入外部信息。

```bash
python generative_city_sim.py rag-import --file news.txt
```

---

## B.4　城市与人口管理

### `python -m gaworld.city create`

从地名创建城市。

```bash
python -m gaworld.city create "绍兴柯桥" --size 200 --seed 42
python -m gaworld.city create "柳溪村" --offline --scale tiny
```

### `python -m gaworld.city add-agents`

往城市里加居民。

```bash
python -m gaworld.city add-agents shaoxing_keqiao --size 200
```

### `python -m gaworld.city add-agent`

加单个居民。

```bash
python -m gaworld.city add-agent shaoxing_keqiao \
  --name "林素" --age 34 --job "社区医生"
```

### `python -m gaworld.city migrate`

迁移居民到新城市。

```bash
python -m gaworld.city migrate shaoxing_keqiao --agent-id 31
```

### `python -m gaworld.city list`

列出所有城市包。

```bash
python -m gaworld.city list
```

### `python -m gaworld.city show`

显示城市详情。

```bash
python -m gaworld.city show shaoxing_keqiao
```

### `python -m gaworld.city use`

切换当前城市。

```bash
python -m gaworld.city use shaoxing_keqiao
# 用 --clear 恢复默认
python -m gaworld.city use --clear
```

### `python -m gaworld.city delete`

删除城市包。

```bash
python -m gaworld.city delete shaoxing_keqiao --yes
```

---

## B.5　群体仿真

### `python -m gaworld.group`

群体(cohort)仿真。

```bash
python -m gaworld.group --size 500 --days 7 --no-llm
python -m gaworld.group --size 500 --days 7 --focal 7,42
python -m gaworld.group --size 500 --days 7 --network-coupling 0.7
```

### `python -m gaworld.group.validate`

群体模式验证门(L1–L4)。

```bash
python -m gaworld.group.validate --size 100 --days 14 --network-coupling 0.7
```

### `python -m gaworld.population`

参数化人口合成。

```bash
python -m gaworld.population --size 500 --seed 42 --out data/town
python -m gaworld.population --check  # 只预览不写
```

---

## B.6　人格与个性化

### `python scripts/author_personality.py`

为居民生成大五人格。

```bash
python scripts/author_personality.py --dry-run  # 看 prompt 不写入
python scripts/author_personality.py --agents 1-5  # 试水
python scripts/author_personality.py --apply  # 全量落盘
```

### `python scripts/big5_effect_ceiling.py`

检验人格与行为的相关上限。

```bash
python scripts/big5_effect_ceiling.py
```

### `python scripts/big5_collinearity.py`

检验大五维度是否与现有状态变量共线。

```bash
python scripts/big5_collinearity.py --annotate
```

---

## B.7　游戏场

### `python -m gaworld.games disaster`

灾害模式(分幕反应)。

```bash
python -m gaworld.games disaster --spec disaster_spec.json --output output/case04
```

### 斗兽场(通过 Dashboard)

启动 Dashboard 后访问 `/site/dashboard/arena.html`,通过界面发起。

### 说服游戏(通过 Dashboard)

启动 Dashboard 后访问 `/site/dashboard/games.html`,通过界面发起。

---

## B.8　脚本工具

### `python scripts/generate_citymap.py`

生成城市地图。

```bash
python scripts/generate_citymap.py --description "a small city with about 1000 residents, in east china"
```

### 各种验证脚本

```bash
python scripts/check_economy_conservation.py  # 检查经济守恒
python scripts/check_seed_reproducibility.py  # 检查种子可复现性
python scripts/generate_paper_figures.py      # 生成论文图表
```

---

## B.9　常用命令组合

### 完整研究流程

```bash
# 1. 创建城市
python -m gaworld.city create "绍兴柯桥" --size 1000

# 2. 加居民
python -m gaworld.city add-agents shaoxing_keqiao --size 1000

# 3. 试运行(7 天)
python generative_city_sim.py run --city shaoxing_keqiao --sim-days 7 --seed 42

# 4. 检查输出
ls output/run_*/
cat output/run_*/state/agent_state_history.csv | head

# 5. 正式实验
python generative_city_sim.py parallel-worlds \
  --spec examples/case-03-policy/worlds.json \
  --output output/case03

# 6. 群体采访
python -m gaworld.interview --spec examples/case-02-survey/round.json --out output/case02.json

# 7. 灾害模式
python -m gaworld.games disaster --spec examples/case-04-disaster/spec.json --output output/case04
```

### 调试流程

```bash
# 关闭 LLM 跑一遍(快速验证逻辑)
python generative_city_sim.py run --sim-days 7 --no-llm

# 单 agent 详细日志
python generative_city_sim.py run --sim-days 7 --verbose-agent 31

# 守恒审计
python scripts/check_economy_conservation.py output/run_*/
```

---

## B.10　环境变量

GAWorld 识别以下环境变量:

```bash
# LLM API 密钥
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export GAWORLD_CONFIG_OVERRIDES='{"llm":{"default":"gpt-4o-mini"}}'

# 日志级别
export GAWORLD_LOG_LEVEL=DEBUG  # DEBUG / INFO / WARNING / ERROR

# 数据目录(可选)
export GAWORLD_DATA_DIR="/path/to/data"
```

---

## B.11　错误码速查

| 错误码 | 含义 | 应对 |
|---|---|---|
| 1 | 通用错误 | 查看日志 |
| 2 | 配置错误 | 检查配置文件 |
| 3 | 数据缺失 | 跑 `reset` 重置 |
| 4 | API 调用失败 | 检查网络、密钥、配额 |
| 5 | LLM 解析失败 | 检查 prompt 或换模型 |
| 6 | 守恒失守 | 检查经济代码或调小步长 |
| 7 | 种子冲突 | 换种子或检查并发 |

---

## B.12　常用路径

```
GAWorld/
├── config.py                # 主配置
├── data/                    # 数据资产
│   ├── cities/             # 城市包
│   ├── agents.csv          # 居民身份
│   └── profiles.md         # 居民 profile
├── output/                  # 仿真产物
│   ├── run_<ts>/           # 单次仿真
│   ├── parallel_worlds/    # 平行世界
│   ├── interviews/         # 采访
│   └── persona/            # Persona 蒸馏
├── docs/                    # 文档
├── examples/                # 案例脚本
├── scripts/                 # 辅助脚本
└── tests/                   # 测试
```

---

> **本附录教学注释**
>
> 这个 CLI 速查表覆盖 GAWorld 90% 的常用命令。读者在自己的研究中,可以从这些命令开始,然后根据具体需求查阅 `docs/` 下的详细文档。
>
> B.9 节"完整研究流程"是本书案例的标准流程。读者做研究时,可以照这个流程跑一遍,验证 GAWorld 安装是否正确。
>
> B.10 节"环境变量"对 LLM 配置特别重要。读者如果没有 OPENAI_API_KEY,所有 LLM 调用会失败。建议读者第一次跑就设置好这个变量。
---

## B.13　扩展:调试与诊断命令

仿真出问题时,这些命令帮读者排查。

### 调试仿真运行

```bash
# 开启详细日志
python generative_city_sim.py run --sim-days 7 --verbose

# 只跑指定 agent
python generative_city_sim.py run --sim-days 7 --only-agent 31

# 输出每日状态
python generative_city_sim.py run --sim-days 7 --dump-state daily
```

### 诊断网络问题

```bash
# 测试 OSM 抓取
python -c "from gaworld.city import fetch_osm; fetch_osm('绍兴柯桥', dry_run=True)"

# 测试 Nominatim 地理编码
python -c "from gaworld.city import geocode; print(geocode('绍兴柯桥'))"
```

### 诊断 LLM 问题

```bash
# 测试 LLM 调用
python -c "from gaworld.llm import test_call; print(test_call('你是谁?'))"

# 查看 LLM 配置
python -c "from gaworld.llm import get_config; print(get_config())"
```

### 诊断数据问题

```bash
# 检查居民数据完整性
python scripts/check_agents_integrity.py data/cities/shaoxing_keqiao

# 检查经济守恒
python scripts/check_economy_conservation.py output/run_*/

# 检查社会网络
python scripts/check_social_graph.py output/run_*/
```

---

## B.14　扩展:批量操作命令

### 批量跑多个种子

```bash
# 跑 5 个种子
for seed in 42 123 456 789 1000; do
    python generative_city_sim.py run \
      --city shaoxing_keqiao \
      --sim-days 30 \
      --seed $seed \
      --output output/run_seed_$seed
done
```

### 批量跑多个城市

```bash
for city in shaoxing_keqiao hangzhou_xihu beijing_haidian; do
    python generative_city_sim.py run \
      --city $city \
      --sim-days 30 \
      --output output/${city}_run
done
```

### 批量分析

```bash
# 合并多个 run
python -c "
import pandas as pd
import glob
dfs = []
for f in glob.glob('output/run_seed_*/state/agent_state_history.csv'):
    df = pd.read_csv(f)
    df['seed'] = f.split('seed_')[1].split('/')[0]
    dfs.append(df)
merged = pd.concat(dfs)
merged.to_csv('output/merged_runs.csv', index=False)
print(f'合并 {len(dfs)} 个 run')
"
```

---

## B.15　扩展:性能优化命令

### 性能监控

```bash
# 启用性能监控
python generative_city_sim.py run --sim-days 30 --profile

# 查看 GPU 使用(如果用本地 LLM)
nvidia-smi
```

### 内存优化

```bash
# 限制内存使用
python generative_city_sim.py run --sim-days 30 --max-memory 8GB

# 强制垃圾回收
python -c "
import gc; gc.collect()
from gaworld.sim import Simulator
sim = Simulator(...)
"
```

### 分布式运行

```bash
# 启动多个 worker
python generative_city_sim.py serve-distributed --port 8877 &
python generative_city_sim.py serve-distributed --port 8878 &
python generative_city_sim.py serve-distributed --port 8879 &

# 在主节点运行
python generative_city_sim.py run --sim-days 30 --distributed
```

---

## B.16　扩展:数据导入导出命令

### 导出数据

```bash
# 导出为 CSV
python generative_city_sim.py export --format csv --output export/

# 导出为 JSON
python generative_city_sim.py export --format json --output export/

# 导出为 Parquet(更紧凑)
python generative_city_sim.py export --format parquet --output export/
```

### 导入数据

```bash
# 从 CSV 导入新居民
python generative_city_sim.py import --format csv --file new_agents.csv

# 从 JSON 导入
python generative_city_sim.py import --format json --file new_agents.json
```

### 数据备份

```bash
# 备份整个仿真
tar -czf backup_$(date +%Y%m%d).tar.gz output/

# 备份配置
cp dashboard_config.json config_backup.json
```

---

## B.17　扩展:版本与依赖管理

### 查看版本

```bash
# GAWorld 版本
python -c "import gaworld; print(gaworld.__version__)"

# Python 版本
python --version

# 依赖列表
pip list

# 锁定依赖
pip freeze > requirements.lock.txt
```

### 更新 GAWorld

```bash
# 从 git pull
cd /Users/cw/dev/GAWorld
git pull origin main
pip install -e .

# 检查更新
python -c "import gaworld; print(gaworld.__version__)"
```

### 重置环境

```bash
# 重置所有缓存
python generative_city_sim.py reset --all

# 重置单个城市
python -m gaworld.city delete shaoxing_keqiao --yes
python -m gaworld.city create "绍兴柯桥" --size 200
```

---

## B.18　扩展:常见任务的脚本模板

### 任务一:跑限行令仿真

```bash
#!/bin/bash
# 限行令政策仿真
set -e

# 1. 准备城市
python -m gaworld.city create "测试城市" --size 1000 --seed 42

# 2. 跑对照组
python generative_city_sim.py run \
  --city test_city \
  --sim-days 180 \
  --seed 42 \
  --output output/limit_control

# 3. 跑处理组
python generative_city_sim.py run \
  --city test_city \
  --sim-days 180 \
  --seed 42 \
  --events '{"day_30": "limit_weekday"}' \
  --output output/limit_treatment

# 4. 分析
python examples/case-03-policy/06_generate_report.py
```

### 任务二:做群体采访

```bash
#!/bin/bash
# 群体采访
set -e

python -m gaworld.interview \
  --spec round.json \
  --out answers.json

python examples/case-02-survey/03_analyze_results.py
```

### 任务三:跑灾害仿真

```bash
#!/bin/bash
# 灾害仿真
set -e

python -m gaworld.games disaster \
  --spec disaster_spec.json \
  --output output/case04

python examples/case-04-disaster/06_generate_summary.py
```

---

## B.19　扩展:高级配置选项

### 自定义 LLM 提供商

```bash
# 通过环境变量配置
export GAWORLD_LLM_PROVIDER="custom"
export GAWORLD_LLM_BASE_URL="https://my-api.example.com/v1"
export GAWORLD_LLM_API_KEY="my-key"
export GAWORLD_LLM_MODEL="my-model"
```

### 自定义数据目录

```bash
export GAWORLD_DATA_DIR="/custom/data/path"
export GAWORLD_OUTPUT_DIR="/custom/output/path"
```

### 自定义提示词路径

```bash
export GAWORLD_PROMPTS_DIR="/custom/prompts/path"
```

---

## B.20　扩展:命令行参数详解

### 全局参数

```bash
# 查看全局帮助
python generative_city_sim.py --help

# 设置日志级别
python generative_city_sim.py --log-level DEBUG

# 启用 dry-run(不实际运行)
python generative_city_sim.py --dry-run
```

### 命令特定参数

每个子命令都有自己的参数:

```bash
# run 命令的所有参数
python generative_city_sim.py run --help

# parallel-worlds 命令的所有参数
python generative_city_sim.py parallel-worlds --help

# 等等
```

### 参数组合的优先级

```bash
# 命令行参数 > 环境变量 > 配置文件 > 代码默认
# 例:--seed 100 覆盖 config.py 的默认种子
```

---

## B.21　本附录教学注释(扩展版)

- 调试与诊断命令帮读者快速定位问题。
- 批量操作命令支持大规模实验。
- 性能优化命令帮读者控制成本。
- 数据导入导出支持与其他工具集成。
- 版本与依赖管理确保可复现性。
- 脚本模板是常见任务的"开箱即用"起点。
- 高级配置选项支持特殊场景。
- 命令行参数详解帮助读者理解每个选项。

