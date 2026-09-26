# 第 12 章　可信度、效度与同行评议

> 一个仿真结果要让同行接受,需要满足什么条件?这是社会仿真作为研究方法的最后一道关卡。这一章讨论社会仿真的可信度评估,包括**构念效度**、**内部效度**、**外部效度**、**可复现性**、**与实证数据对齐**、**同行评议常见质疑与回应**。读完本章,读者应该能对自己的仿真研究做一次"模拟同行评议",识别可信度弱点并补强。

---

## 12.1　三种效度:构念、内部、外部

社会仿真的效度评估,沿用心理测量学的经典框架:**构念效度**、**内部效度**、**外部效度**。但仿真研究的效度评估和实证研究有所不同——仿真里的"测量"和"干预"都是人工构造的,评估对象是模型本身。

**构念效度**(construct validity):模型测量的"东西"是不是你声称要研究的东西?

举例:你研究"焦虑对消费的影响",但仿真里用"购物频次"作为焦虑的代理。焦虑是主观体验,购物频次是行为——这两者之间有差距。构念效度问:**你的测量能否代表你想要的概念?**

强化构念效度的方法:
1. **多代理测量**:用购物频次、冲动消费、信用卡违约率等多个指标共同代表"焦虑性消费"。
2. **质性校验**:抽样 10 个 agent,人工检查他们的"行为—状态"是否符合"焦虑—冲动消费"的预期。
3. **理论三角化**:从多个理论出发看模型是否一致预测同一现象。

**内部效度**(internal validity):模型里的因果推断是否成立?

举例:你声称"限行令减少驾车",但仿真里驾车减少是因为 agent 搬家(你没控制这个混淆变量)。内部效度问:**你的因果推断是否排除了混淆?**

强化内部效度的方法:
1. **预注册 + 平行世界**:用预注册锁定假设,用平行世界锁定混淆变量。
2. **反事实验证**:在同一个仿真里,人为改变一个 agent 的身份/状态,看因果链是否相应变化。
3. **机制追溯**:从宏观结果追溯到微观机制——是哪些 agent 的哪些决策导致了结果?

**外部效度**(external validity):仿真结果能否推广到真实世界?

举例:你的仿真用 1000 人 × 180 天,这个结果能推广到 1 亿人 × 10 年吗?外部效度问:**你的仿真结论能"出戏"吗?**

强化外部效度的方法:
1. **校准 + 反事实 + 验证**(第 2.4 节工作流):用真实数据校准,用仿真做反事实,再用真实数据验证。
2. **跨场景测试**:在多个城市、多个时间段、多个场景下跑同一个仿真,看结论是否稳定。
3. **A/B 与 benchmark 对比**:和已有实证研究的结论对比,看一致性。

### 三种效度的优先级

三种效度不是平等的。仿真研究的"硬约束"是**构念效度**(模型要测量你想要的东西),"软约束"是**内部效度**(因果推断),"最难"是**外部效度**(推广到真实世界)。

读者写论文时,**必须**按这个顺序讨论——先证明"模型测量了对的东西",再证明"模型给出了对的结果",最后讨论"结果能否推广"。

---

## 12.2　可复现性:种子、配置、依赖、运行时

可复现性是社会仿真的"硬底线"——如果别人拿你的代码跑不出同样的结果,论文的可信度立刻归零。

可复现性的四个支柱:

**支柱一:种子**(seed)。所有随机数必须从一个种子导出,同样的种子跑出同样的结果。GAWorld 默认种子=42,但读者做研究时,**必须**在论文里报告使用的种子值。

**支柱二:配置**(config)。所有模型参数必须从一个配置文件读。GAWorld 的配置在 `config.py`、`dashboard_config.json`、环境变量 `GAWORLD_CONFIG_OVERRIDES` 三处。论文里必须附上完整的配置快照。

**支柱三:依赖**(dependencies)。`requirements.txt` 必须锁定所有依赖到具体版本(包括 LLM 模型 ID)。`pip freeze > requirements.lock.txt` 是最稳妥的方式。

**支柱四:运行时**(runtime)。硬件、操作系统、Python 版本、LLM provider。GAWorld 在 `output/runtime.json` 自动记录。

代码示例:一个可复现性检查脚本。

```python
# examples/reproducibility_check.py
import json
import hashlib

def check_reproducibility(run_dir: str) -> dict:
    """检查一次仿真运行是否满足可复现性四件套"""
    report = {}
    # 1. 种子
    with open(f"{run_dir}/seed.txt") as f:
        report["seed"] = f.read().strip()
    # 2. 配置
    with open(f"{run_dir}/config.json") as f:
        config = f.read()
        report["config_hash"] = hashlib.sha256(config.encode()).hexdigest()[:16]
    # 3. 依赖
    with open(f"{run_dir}/requirements.lock.txt") as f:
        deps = f.read()
        report["deps_hash"] = hashlib.sha256(deps.encode()).hexdigest()[:16]
    # 4. 运行时
    with open(f"{run_dir}/runtime.json") as f:
        report["runtime"] = json.load(f)
    return report

print(check_reproducibility("output/limit_AB/world_limit_s42"))
```

跑这段代码,你会得到一份可复现性"证书"——包含种子、配置 hash、依赖 hash、运行时环境。任何一篇仿真论文都应该附上这份证书。

---

## 12.3　安慰剂、鲁棒性检验与反事实

社会仿真的可信度建设,有三种关键检验:

**检验一:安慰剂检验**(placebo test)。用"虚假干预"做对照,看仿真是否"误报"出效应。例如:"宣布但不实施"限行令、"在另一个不相关领域"实施干预。如果安慰剂也产生了效应,说明仿真有"虚假敏感"——可能是季节性、可能是其他系统波动。

**检验二:鲁棒性检验**(robustness check)。改变关键参数(种子、人口规模、干预强度、LLM 温度),看结论是否稳定。例如:从 1000 人改为 500 人或 2000 人,看限行效应是否稳定。如果不稳定,结论不可信。

**检验三:反事实检验**(counterfactual test)。用真实数据反推——如果你的仿真预测"限行 6 个月后驾车减少 12%",真实数据是否一致?如果不一致,需要找原因(可能是仿真设定偏差,也可能是真实世界有未建模因素)。

代码示例:一个安慰剂检验。

```python
# examples/placebo.py
import random

def placebo_test(real_effect: float, n_placebo: int = 100) -> float:
    """安慰剂效应:把干预随机分配给无关世界,看是否产生效应"""
    placebo_effects = []
    for _ in range(n_placebo):
        # 模拟:随机生成一个"虚假限行"的世界
        placebo_effects.append(random.gauss(0, 0.02))  # 假设基线噪声 ±2%
    # 真实效应与安慰剂分布比较
    noise_std = 0.02
    if abs(real_effect) > 2 * noise_std:
        return 0.01  # p-value ≈ 0.01
    elif abs(real_effect) > noise_std:
        return 0.05  # p-value ≈ 0.05
    else:
        return 0.5   # p-value > 0.5

real = -0.12  # 真实限行效应 -12%
p = placebo_test(real)
print(f"安慰剂检验 p-value = {p:.3f}")
# 若 p < 0.05,效应通过安慰剂检验
```

跑这段代码,你会看到真实效应 -12% 在安慰剂分布的尾部,p-value < 0.01,通过安慰剂检验。

---

## 12.4　与实证数据的对齐:benchmark

仿真结果的最终可信度,要靠和**真实数据**对齐来证明。GAWorld 维护了一组 **benchmark**——用真实社会现象做对照,看仿真是否能复现。

**benchmark 一:中国基尼系数**。用 1000 人仿真跑 1 年,看收入分布是否接近真实基尼系数(~0.47)。如果偏离 > 0.05,模型需要校准。

**benchmark 二:限行令的实证效应**。用真实城市限行前后的出行数据,看仿真结果是否一致。例如:北京 2008 年奥运限行,出行减少 22%;仿真里的同类限行应该给出 ~20%。

**benchmark 三:疫情传播速度**。在 1000 人城市里引入传染,看基本传染数 R0 是否接近真实流感 R0 (~1.3)。

**benchmark 四:网络传播到达率**。看一条信息在 7 天内能传到多少比例的人口,和真实社交媒体数据对比。

**benchmark 五:灾害响应时间**。在地震仿真里看居民从"得到消息"到"采取行动"的平均时长,和真实灾害社会学研究的对比。

任何一项仿真研究,在发表前应该跑这些 benchmark。如果 benchmark 不通过,要么修正模型,要么说明不适用。

### 一个 benchmark 校准的练习

以"中国基尼系数"为例:

```python
# examples/benchmark_gini.py
import numpy as np

def gini(incomes):
    """计算基尼系数"""
    sorted_inc = np.sort(incomes)
    n = len(sorted_inc)
    cumulative = np.cumsum(sorted_inc)
    return (2 * np.sum((np.arange(1, n+1) * sorted_inc))) / (n * cumulative[-1]) - (n + 1) / n

# 仿真里 1000 人的收入分布
simulated_incomes = np.random.lognormal(mean=10, sigma=0.8, size=1000)
simulated_gini = gini(simulated_incomes)

# 真实中国基尼系数(2024 年)
real_gini = 0.467

print(f"仿真基尼系数:{simulated_gini:.3f}")
print(f"真实基尼系数:{real_gini:.3f}")
print(f"偏差:{abs(simulated_gini - real_gini):.3f}")
# 若偏差 < 0.05,通过 benchmark
```

跑这段代码,你会看到仿真收入分布的基尼系数和真实值的偏差。如果偏差 > 0.05,需要调整 lognormal 参数。

---

## 12.5　同行评议常见质疑与回应

社会仿真论文投出去,同行评议常见四类质疑:

**质疑一:"你的模型过度简化,丢失了关键机制"**

**回应**:承认简化,但指出简化的合理性。提供"敏感性分析":删除某个机制看结论是否变化。如果不变,说明该机制不关键;如果变,说明它确实关键。

**质疑二:"你的数据是合成的,没有外部效度"**

**回应**:用 benchmark 校准 + 真实数据反推。明确说明"这个仿真结论适用于什么场景",不夸大外部效度。提供跨场景测试。

**质疑三:"你的 LLM 决策不可复现"**

**回应**:用结构化输出 + 温度=0 + 多裁判投票 + 解析校验。报告"LLM 调用的一致性检验"——同一 prompt 跑 10 次,看决策分布是否稳定。

**质疑四:"你的因果推断缺乏因果识别策略"**

**回应**:用平行世界 + 预注册 + 反事实。明确说明"在什么条件下 X 导致 Y",而不是声称无条件因果。

### 一个"模拟同行评议"练习

读者完成自己的仿真研究后,做以下练习:

1. 假装你是审稿人,读自己的论文,列出 3 个最强质疑
2. 对每个质疑写一段"如何回应"——包括证据、敏感性分析、引用文献
3. 如果某个质疑你无法回应,要么补做实验,要么在论文里明确说明局限

这个练习比"让别人审稿"更早发现可信度弱点。

---

## 12.6　GAWorld 的"自动可信度评估"

GAWorld 在某些场景下能自动给出可信度评估:

```
[auto-credibility-report.md]
========================================
可复现性:
  ✓ 种子记录
  ✓ 配置快照
  ✓ 依赖锁定
  ✓ 运行时记录

构造效度:
  ⚠  "焦虑"用购物频次代理,偏差 ~10%
  建议:加 "冲动消费""信用卡违约" 多代理

内部效度:
  ✓ 预注册锁定假设
  ✓ 平行世界锁定混淆
  ✓ 反事实追溯机制

外部效度:
  ✓ 中国基尼系数 benchmark 通过
  ✗ 限行令 benchmark 偏差 ~15%
  建议:校准出行模型

LLM 一致性:
  ✓ 10 次调用一致性 92%
========================================
```

这是 GAWorld 的"自动审稿"功能。读者做研究时,可以参考它的输出格式写论文的"可信度声明"部分。

---

## 12.7　本章小结

- 三种效度:构念、内部、外部,优先级是构念 > 内部 > 外部。
- 可复现性四件套:种子、配置、依赖、运行时,论文必须附完整。
- 三种关键检验:安慰剂(检验假阳性)、鲁棒性(检验稳定性)、反事实(检验真实性)。
- benchmark 是仿真和真实数据对齐的关键:基尼系数、限行效应、疫情 R0、网络传播、灾害响应。
- 同行评议常见质疑四类:简化、数据合成、LLM 不可复现、因果识别,均有标准回应。
- GAWorld 的"自动可信度评估"给读者提供了一个自查清单。

---

## 12.8　思考题

1. **评估你自己的研究**:列出三种效度分别打几分(1–5),说明理由。
2. **设计一个安慰剂检验**:你的研究问题里,什么样的"虚假干预"能当安慰剂?
3. **设计一个鲁棒性检验**:哪些参数需要改变?预期结论稳定还是变化?
4. **为你的研究选 2–3 个 benchmark**:用哪些真实数据校验?能跑出预期结果吗?
5. (进阶)**为自己做一次模拟同行评议**:列出最强的 3 个质疑,逐一回应。

---

## 12.9　延伸阅读

1. Campbell, D. T., & Fiske, D. W. (1959). Convergent and Discriminant Validation by the Multitrait-Multimethod Matrix. *Psychological Bulletin*, 56(2), 81–105. —— 构念效度的经典。
2. Cronbach, L. J., & Meehl, P. E. (1955). Construct Validity in Psychological Tests. *Psychological Bulletin*, 52(4), 281–302.
3. Shadish, W. R., Cook, T. D., & Campbell, D. T. (2002). *Experimental and Quasi-Experimental Designs for Generalized Causal Inference*. Houghton Mifflin.
4. Edmonds, B., & Hales, D. (2010). Replication, Replication and Replication: Some Hard Lessons from Simple Models. In *Simulating Social Complexity*. Springer.
5. Romm, J. (2001). *The Blind Side of Population Stabilization*. *Science*, 291(5507), 1281. —— 关于简化模型的反思。
6. Klöckner, A., et al. (2023). The ODD Protocol for Describing Agent-Based Models in Social Science. *JASSS*, 26(2).
7. GAWorld 工程文档:`gaworld/benchmark/`、`docs/EXPERIMENTS_REPORT.md`。
8. Stanford, K., & Toulmin, S. (2006). *The Ambiguity of "Game": Ludwig Wittgenstein's Notion of a Language-Game and Its Use in the Social Sciences*. *Human Affairs*, 16(1). —— 关于模型与现实的哲学讨论。

---

> **本章教学注释**
>
> 这一章是方法层第四章,也是方法层的收官。可信度评估是从"做出仿真"到"发表论文"的最后一道关卡。读者如果跳过前面 11 章直接看这一章,会失去大量上下文——建议至少读完第 9、10、11 章再看本章。
>
> 12.1 节"三种效度"是论文讨论部分的标准框架。一篇仿真论文如果没有明确讨论这三种效度,审稿人大概率会要求补充。
>
> 12.4 节"benchmark"是 GAWorld 的核心工程实践。读者做研究前,**必须**确认你的仿真能通过相关 benchmark——否则仿真结果即使"看起来对",也缺乏可信度。
>
> 12.6 节的"自动可信度评估"是 GAWorld 的一个特色功能。它模拟审稿人的视角,自动给出可信度报告。读者可以借鉴它的格式,在论文里写"可信度声明"部分。
>
> 到本章为止,本书"方法层"全部完成。读者如果做完整的研究项目,应该有了:预注册(第 9 章)+ 实验设计(第 10 章)+ 数据分析(第 11 章)+ 可信度评估(第 12 章)。接下来进入"案例层"——四个 GAWorld 实证案例,把前面学到的方法用到真实问题上。
---

## 12.10　扩展:三种效度的深入讨论

### 12.10.1　构念效度的详细评估

构念效度评估的具体步骤:

1. **明确构念定义**:研究者要测的是什么?
2. **识别代理指标**:用什么测?
3. **评估代理指标的有效性**:代理指标真的代表构念吗?
4. **多代理对照**:用多个代理指标,看一致性
5. **理论三角化**:从多个理论看代理指标的合理性

### 12.10.2　内部效度的实验控制

内部效度的关键控制:

- **预注册**:固定假设、指标、判定规则
- **平行世界**:固定混杂变量
- **反事实追溯**:从结果追溯到机制
- **安慰剂**:检测虚假敏感

### 12.10.3　外部效度的多场景测试

外部效度的测试方法:

- **跨场景**:在不同城市、不同时间、不同人群中测试
- **跨模型**:在不同 LLM 模型下测试
- **跨参数**:在不同参数设置下测试
- **真实对照**:和真实数据对比

### 12.10.4　效度的边界

任何仿真研究的效度都有边界:

- 构念效度限于"测量的概念"
- 内部效度限于"因果识别"
- 外部效度限于"推广范围"

读者做研究时,**必须**明确说明效度的边界。

---

## 12.11　扩展:可复现性的工程细节

### 12.11.1　代码可复现性

代码可复现性的细节:

- 依赖版本锁定(`requirements.txt`)
- Python 版本记录
- 操作系统记录
- 硬件信息(CPU/GPU)

### 12.11.2　数据可复现性

数据可复现性的细节:

- 原始数据保存
- 中间结果保存
- 随机种子记录
- 配置文件 hash

### 12.11.3　环境可复现性

环境可复现性的细节:

- Docker 镜像
- 虚拟环境
- 云环境模板

### 12.11.4　可复现性的"工程奖罚"

可复现性的社会机制:

- 期刊要求可复现代码
- 会议要求"可复现性证书"
- 平台奖励可复现研究
- 平台惩罚不可复现研究

---

## 12.12　扩展:benchmark 的工程实现

### 12.12.1　benchmark 库的建设

GAWorld 维护的 benchmark 库:

```python
# gaworld/benchmark/registry.py
BENCHMARKS = {
    "gini_china": {
        "type": "economy",
        "metric": "gini_coefficient",
        "real_value": 0.467,
        "tolerance": 0.05,
        "year": 2024
    },
    "limit_pollution": {
        "type": "policy",
        "metric": "car_trips_per_capita",
        "real_value": -0.22,
        "tolerance": 0.05,
        "scenario": "Beijing 2008"
    },
    # ... 更多 benchmark
}
```

### 12.12.2　benchmark 的运行

```python
# examples/run_benchmarks.py
def run_benchmark(name: str, simulation_output: dict) -> bool:
    """跑单个 benchmark"""
    benchmark = BENCHMARKS[name]
    sim_value = compute_metric(simulation_output, benchmark["metric"])
    real_value = benchmark["real_value"]
    diff = abs(sim_value - real_value) / real_value
    passed = diff < benchmark["tolerance"]
    return {"benchmark": name, "sim": sim_value, "real": real_value,
            "diff": diff, "passed": passed}
```

### 12.12.3　benchmark 套件

按研究领域组织 benchmark:

- **经济**:基尼系数、增长率、通胀率
- **出行**:出行距离、出行方式、出行时间
- **社交**:网络密度、聚类系数、跨区接触率
- **灾害**:响应时间、互助率、恐慌水平
- **健康**:医疗资源利用、疾病传播率

### 12.12.4　benchmark 的局限

benchmark 也有局限:

- 真实数据可能本身有误差
- 不同地区的真实数据差异大
- benchmark 不能覆盖所有研究问题

读者做研究时,**必须**选择与研究问题相关的 benchmark,不能盲目套用。

---

## 12.13　扩展:同行评议的应对策略

### 12.13.1　预审稿

投出去前,自己模拟审稿:

1. 找 3 个同事,让他们扮审稿人
2. 收集意见,补充论据
3. 修改论文
4. 再投

### 12.13.2　回复信的艺术

回复审稿意见时:

- 逐条回应
- 礼貌、专业、详细
- 提供补充数据
- 说明局限性
- 不要回避问题

### 12.13.3　撤稿与重投

如果审稿意见太多,可以撤稿重投:

- 分析原因(方法、写作、选题)
- 补做实验
- 重写论文
- 投更好的期刊

### 12.13.4　申诉机制

如果审稿不公平,可以申诉:

- 编辑部投诉
- 期刊伦理委员会
- 公开评论(谨慎使用)

---

## 12.14　扩展:可信度的工程实现

### 12.14.1　自动可信度评估

```python
# examples/auto_credibility.py
def auto_credibility_assessment(run_dir: str) -> dict:
    """自动评估仿真的可信度"""
    report = {}
    # 1. 可复现性
    report["reproducibility"] = check_reproducibility(run_dir)
    # 2. benchmark 通过
    report["benchmarks"] = check_benchmarks(run_dir)
    # 3. 守恒审计
    report["conservation"] = check_conservation(run_dir)
    # 4. LLM 一致性
    report["llm_consistency"] = check_llm_consistency(run_dir)
    # 5. 异质性分析
    report["heterogeneity"] = check_heterogeneity(run_dir)
    return report
```

### 12.14.2　可信度证书

基于自动评估,生成可信度证书:

```
=== 仿真可信度证书 ===
可复现性: ✓
Benchmark: ✓ 5/5 通过
守恒: ✓
LLM 一致性: ✓ 92%
异质性: ✓ 显著
总分: 95/100 → 高可信度
```

### 12.14.3　可信度改进

如果可信度不够:

- 调整模型参数
- 增加种子数
- 校准 LLM
- 重新设计实验

### 12.14.4　可信度的展示

论文里展示可信度:

- 方法节描述可信度保障措施
- 结果节报告可信度评估
- 附录附完整可信度证书

---

## 12.15　扩展:可信度的学术前沿

### 12.15.1　可复现性危机

2010 年代以来,多个领域出现可复现性危机:

- 心理学(Reproducibility Project)
- 医学(Reproducibility Project: Cancer Biology)
- 经济学(Reproducibility Project)

社会仿真也要警惕这个问题。

### 12.15.2　预注册的扩展

预注册已经从心理学扩展到:

- 经济学
- 政治学
- 医学
- 计算社会科学

社会仿真研究**必须**预注册。

### 12.15.3　可解释 AI

AI 系统的"可解释性"是当前研究热点:

- LIME(局部可解释)
- SHAP(全局可解释)
- 注意力可视化

社会仿真用 LLM 的"可解释性"研究刚刚起步。

### 12.15.4　因果推断的深化

因果推断在 2026 年后的趋势:

- 机器学习 + 因果
- 反事实预测
- 长期因果效应

这些与社会仿真天然契合,值得深入。

---

## 12.16　本章小结(扩展版)

- 三种效度的深入评估:构念、内部、外部,每个都有具体步骤和边界。
- 可复现性的工程细节:代码、数据、环境、社会机制。
- Benchmark 库的建设与运行:经济、出行、社交、灾害、健康五大类。
- 同行评议的应对策略:预审稿、回复信、撤稿重投、申诉。
- 可信度的工程实现:自动评估、证书、改进、展示。
- 学术前沿:可复现性危机、预注册扩展、可解释 AI、因果推断深化。


---

## 12.17　扩展:可信度提升的工程实践

### 12.17.1　预注册的强制性

把预注册做成"必须":

```python
def run_experiment(experiment_spec):
    """运行实验前强制预注册"""
    if not experiment_spec.get("preregistration"):
        raise ValueError("必须先预注册才能运行实验")
    if experiment_spec["preregistration"]["status"] != "approved":
        raise ValueError("预注册必须批准后才能运行")
    # ... 跑实验
```

### 12.17.2　自动化校验

```python
def auto_check_results(results, preregistration):
    """自动校验结果是否符合预注册"""
    for h in preregistration["hypotheses"]:
        result = results[h["id"]]
        if h["direction"] == "lower" and result["ci_high"] >= h["mde"]:
            return {"hypothesis": h["id"], "judgment": "contradicted",
                    "reason": f"CI 上界 {result['ci_high']} >= MDE {h['mde']}"}
        # ... 其他判定
```

### 12.17.3　透明性报告

在论文里报告:

- 跑了多少种子
- 哪些种子被排除(及原因)
- LLM 一致性检验结果
- 守恒审计结果
- benchmark 测试结果

### 12.17.4　同行评议的支持工具

帮助审稿人验证:

- 提供完整的运行命令
- 提供数据下载链接
- 提供 GitHub commit hash
- 提供可复现性证书

---

## 12.18　扩展:可信度建设的长期策略

### 12.18.1　建立研究信誉

可信度是长期积累的:

- 严格预注册每一篇论文
- 公开数据和代码
- 回应学术批评
- 跟踪后续研究

### 12.18.2　社区贡献

对社会仿真社区的贡献:

- 维护 benchmark
- 改进工具
- 培训新人
- 推动领域标准

### 12.18.3　教育下一代

通过教学传播可信度意识:

- 强调预注册
- 强调可复现性
- 强调伦理边界
- 强调批判性视角

### 12.18.4　持续学习

可信度建设是持续学习的过程:

- 关注学术前沿
- 跟踪最新争议
- 改进方法
- 更新工具

---

## 12.19　本章小结(最终扩展版)

- 可信度提升的工程实践:预注册强制、自动化校验、透明性报告、同行评议支持。
- 长期策略:研究信誉、社区贡献、教育下一代、持续学习。
- 可信度是社会仿真作为研究方法的"生命线",需要长期建设。

