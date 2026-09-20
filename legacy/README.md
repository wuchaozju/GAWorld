# legacy/

这个目录保存迁移到 `gaworld/` 包之前的旧模块文件。

**这些文件已不再维护。** 所有功能均已迁移到 `gaworld/` 包中：

| 旧模块 | 新位置 |
|---|---|
| `avatar_generator` | `gaworld.io.avatar` |
| `city_map_system` | `gaworld.world.city_map` |
| `config` | `gaworld.settings` |
| `distributed_comm` | `gaworld.distributed.comm` |
| `dynamic_behavior` | `gaworld.behavior.dynamic` |
| `economy_module` | `gaworld.economy.finance` |
| `environment` | `gaworld.env.system` |
| `experience_store` | `gaworld.memory.experience` |
| `extensibility` | `gaworld.hooks` |
| `human_realism` | `gaworld.cognition.realism` |
| `intervention_policy` | `gaworld.policy.intervention` |
| `life_events` | `gaworld.events.life` |
| `llm_providers` | `gaworld.llm.providers` |
| `memory_store` | `gaworld.memory.store` |
| `simulation_visualizer` | `gaworld.apps.visualizer` |
| `social_network` | `gaworld.social.network` |

旧脚本：`analyze_wellbeing.py`、`generate_agent_rag_seed.py`、`custom_hooks.py`
