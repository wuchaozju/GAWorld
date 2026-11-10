# 谣言扩散与灾害模拟改进交付记录

日期：2026-11-10。范围：用户确认的完整方案；复用当前工作区，保留其他聊天与用户的并发修改。

## 改动结果

1. 谣言局将相信程度、行动和动机分开。支持相信内容、提醒亲友、娱乐玩梗、社交互动、表达情绪、求证、纠正信息、不参与、未说明；不设置目标转发率。每一跳传递实际转述，保留逐轮事件和收到的消息。发送者内部自报动机只在审计中保存，接收者不能直接知道。社会证明仅取相邻节点上一轮状态。
2. 灾害新增保护家人、转移财产、等待官方通知；主行动与次要行动分开。五档恐慌描述完整，并说明为模型角色自报。家庭外互助与保护家庭分开。
3. 总反应人次与有效行动、恐慌、互助分母分开；解析失败与缺失不再补成恐慌3分或不互助。无有效分母显示缺失。页面、逐幕汇总、Markdown 导出同步展示质量信息。
4. 有限容错恢复单引号、JSON布尔量、尾逗号；拒绝执行表达式；限制输入长度和嵌套深度。非字符串原话/细节不直接转成JSON文字显示。未解析回答标为未解析，原文只放诊断。
5. 灾害读取已有地域资料。洪水按山区、沿海、水乡提供不同三幕；其他内置灾害保留主线并附加地域约束。自定义剧本保留原文，缺资料回退通用情境。依据、资料来源与假想情境说明随结果保存。
6. 优先读取当前世界或所选城市已有的居民关系；过滤 ghost，再用同住址、同行或同龄推断缺失联系。推断不作为真实关系验证，同姓不作为亲属证据，亲子/祖孙使用中性关系标签。每幕只沿边发送上一幕消息；停电断网阻断远程消息，直至明确恢复。保留送达和阻断事件。
7. 新结果标记 `rumor-2` / `disaster-2`。基准报告拒绝合并不同机制版本，灾害基准也按各字段有效分母计算，不再把缺失互助回答当false。旧存档不会被改写。

## 文件职责

- `gaworld/apps/game_reactions.py`：有界结构化回复恢复及量表、布尔字段校验。
- `gaworld/apps/disaster_context.py`：地域情境、只读关系读取、阶段同步消息与通信阻断。
- `gaworld/apps/game_measurements.py`：存档口径与机制版本检查；`benchmark/gaworld_bench.py` 为薄接入。
- `gaworld/apps/disaster_api.py` / `rumor_api.py`：原有 API 与任务执行的集成。
- `site/dashboard/disaster.{html,js}`、`rumor.{html,js}`、`game-export.js` 与中英文 locale：页面、逐轮审计、口径与导出。
- `docs/PLAYGROUND_TUTORIAL.md`：同步玩法、口径与局限。

## 验证结果

- `python -m pytest tests/test_game_mechanisms.py tests/test_disaster_api.py tests/test_rumor_api.py tests/test_games_api.py tests/test_game_archive.py benchmark/test_gaworld_bench.py -q`：169 passed，5 subtests passed。
- 独立审查复跑机制回归：28 passed；已修复动机泄漏和亲属方向标签，无剩余阻止交付的发现。
- `node site/dashboard/game-export.test.js`：13 passed；三个修改后的浏览器脚本均通过 `node --check`。
- `python -m pytest --suite core -q --disable-warnings`：515 passed，1 skipped，978 subtests passed；跳过项因未安装可选 openapi-spec-validator。现有绘图字体警告96条。
- 单独 OpenAPI：11 passed，1 skipped，917 subtests passed。首次执行曾遇到并发人口恢复路由未登记，其他聊天随后补齐，重跑已通过。
- 本次8个Python文件的 Ruff检查与格式检查全部通过。既有 benchmark 文件的 Ruff findings 11→11，无新增。
- 全工作区 lint ratchet 最后检查仍有3项，均来自本次范围外的并发文件：`gaworld/research/model_provenance.py` 格式；`tests/test_serious_game_validity.py` 的6项lint与格式。未替其他任务修改这些文件或基线。
- 使用 agent-browser 独立会话与临时只读夹具服务器验证实际页面：灾害6次尝试、5个有效互助回答、1次互助、1次解析失败显示为20%与1/5；解析失败不在原话区显示原始文本。谣言3人均相信2%但玩梗逐跳转发，页面显示0人相信、3人娱乐转发与3人不信仍转发。中英文新增指标、亮色/暗色与两个页面的390px视口检查通过。浏览器未运行真实模型。

## 使用及边界

代码生效需要后端进程加载新代码、浏览器刷新脚本。没有重启用户现有服务，没有运行付费模型实验，没有部署、提交或重建任何人口数据。

同住址可见接触、固定联系推断与地域模板都是明确的简化假设；已有关系也不是现实关系证据。缺少地域档案的城市继续使用通用情境，不根据城市名字编造资料。除洪水外，其他灾害尚未建立独立的完整地域灾害动力学模型。

离线回归证明新分支、信息边界和统计口径可用，不证明模型在真实调用时一定表现出某一传播比例，更不证明与真实人类行为等价。旧版本结果保留原口径并给出提示，不自动重算。
