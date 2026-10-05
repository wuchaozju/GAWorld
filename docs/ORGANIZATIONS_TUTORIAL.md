# 持久组织：社区资助与企业招聘

组织有稳定 ID、目标、负责人、成员、版本化规则和有限账户。名称、目标修改和负责人交接都不清空历史；关闭会停止新的申请与招聘，已有员工仍保留雇佣关系与工资义务，账目和欠付继续保留。第一版使用确定性规则决策，没有额外组织模型调用。

## 启用与入口

控制台 **配置 → 持久组织** 将 `organizations.enabled` 开启，经济系统也须开启。在 **组织** 页创建社区或企业，或使用 `python -m gaworld.organizations`。管理操作只提交命令；界面的“排队等待”表示尚未执行。下一次启用组织的仿真，在日开始时执行命令，再冻结候选信息并决策。正在运行时提交的命令同样等待下一日边界。

支持单机逐 tick 与按日快进。月/年快进、分布式世界、关闭经济的组合在启动之前拒绝。配置默认关闭，原有财务付款、审计列和随机数路径保留。只管理名册或排队而未运行时，不会产生付款。

启用后，日初先同步返回员工的待执行离职，再运行经济初始化；组织随后执行排队命令、资助与招聘决策，刷新就业统计，旅行模块最后按当天的雇佣关系支付年假工资。当天人工设置的宏观失业率仍优先生效，实际劳动力人数另行更新。

## 社区资助

创建组织时登记成员和负责人、预算及拨款来源，选择 `equal_split`（等额分配）或 `need_first`（困难优先），可设置 `max_award_cents` 单人上限。金额单位是整数分。

等额分配在申请额、单人上限与总预算内分配，剩余分币用组织种子确定顺序。困难优先先比较本批次资助前的活期加储蓄余额，现金相同再比较已登记的同住受抚养人数，最后以种子打破平局。受抚养人数定义为同住的未成年子女、65 岁及以上父母；缺少家庭登记则注明缺失，仅按现金排序。缺少现金不视为零，无法通过困难资格评估。

默认资格：有效成员、满 18 岁、同一批次最多一项合格申请。申请额、冻结信息、规则版本、等待天数、拒绝原因与实际资助均可查看。居民选择受控的申请动作也会提交同一队列，自由叙述“已得到钱”不能改变账户。

收款人须有已初始化的独立经济账户。由家庭系统提升为居民、仍由家庭统一承担支出的受抚养成员没有该账户，会以 `economic_account_missing` 拒绝申请；不会让整个组织进入支付故障。

CLI 排队示例（替换为当前世界实际居民 ID）：

```sh
python -m gaworld.organizations command --json '{"type":"create","organization_id":"care","name":"互助会","kind":"community","leader_id":1,"member_ids":[1,2,3],"initial_balance_cents":30000,"funding_source":"government","rule":"need_first","rule_params":{"max_award_cents":15000}}'
python -m gaworld.organizations command --json '{"type":"apply_aid","organization_id":"care","agent_id":2,"amount_cents":15000,"reason":"本月生活困难"}'
python -m gaworld.organizations commands
```

## 企业与工资

企业创建后发布岗位：职业、名额、月薪、最低 `income_skill` 与地点。`lottery` 在资格达标者中确定性抽签；`skill_first` 按现有经济能力代理 `income_skill` 从高到低排序，同分用组织种子。该字段属于模型假设，不能当作经过现实验证的能力测量。缺失资格值会明确拒绝。

录用同步居民职业、雇佣状态与工资。岗位不超额，居民最多有一家企业雇主；主动转职释放旧岗位，退休、失业和外部工作变更也会解除旧付款关系，欠薪保留。负责人可以停止在本企业工作而继续担任负责人。

`remove_member` 解除员工合同并释放岗位。员工暂时不在本次居民名单时，离职记录等待其返回，在日初经济统计和旅行年假付款前同步就业状态；后来获得的新工作会保留。正常续跑从经济记录恢复职业与就业状态，不会重复生成离职事件。

```sh
python -m gaworld.organizations command --json '{"type":"create","organization_id":"workshop","name":"工作坊","kind":"company","leader_id":1,"initial_balance_cents":1000000,"funding_source":"firms","rule":"skill_first"}'
python -m gaworld.organizations command --json '{"type":"publish_job","organization_id":"workshop","job_id":"design","occupation":"设计师","vacancies":1,"monthly_salary_cents":400000,"min_income_skill":0.5}'
python -m gaworld.organizations command --json '{"type":"apply_job","organization_id":"workshop","job_id":"design","agent_id":2}'
```

逐 tick 工资、按日快进工资、带薪休假、工资型奖金及雇主住房公积金由企业组织账户支付。投资回报、商户分成继续沿既有来源支付。企业余额不足时只支付可用部分，未付款形成欠付义务；没有自动贷款或营业收入。补充资金优先还欠付；暂时不活跃的员工不新发工资，旧欠付保留并预留相应资金，重新参与后在日边界偿还。

补发旧工资或奖金会计入实际收款日的收入，但按日快进仍单独计算当天劳动义务。当天已经登记的年假工资，即使企业只能部分支付或无法支付，也不会再生成一笔快进工资；未付部分留在欠付记录中。

## 钱从哪里来

初始和后续拨款来自显式登记的 `government` 或 `firms` 部门池。部门池按既有模型允许负余额，组织账户不能透支。资助是转移收入，不进入劳动税基。工资复用已有劳动收入和税费口径。付款与等额来源扣款、实际金额、未支付金额、交易 ID 和用途都记录；开启时的经济守恒审计增加 `organizations_total`。

名称与目标、交接、拨款、规则变更示例：

```sh
python -m gaworld.organizations command --json '{"type":"update_profile","organization_id":"care","name":"河畔互助会","goal":"优先保障困难成员的基本生活"}'
python -m gaworld.organizations command --json '{"type":"handover","organization_id":"care","leader_id":2}'
python -m gaworld.organizations command --json '{"type":"fund","organization_id":"workshop","amount_cents":100000,"source":"firms"}'
python -m gaworld.organizations command --json '{"type":"set_rule","organization_id":"care","rule":"equal_split","rule_params":{"max_award_cents":15000}}'
python -m gaworld.organizations detail care
python -m gaworld.organizations history care --limit 100
```

在组织页选择“修改名称与目标”也会提交 `update_profile`。可只提交 `name` 或 `goal`；名称不能为空。修改保留组织 ID、世代、成员、规则版本、余额与过去的决策，并记录修改前后的值及操作者。正在运行时等待下一日边界生效，关闭的组织不能再修改名称与目标。

## 组织治理：提案—表决—执行

治理是独立开关，默认关闭。在配置的持久组织区开启 `organizations.enabled` 和 `organizations.governance.enabled`，例如：

```json
{"organizations":{"enabled":true,"governance":{"enabled":true,"mode":"member_vote","threshold":"quorum_majority","voting_days":1}}}
```

这段是配置片段；保留原有运行路径、经济配置和种子。治理不额外调用模型，居民继续使用现有行动选择。新组织使用配置中的默认治理方式；正常续跑的已有组织第一次启用时登记默认政策，此后以组织自身持久政策为准。也可在 create 命令中指定 `governance`，或在组织页选择 **设置组织治理**。

方式包括 `off`（关闭该组织治理）、`leader`（负责人决定）和 `member_vote`（成员表决）。成员可提案修改社区的资助规则与单人上限，或企业的招聘规则。提案不能改变资金、工资、成员资格和负责人；每个组织同时处理一个未完成提案。

成员表决默认 `quorum_majority`：至少半数有资格成员参与，赞成多于反对。弃权计入参与人数，平票不通过。`electorate_majority` 要求全体有资格成员过半赞成；`simple_majority` 不设参与门槛，只比较赞成与反对。没有参与或未满足参与门槛为 `expired`，其余未通过为 `rejected`。负责人模式只接受提案开启时负责人的赞成或反对。

以下使用当前世界已有组织 care；每条命令同样等待日边界。先设置治理，再开启提案，看到提案为 open 后才提交票：

```sh
python -m gaworld.organizations command --json '{"type":"set_governance","organization_id":"care","governance":{"mode":"member_vote","threshold":"quorum_majority","voting_days":1}}'
python -m gaworld.organizations command --json '{"type":"propose_rule","organization_id":"care","agent_id":1,"proposal_id":"aid-reform","rule":"equal_split","rule_params":{"max_award_cents":20000},"reason":"希望提高支持额度并等额分配"}'
python -m gaworld.organizations command --json '{"type":"cast_vote","organization_id":"care","proposal_id":"aid-reform","agent_id":1,"choice":"yes","reason":"支持提高额度"}'
python -m gaworld.organizations command --json '{"type":"cast_vote","organization_id":"care","proposal_id":"aid-reform","agent_id":2,"choice":"abstain","reason":"暂不确定"}'
```

如果该组织只有三名有资格成员，上例两票构成参与门槛，赞成 1、反对 0、弃权 1 可以通过。负责人模式用 `leader_decide` 替换 `cast_vote`，只允许负责人，选择为 `yes` / `no`。控制台的“代成员提交规则提案”“代成员投票”“代负责人决策”是研究者代理操作，仍由执行时的资格检查决定是否接受。

时间分开记录：Day D 日边界开启，截止为 D + voting_days；默认 1 天时，Day D 行动产生的票在 Day D+1 日边界接收并结算，批准后的规则在 Day D+2 日边界执行。例如 Day 1 开启、Day 2 通过、Day 3 生效。截止日边界之后入队的票不能追补；通过当天仍使用旧规则。新规则生效后，沿已有资助和招聘执行层决策，没有直接发钱或叙述改账。

提案开启时固定未退出成员名单、负责人、规则与治理版本。缺席成员保留在成员表决分母中，后加入者不能参与旧提案；开启后退出者保留旧提案资格，但实际投票必须是本次运行中的居民。模型不额外设置投票年龄限制。首次有效选择不可改，相同选择重发不重复计票；理由缺失如实显示“未提供”。开放期间居民只感知自己的票，截止后感知总票数，研究者控制台可查看完整票记录。

人工改规则、改治理方式或关闭组织会让未决提案失效；负责人模式中发生交接也会失效，包括交接后又交回。已通过、尚未执行的决议遇到这些变化时记录 `execution_failed`，保留 `decision_outcome=approved`。队列按入队顺序执行：治理执行命令早于后来的人工命令时，先执行治理，再执行人工修改，各自有独立版本和历史。

正常日边界恢复保留提案、票和待执行命令；新世代不能接收旧世代治理命令。关闭全局治理后，未决提案失效，尚未执行的批准记录执行失败，不继续改变规则。中断日仍适用下一节的恢复约束。

组织详情增加 proposals / ballots；提案连起前后规则、固定成员、政策、来源、理由、决议与执行日、执行命令及执行规则版本。有效组织输出目录另有 `governance.json`，每个完成日也归档一份。其范围为本世代累计，参与率的分子/分母按已结算成员表决的参与席位/有资格席位求和，不能当作独立居民人数，也不要把每日累计文件相加。已有经济 metrics.json / CSV 的口径保持原样。记录器增加 `organizations.governance.proposal`、`.ballot`、`.resolution`、`.execution`、`.policy` 事件。

这些记录便于比较模型中的组织过程；治理方式的现实有效性仍需另行研究设计与验证。

## 持久化、隔离和恢复

`stateful=true` 在正常日边界续跑，`stateful=false` 开始新世代。只读 API 可带 `generation_id` 查看旧世代；CLI 可用 `--generation <id>` 读取旧名册和历史，不能向旧世代写入。组织状态位于有效 `memory_dir/organizations.sqlite`，经济回执与居民账户一起保存，组织经济检查点也在 memory 目录。城市、账号世界和平行实验通过既有运行路径隔离；CLI 可用 `--world <已有世界ID>` 选择本地世界。API 只能操作当前世界，客户端不能指定存储路径，写入限世界拥有者或管理员。

旧世代的列表返回该世代最后完成日与恢复标记，执行状态为 `historical_read_only`。更早、没有保存这些元数据的世代返回空值，不借用当前世代的运行状态。

一个目录只允许一个组织执行者。更换居民子集不删除其他成员。居民 ID、姓名、性别、出生日期指纹和人口来源用于发现不兼容的旧状态。组织时间与居民时钟矛盾时拒绝恢复。`python generative_city_sim.py reset` 清理居民与组织运行状态及导出，保留配置中的种子定义。

SQLite 与居民 JSON 不是统一的世界事务。首版保证正常日边界恢复；中途未达到检查点、回执缺失、文件损坏或账目矛盾时显示 `recovery_required` 并停止付款，不能用重试绕过重复支付检查。完整任意 tick 回滚和自动故障修复仍需世界检查点能力。

## 输出和规则对照

有效 `organizations.output_dir` 下有最新 `snapshot.json`、`metrics.json`、`metrics.csv`，并在 `generations/<世代>/day-<日>/` 保留每个完成日的 JSON 快照和指标。记录器还有组织、成员、申请、决策、交易与摘要六类表。每项带世代和日标识；指标说明岗位占用、录用、实付、欠付、预算利用率、等待与拒绝。

社区覆盖率是已实付资助申请数除以已决策合格申请数；企业覆盖率是录用数除以已决策合格应聘数。拒绝按原因统计。分组使用每项申请在决策前冻结的年龄（35 岁以下、35–64 岁、65 岁及以上）、性别和就业状态，保留未知值，并输出申请数、合格数、实付资助、录用、拒绝和等待天数。这里按申请计数，同一个居民跨日申请会重复计数；原始 CSV 的分组列和拒绝原因列使用 JSON 编码。目前未接入研究工作台预注册假设的多来源自动评分。

`gaworld/organizations/examples/equal_lottery.json` 与 `need_skill.json` 提供相同居民、预算、种子下的规则对照配置；分别使用独立运行目录，并在两个世界提交相同申请与岗位命令。不要把两套规则当作现实政策有效性的结论。首版没有生产销售、组织战略、劳资谈判或自动收入反馈。

### 离线生成规则对照报告

在控制台的 **组织** 页点击右上角 **下载 Day N 指标 JSON**，即可保存当前世界最近完成日的原始指标。查看者即使没有管理权限也可以下载；尚未完成第一日时按钮不可用。下载请求固定世代与完成日，文件名包含二者，不会因为正在开始新世代而误取旧的顶层文件。两个世界的文件下载后，可直接作为下列 `compare` 命令的输入。

接口 `GET /api/organizations/exports/metrics` 也可读取当前世界的档案；可选 `generation_id=<世代>&day=<完成日>` 查询历史。参数省略时使用所选世代最后完成日；更早没有完成日元数据的世代必须显式指定 `day`。后续某日尚未完成或需要恢复时，之前已完成日的档案仍可下载。缺失档案返回 404，损坏或标识不匹配返回 409，非法、重复或跨世界路径参数返回 400。

接口返回含 `filename`、`content_type`、`content`、`sha256`、`generation_id`、`day`、`scope` 的 JSON 信封。页面只将 `content` 保存为文件，保留原始 UTF-8 内容和整数金额；不要把整个信封当作 `metrics.json`。SHA-256 对应这个原始文件。客户端不能指定服务器文件路径或其他世界。

两个世界运行完成后，选择同一完成日的 `metrics.json`，可一次比较社区与企业：

```sh
python -m gaworld.organizations compare \
  /path/to/equal-world/organizations/metrics.json \
  /path/to/need-world/organizations/metrics.json \
  --output-dir /path/to/reports/organization-comparison \
  --left-label '等额资助 / 抽签招聘' \
  --right-label '困难优先 / 技能优先'
```

路径替换为两个运行的实际导出位置。最新导出日不同时，使用 `generations/<世代>/day-<日>/metrics.json` 选择同一天。加 `--organization-id mutual-aid` 可只比较一个共有组织。输入文件已经确定来源，因此 `compare` 不接受全局 `--world` 或 `--generation`。

输出目录包含 `comparison.md`（中文表格）、`comparison.json`（完整结构）和 `comparison.csv`（一行一个指标或群体指标）。差值统一为右减左；Markdown 的比例差使用百分点、金额使用元，JSON/CSV 金额保持整数分。报告保留输入绝对路径与 SHA-256、世代、完成日、当前规则及其版本。工具只读导出文件，不打开组织数据库，不运行仿真或调用模型；输出不能覆盖输入文件。无效输入会返回退出码 2。

导出范围必须是 `cumulative_current_generation`，表示截至该日的世代累计值，不应把每天的快照相加。比较器检查同日、组织 ID 和类型、整数金额、申请结果分割、欠付与应付实付的一致性、群体合计与覆盖率分母。覆盖率和平均等待按整数计数重新计算；零分母保留为空，任一侧无分母时差值也为空。未知群体保留，全部零值分组保存在 JSON/CSV 中。

预算利用率使用原始导出的支出比例与累计显式拨款分母；现有指标没有单列支出分币数，工具不会从浮点比例反推金额。拨款的部门来源须查配置和交易历史。当前规则版本大于 1 时，报告提示累计结果可能含有较早规则的决策。

同日、同组织只是文件可比较的必要条件。人口、初始预算、拨款安排、申请输入、种子和代码版本仍须结合原始运行资料核验。报告提供描述性差异；因果推断、重复种子的统计分析和预注册评分需另行设计。

## API

- `GET /api/organizations`：当前世界组织与执行状态。
- `GET /api/organizations/<id>`、`/<id>/history`：实际状态与审计历史。
- `GET /api/organizations/commands`、`/commands/<id>`：排队、已应用或拒绝状态。
- `GET /api/organizations/exports/metrics`：当前世界已完成日的指标下载，可选世代和完成日。
- `POST /api/organizations/commands`：提交命令，返回 202；使用 `command_id` 幂等提交并查询最终状态。

创建、名称与目标修改、加入/退出、交接、拨款、资助申请、岗位发布、应聘、规则修改、关闭，以及治理设置、提案、投票、负责人决策均使用这一命令协议。OpenAPI 包含完整路由和命令字段。
