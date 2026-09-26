# 附录 C　配置文件结构与常用覆盖项

> 本附录介绍 GAWorld 的配置文件结构,以及最常用的覆盖项。读者做研究时,经常需要修改配置(种子、LLM 模型、人口规模等),本附录给出完整指南。

---

## C.1　配置文件的三层结构

GAWorld 的配置分三层,从高到低优先级:

**第一层:代码默认**(`config.py`, `gaworld/settings/defaults.py`)
最底层,所有参数都有默认值。读者一般不需要改这里。

**第二层:dashboard_config.json**
本地配置,优先级中等。日常调试、改种子、换 LLM 都改这里。

**第三层:环境变量**(`GAWORLD_CONFIG_OVERRIDES`)
最高优先级,适合 CI/CD 或一次性覆盖。

```
环境变量 GAWORLD_CONFIG_OVERRIDES  ← 最高优先级
dashboard_config.json              ← 中等优先级
config.py / defaults.py            ← 最低优先级(默认)
```

---

## C.2　dashboard_config.json 结构

```json
{
  "city": "shaoxing_keqiao",
  "llm": {
    "default": "gpt-4o-mini",
    "tasks": {
      "daily_decision": "gpt-4o-mini",
      "interview_analysis": "gpt-4",
      "disaster_response": "gpt-4o"
    }
  },
  "memory": {
    "consolidation_threshold": 10,
    "decay_half_life_days": 7
  },
  "economy": {
    "currency_unit": "CNY",
    "conservation_audit": true,
    "sectors": {
      "household": 0.7,
      "corporate": 0.2,
      "government": 0.05,
      "bank": 0.05
    }
  },
  "simulation": {
    "default_seed": 42,
    "default_sim_days": 30,
    "fast_forward_threshold_days": 60
  },
  "social": {
    "decay_rate_per_day": 0.01,
    "ghost_ratio": 0.15,
    "dunbar_layers": [5, 15, 50, 150]
  },
  "personality": {
    "big5_enabled": true,
    "big5_sampling": "llm",
    "big5_application": "soft_prompt"
  },
  "interests": {
    "enabled": true,
    "evolution": "幂律学习",
    "decay_half_life_days": 30
  },
  "family": {
    "marriage_by_age": "real_china_2024",
    "child_age_distribution": "real_china_2024"
  },
  "policy_events": {
    "limit_weekday": {
      "day": 45,
      "description": "工作日按车牌尾号限行",
      "parameters": {
        "plate_rules": "周一1&6,周二2&7,..."
      }
    }
  },
  "moltbook": {
    "enabled": false,
    "daily_post_rate_limit": 0.5
  },
  "intervention": {
    "enabled": false
  }
}
```

---

## C.3　常用覆盖项详解

### C.3.1 城市切换

```json
{
  "city": "shaoxing_keqiao"   // 或 "hangzhou_xihu"、"default" 等
}
```

或命令行:

```bash
python generative_city_sim.py run --city shaoxing_keqiao
```

### C.3.2 LLM 模型与路由

```json
{
  "llm": {
    "default": "gpt-4o-mini",
    "tasks": {
      "daily_decision": "gpt-4o-mini",
      "interview_analysis": "gpt-4",
      "disaster_response": "gpt-4o"
    }
  }
}
```

任务级路由允许不同任务用不同模型,优化成本。

### C.3.3 随机种子

```json
{
  "simulation": {
    "default_seed": 42
  }
}
```

或命令行:

```bash
python generative_city_sim.py run --seed 42
```

### C.3.4 经济系统

```json
{
  "economy": {
    "conservation_audit": true,    // 是否每天审计
    "sectors": {                    // 部门池初始资金比例
      "household": 0.7,
      "corporate": 0.2,
      "government": 0.05,
      "bank": 0.05
    },
    "credit": {                     // 信贷设置
      "max_loan_amount": 50000,
      "interest_rate": 0.05
    }
  }
}
```

### C.3.5 记忆系统

```json
{
  "memory": {
    "consolidation_threshold": 10,    // 多少条触发长期记忆
    "decay_half_life_days": 7,        // 记忆半衰期
    "vector_recall_topk": 3           // 召回 Top-K
  }
}
```

### C.3.6 社会网络

```json
{
  "social": {
    "decay_rate_per_day": 0.01,       // 关系衰减
    "ghost_ratio": 0.15,              // 幽灵节点比例
    "dunbar_layers": [5, 15, 50, 150] // Dunbar 分层
  }
}
```

### C.3.7 大五人格

```json
{
  "personality": {
    "big5_enabled": true,           // 是否启用
    "big5_sampling": "llm",         // llm / random
    "big5_application": "soft_prompt"  // soft_prompt / hard_rule
  }
}
```

### C.3.8 兴趣爱好

```json
{
  "interests": {
    "enabled": true,
    "evolution": "幂律学习",
    "decay_half_life_days": 30
  }
}
```

### C.3.9 家庭

```json
{
  "family": {
    "marriage_by_age": "real_china_2024",
    "child_age_distribution": "real_china_2024"
  }
}
```

---

## C.4　环境变量覆盖

```bash
# 一次性覆盖某项
export GAWORLD_CONFIG_OVERRIDES='{"llm":{"default":"gpt-4"}}'

# 或在 Python 里
import os
os.environ["GAWORLD_CONFIG_OVERRIDES"] = '{"llm":{"default":"gpt-4"}}'
```

环境变量优先级最高,**必须**是合法 JSON 字符串。

---

## C.5　不同场景的典型配置

### 场景一:快速验证(开发调试)

```json
{
  "simulation": {"default_seed": 42, "default_sim_days": 7},
  "llm": {"default": "gpt-4o-mini"},
  "memory": {"consolidation_threshold": 20}
}
```

快、短、便宜。

### 场景二:研究项目(可发表标准)

```json
{
  "simulation": {"default_seed": 42, "default_sim_days": 180},
  "llm": {
    "default": "gpt-4o-mini",
    "tasks": {"disaster_response": "gpt-4"}
  },
  "economy": {"conservation_audit": true},
  "memory": {"consolidation_threshold": 10, "decay_half_life_days": 7}
}
```

标准、可信、可复现。

### 场景三:大规模长期仿真

```json
{
  "simulation": {"default_sim_days": 600, "fast_forward_threshold_days": 60},
  "llm": {"default": "gpt-4o-mini", "tasks": {"daily_decision": "gpt-4o-mini"}},
  "memory": {"consolidation_threshold": 30, "decay_half_life_days": 14},
  "performance": {"parallel_workers": 16}
}
```

### 场景四:小成本教学演示

```json
{
  "simulation": {"default_seed": 42, "default_sim_days": 3},
  "llm": {"default": "gpt-4o-mini"},
  "memory": {"consolidation_threshold": 5}
}
```

小、慢但便宜,适合课堂演示。

### 场景五:本地无网络

```json
{
  "llm": {"default": "ollama:llama3:8b"},
  "intervention": {"enabled": false}
}
```

用本地模型,适合内网/无网环境。

---

## C.6　配置修改注意事项

修改配置时,有几个原则:

**原则一:不要改 defaults.py**。除非是 GAWorld 维护者,改 defaults.py 会影响所有用户。改 dashboard_config.json 或环境变量。

**原则二:配置版本化**。dashboard_config.json 应该加入 git,环境变量不应该。

**原则三:配置变更要在论文里报告**。改了 LLM 模型、改了种子、改了衰减率,都要在论文里写清楚。

**原则四:配置变更要做对比实验**。改了关键参数,要跑鲁棒性检验,看结论是否稳定。

---

## C.7　常见配置问题

**Q:改了配置但没生效?**

A:检查优先级——环境变量 > dashboard_config.json > defaults.py。如果环境变量没设,改 dashboard_config.json 就够了。

**Q:运行时报 "ConfigError"?**

A:配置 JSON 格式不对。可以用 `python -c "import json; json.load(open('dashboard_config.json'))"` 检查。

**Q:想用自定义模型?**

A:在 `llm.providers` 里加:

```python
# config.py 顶层
LLM_PROVIDERS = {
    "my_custom_model": {
        "type": "openai",
        "base_url": "https://my-api.example.com/v1",
        "api_key": "...",
        "model_name": "my-custom-model"
    }
}
```

然后在 dashboard_config.json 里:

```json
{
  "llm": {
    "default": "my_custom_model"
  }
}
```

---

## C.8　配置的最佳实践

1. **日常配置放 dashboard_config.json**——易管理,易分享。
2. **实验配置用环境变量**——CI/CD 或一次性实验。
3. **每个研究项目一份 dashboard_config.json**——版本化,记录在 git。
4. **每次跑实验前备份配置**——避免意外覆盖。
5. **报告所有非默认配置**——论文里明确列出改了什么。

---

## C.9　配置与可复现性

可复现性要求配置在论文发表后仍能恢复。GAWorld 的做法:

- `dashboard_config.json` 入 git
- 关键实验的环境变量记录在论文附录
- 输出目录 `output/run_<ts>/config_snapshot.json` 自动记录本次运行的配置快照

读者做研究时,**必须**遵守这个规范——否则论文发表后,你的实验无法被别人复现。

---

> **本附录教学注释**
>
> 这个配置指南覆盖了 GAWorld 90% 的常用配置项。读者做研究时,建议从"研究项目(可发表标准)"配置开始,熟悉后再调整。
>
> C.3 节是配置详解——读者重点看 C.3.1–C.3.3(城市、LLM、种子)和 C.3.4–C.3.7(经济、记忆、网络、人格)。
>
> C.5 节"不同场景的典型配置"是工程经验总结——读者可以直接照搬,根据需要微调。
>
> C.6 节"配置修改注意事项"是给做长期研究的读者准备的——配置版本化是工程纪律,不是可选项。
---

## C.10　扩展:配置管理的最佳实践

### C.10.1　配置分层策略

推荐的配置分层:

```
config/
├── default.yaml            # 基础默认值
├── development.yaml        # 开发环境
├── production.yaml         # 生产环境
├── research.yaml           # 研究项目
├── teaching.yaml           # 教学场景
└── experiments/
    ├── exp_2026_09_26.yaml # 特定实验
    └── exp_2026_10_01.yaml
```

切换方法:

```bash
# 通过环境变量指定
export GAWORLD_CONFIG_PROFILE="research"

# 或在代码里
from gaworld.settings import load_config
config = load_config(profile="research")
```

### C.10.2　配置验证

每个配置文件都应该有 schema 验证:

```python
# config_schema.py
CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "simulation": {
            "type": "object",
            "properties": {
                "default_seed": {"type": "integer"},
                "default_sim_days": {"type": "integer"}
            },
            "required": ["default_seed"]
        },
        # ... 其他字段
    }
}
```

加载配置时验证 schema。

### C.10.3　配置的文档化

每个配置字段应该有注释:

```yaml
simulation:
  default_seed:
    type: integer
    default: 42
    description: |
      随机数生成器的种子。改这个值会得到不同的仿真结果。
      论文里**必须**报告使用的种子值。
  default_sim_days:
    type: integer
    default: 30
    description: |
      默认仿真天数。可以被 --sim-days 命令行参数覆盖。
```

### C.10.4　配置的迁移

GAWorld 升级时,配置文件格式可能变化。处理方法:

```python
# config_migrations.py
MIGRATIONS = {
    ("1.0", "1.1"): lambda c: {**c, "memory": {"consolidation_threshold": 10}},
    ("1.1", "2.0"): lambda c: {**c, "simulation": {**c["simulation"], "fast_forward": False}}
}

def migrate_config(config: dict, from_version: str, to_version: str) -> dict:
    """迁移配置"""
    # 按顺序应用迁移
    ...
```

---

## C.11　扩展:高级配置场景

### C.11.1　多 LLM 提供商混合

不同的 LLM 在不同任务上表现不同:

```yaml
llm:
  providers:
    openai:
      api_key: ${OPENAI_API_KEY}
      base_url: https://api.openai.com/v1
    anthropic:
      api_key: ${ANTHROPIC_API_KEY}
      base_url: https://api.anthropic.com
    local_ollama:
      base_url: http://localhost:11434/v1
      type: openai_compatible
  routing:
    default: openai:gpt-4o-mini
    tasks:
      daily_decision: openai:gpt-4o-mini
      interview_analysis: anthropic:claude-3-5-sonnet
      disaster_response: openai:gpt-4
```

### C.11.2　敏感数据加密

API 密钥等敏感数据应该加密存储:

```python
from cryptography.fernet import Fernet

def encrypt_api_key(api_key: str, master_key: bytes) -> bytes:
    """加密 API key"""
    f = Fernet(master_key)
    return f.encrypt(api_key.encode())

def decrypt_api_key(encrypted: bytes, master_key: bytes) -> str:
    """解密 API key"""
    f = Fernet(master_key)
    return f.decrypt(encrypted).decode()
```

### C.11.3　远程配置中心

大型团队用远程配置中心(etcd、Consul):

```python
from gaworld.config import RemoteConfig

config = RemoteConfig(
    backend="etcd",
    host="etcd.internal:2379",
    key_prefix="/gaworld/"
)
```

### C.11.4　配置审计

每次配置变更应该有审计日志:

```python
def audit_config_change(old_config: dict, new_config: dict, user: str):
    """审计配置变更"""
    changes = diff_configs(old_config, new_config)
    log_audit(
        user=user,
        action="config_change",
        changes=changes,
        timestamp=datetime.now()
    )
```

---

## C.12　扩展:配置文件示例集

### C.12.1　教学场景配置

```yaml
# teaching.yaml - 适合课堂演示
simulation:
  default_seed: 42
  default_sim_days: 7  # 短,几分钟跑完
  parallel_workers: 1
llm:
  default: gpt-4o-mini  # 便宜
memory:
  consolidation_threshold: 3  # 简化
social:
  ghost_ratio: 0.0  # 不需要
```

### C.12.2　研究项目配置

```yaml
# research.yaml - 适合正式研究
simulation:
  default_seed: 42
  default_sim_days: 180
  parallel_workers: 8
  fast_forward_threshold_days: 60
llm:
  default: gpt-4o-mini
  tasks:
    interview_analysis: gpt-4
memory:
  consolidation_threshold: 10
  decay_half_life_days: 7
economy:
  conservation_audit: true  # 严格
social:
  ghost_ratio: 0.15
interests:
  enabled: true
```

### C.12.3　生产环境配置

```yaml
# production.yaml - 适合大规模运行
simulation:
  default_seed: 42
  default_sim_days: 365
  parallel_workers: 32
  distributed: true
llm:
  default: gpt-4o-mini
  cache: redis://localhost:6379
performance:
  profile_enabled: true
  memory_limit_gb: 32
monitoring:
  enabled: true
  endpoint: https://monitoring.internal/api
```

### C.12.4　小型实验配置

```yaml
# experiment_2026_09_26.yaml - 特定实验
experiment:
  name: 限行令差异化影响
  date: 2026-09-26
  researcher: cw
simulation:
  default_seed: 42
  default_sim_days: 180
  fast_forward: true  # 节约成本
preregistration:
  conditions: [...]
  hypotheses: [...]
output:
  format: csv
  compression: gzip
```

---

## C.13　扩展:配置问题的诊断

### C.13.1　配置不生效

如果改了配置但没生效,检查:

```bash
# 1. 检查优先级
echo "环境变量:${GAWORLD_CONFIG_OVERRIDES}"
echo "配置文件:"
cat dashboard_config.json

# 2. 检查合并后的最终配置
python -c "from gaworld.settings import get_final_config; print(get_final_config())"
```

### C.13.2　配置错误

如果配置 JSON 解析失败:

```bash
# 验证 JSON
python -c "import json; json.load(open('dashboard_config.json'))"

# 验证 YAML
python -c "import yaml; yaml.safe_load(open('config.yaml'))"
```

### C.13.3　配置版本不匹配

如果升级 GAWorld 后配置不兼容:

```bash
# 查看迁移指南
cat docs/MIGRATION_GUIDE.md

# 运行迁移
python -m gaworld.config migrate old_config.json new_config.json
```

### C.13.4　配置污染

如果不同项目的配置混在一起:

- 严格按项目分目录
- 每个项目独立 dashboard_config.json
- 配置改动不跨项目

---

## C.14　扩展:配置与可观测性

### C.14.1　配置追踪

每次运行都记录配置:

```python
# 自动保存运行配置
import json
from datetime import datetime

run_config = {
    "timestamp": datetime.now().isoformat(),
    "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip(),
    "config_snapshot": dashboard_config,
    "command": " ".join(sys.argv)
}
with open(f"output/{run_id}/config.json", "w") as f:
    json.dump(run_config, f, indent=2)
```

### C.14.2　配置差异

不同运行的配置差异:

```python
def diff_configs(c1: dict, c2: dict) -> list:
    """配置差异"""
    changes = []
    # 深度比较
    ...
    return changes
```

### C.14.3　配置告警

如果某个配置字段偏离正常值,告警:

```python
def alert_on_unusual_config(config: dict):
    """异常配置告警"""
    if config["llm"]["temperature"] > 0.8:
        alert("LLM 温度太高,可能不稳定")
    if config["simulation"]["default_sim_days"] > 365:
        alert("仿真天数超过 1 年,检查成本")
```

### C.14.4　配置可视化

把配置文件渲染成 HTML,便于浏览:

```python
def config_to_html(config: dict) -> str:
    """配置转 HTML"""
    # 用 Jinja2 渲染
    ...
```

---

## C.15　本附录教学注释(扩展版)

- 配置分层策略支持多场景(教学/研究/生产)。
- 高级配置:多 LLM、加密存储、远程配置中心、审计。
- 配置示例集覆盖了教学、研究、生产、小型实验。
- 配置诊断:不生效、错误、版本不匹配、污染。
- 配置与可观测性:追踪、差异、告警、可视化。

