# 任务规划:个人发展与兴趣系统增强(科学家团队设计)

## 目标
以多学科虚拟专家小组(发展心理学、行为科学、复杂系统、ML/仿真工程)评审现有个人发展与兴趣系统,产出增强设计并实现+测试。

## 阶段
- [x] 阶段1:调研现有系统(interests.py、_curiosity.py、skills/、sim 接入点、测试)
- [x] 阶段2:专家小组评审,写设计文档 docs/proposals/2026-07-04-personal-growth-v2.md
- [x] 阶段3:实现增强(按设计文档范围)
- [x] 阶段4:补测试,跑全量测试验证(新增18测试全过;全量527过,6失败均在干净HEAD复现,为存量问题)
- [x] 阶段5:更新 CHANGELOG,收尾

## 约束与注意事项
- 新代码只写进 gaworld/ 包(AGENTS.md 规则)
- 项目守则:最小改动、外科手术式修改、不做投机性抽象
- LLM 失败不能中断仿真(本次全部纯规则,零新增 LLM 调用)
- 持久化格式向后兼容(agent_N_growth.json 未改 schema)
- 经济系统刚改造过(P0-P3),勿动经济不变量(未触碰)

## 错误记录
- 在挂载 repo 里执行 `git stash` 失败(沙盒对 .git 内文件 unlink 无权限),留下 stale `.git/index.lock`(0 字节,14:41),沙盒里 rm 也被拒。工作区文件未受影响(改动都在)。教训:此挂载 repo 内不要做需要写 index 的 git 操作;基线对比改用 `git archive HEAD`(只读)。index.lock 需用户在宿主机删除:`rm /Users/cw/dev/GAWorld/.git/index.lock`
- 注意:stash@{0} "!!GitHub_Desktop<main>" 是用户 GitHub Desktop 的存量 stash,勿动
- 沙盒 python 是 3.10,项目要求 ≥3.11;已用 uv 建 /tmp/gaw-venv(3.11.15)跑测试
