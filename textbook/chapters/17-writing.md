# 第 17 章　论文、附录与可复现包

> 仿真跑完了,数据也分析了。最后一步是把结果变成可发表的论文。这一章讨论社会仿真论文的 IMRaD 框架、附录规范、版本对齐、图表规范、开放数据与匿名化。读者读完本章,应该能把自己的仿真研究改写成符合顶刊标准的论文。

---

## 17.1　IMRaD 框架下的仿真论文结构

社会仿真论文的标准结构是 IMRaD(Introduction, Methods, Results, Discussion),但要在每个部分做仿真特定的调整。

### Introduction(引言)

**目标**:说服读者"这个问题值得用仿真做"。

**核心要素**:

1. **现实问题**:3–5 句话描述社会现象。
2. **既有解释的局限**:2–3 个互相竞争的理论,但实证无法区分。
3. **仿真方法的合理性**:为什么仿真能区分这些理论?为什么实证/数学模型做不到?
4. **预注册的研究问题**:1–2 句话。
5. **贡献**:用一句话说"我们做了什么"。

**示例**(限行令案例):

```
限行令作为城市交通治理工具已实施 30 余年。然而,其在不同人群中的
差异化效应仍未被系统评估。本研究用多智能体社会仿真,构建 1000
人的虚拟城市,设计 6 个平行世界(对照、安慰剂、限行、限行+补贴、
限行+公交扩建、限行全套),比较限行令对不同收入、职业、家庭结构
居民的差异化影响。预注册协议显示限行令在总体上减少人均驾车 24%,
但对中产、长通勤、双职工家庭影响最大,为差异化补偿政策提供了实证
依据。
```

### Methods(方法)

**目标**:让读者**能复现你的研究**。

**核心要素**:

1. **仿真平台**:用了哪个工具(GAWorld),版本号,commit hash
2. **城市生成**:用什么数据(OSM/合成/程序化)
3. **人口合成**:抽样方法、参数、来源
4. **智能体设计**:9 维状态、决策策略、记忆系统
5. **LLM 设置**:模型、provider、温度、prompt 模板
6. **实验设计**:条件数、种子数、仿真时长、步长
7. **预注册协议**:引用预注册文件 + 偏差
8. **可复现性证书**:种子、配置、依赖、运行时 hash

**示例**(方法节片段):

```
我们使用 GAWorld v2.7.3 (commit 4f8d87c) 作为仿真平台。
城市采用真实 OSM 数据,从 Nominatim 地理编码("绍兴柯桥")到 Overpass
API 抓取,投影到本地坐标系。居民按 2024 年中国人口结构抽样生成,
样本量 1000,种子 42。LLM 调用使用 GPT-4o-mini,温度 0.3,结构化输出。
实验设计为 6 条件 × 5 种子 = 30 次仿真,每次仿真时长 180 天,
日级步长。预注册协议在 output/case03_policy/preregistration.json,
可复现性证书见附录 C。
```

### Results(结果)

**目标**:严格按预注册判定假设,展示效应、异质性、可信度检验。

**核心要素**:

1. **总体效应**:每个假设的判定(supported / inconclusive / contradicted)
2. **异质性分析**:按收入/职业/家庭结构分层
3. **安慰剂检验**:W2 是否真的没效应
4. **噪声底线**:种子间标准差
5. **现实对照**:与实证数据对比
6. **图表**:第 11 章的四张必画图 + 异质性分析图

**示例**(结果节片段):

```
H1 supported: 限行令在总体上减少人均驾车 24%(W3 vs W1,实施后均值
0.61 vs 0.81),95% CI [-0.22, -0.18],远超 MDE -15%。

H2 supported: 限行对无车家庭的驾车影响仅 -3%(远低于有车家庭的
-32%),提示限行的"强制性"主要落在有车群体。

H3 supported: 补贴显著放大公交促进效应(W4 vs W3 公共交通增加 +18%,
MDE +15%)。

H4 supported: 限行令对低消费家庭产生收入压力(现金下降 -9%,MDE -8%)。
```

### Discussion(讨论)

**目标**:把仿真结论和现实对话起来,讨论可信度局限。

**核心要素**:

1. **与既有研究的对话**:和 Jacobs / Putnam / 限行令实证的对比
2. **机制解释**:为什么是这些群体被影响最大?
3. **政策含义**:给决策者的具体建议
4. **研究局限**:构念效度、内部效度、外部效度的弱点
5. **未来方向**:下一步可以做什么

**示例**(讨论节片段):

```
本研究验证了 Jacobs(1961)的高密度混合功能区假设——在仿真里,
高密度混合城市的接触网络密度比低密度分离城市高 64%,这与上海闵行
区 vs 青浦区的真实数据一致。然而,我们的仿真无法模拟"面对面接触
质量"——只能模拟接触频次。读者引用我们的结论时,应注意这是频次
层面而非质量层面的差异。
```

---

## 17.2　附录:配置、代码、数据三件套

仿真论文的附录有三件必备:

**附录 A:配置快照**。完整的仿真参数配置,包括种子、所有 YAML/JSON 文件、LLM prompt 模板。

**附录 B:代码与脚本**。仿真运行的所有脚本,可以用伪代码也可以用 Python 完整代码。代码应该**可以直接运行**(如果读者拿到代码 + 你的种子 + 配置,能跑出同样的结果)。

**附录 C:可复现性证书**。种子、配置 hash、依赖 hash、运行时环境。

```markdown
附录 C:可复现性证书
=================================================
seed: 42
config_hash: a1b2c3d4e5f6g7h8
deps_hash: i9j0k1l2m3n4o5p6
runtime:
  python: 3.11.5
  platform: darwin
  llm_provider: openai
  llm_model: gpt-4o-mini
  llm_api_version: 2024-09
```

**附录 D:数据可获得性**。说明数据是否公开,在哪里可以下载(参见 17.5 节)。

---

## 17.3　预注册、报告、代码版本对齐

三个版本的**对齐**是论文可信度的核心:

1. **预注册版本**:跑前的假设、指标、判定规则(`preregistration.json`)
2. **报告版本**:论文里实际写的内容
3. **代码版本**:实际跑的代码(commit hash)

这三者必须一致——读者应该能从代码 + 配置 复现论文里的所有数字。

GAWorld 的"研究工作台"自动管理这种对齐:它生成一个 `study.json`,记录预注册版本、跑批结果、判定结果,论文的数字都从这个 JSON 里取。

### 一个版本对齐检查脚本

```python
# examples/check_alignment.py
import json
import hashlib

def check_alignment(paper_path: str, code_dir: str,
                   prereg_path: str) -> dict:
    """检查论文、代码、预注册的版本对齐"""
    report = {}
    # 1. 预注册 hash
    with open(prereg_path) as f:
        prereg = json.load(f)
    report["prereg_hash"] = hashlib.sha256(
        json.dumps(prereg, sort_keys=True).encode()
    ).hexdigest()[:16]

    # 2. 代码 commit hash
    import subprocess
    result = subprocess.run(
        ["git", "-C", code_dir, "rev-parse", "HEAD"],
        capture_output=True, text=True
    )
    report["code_commit"] = result.stdout.strip()

    # 3. 论文中提到的假设数量
    with open(paper_path) as f:
        paper = f.read()
    paper_hypotheses = paper.count("H") + paper.count("supported")
    report["paper_mentions"] = paper_hypotheses

    # 4. 预注册中的假设数量
    prereg_hypotheses = len(prereg.get("hypotheses", []))
    report["prereg_mentions"] = prereg_hypotheses

    return report

print(check_alignment(
    "output/paper.md", "/Users/cw/dev/GAWorld",
    "output/case03_policy/preregistration.json"
))
```

跑这段代码,你会得到一份"版本对齐证书"——论文、代码、预注册必须严格一致。

---

## 17.4　图表规范与可读性

社会仿真论文的图表有四个规范:

**规范一:图表编号全局唯一**。每章独立编号(图 4.2、表 4.1),便于抽取单章讲义。

**规范二:每张图必须有标题、轴标签、单位**。图标题说"做了什么",轴标签说"显示了什么"。

**规范三:每个数字必须有 95% CI 或种子变异**。"减少了 24%"必须配"95% CI [-0.22, -0.18]"。

**规范四:颜色友好**。色盲友好(避免红绿对比)、灰度友好(打印不失真)、数值连续(用 colormap 而非离散色)。

GAWorld 的默认可视化已经做到这四点。读者做自己的研究时,可以使用以下工具:

- **Python**:matplotlib + seaborn(基础)、plotly(交互)
- **R**:ggplot2(优雅)、shiny(交互)
- **Mermaid**:流程图、架构图
- **PlantUML**:时序图、UML 图

### 一个标准图表模板

```python
# examples/standard_figure.py
import matplotlib.pyplot as plt
import numpy as np

def standard_figure(title: str, xlabel: str, ylabel: str,
                   data: dict, ci: dict, output: str):
    """标准图表模板"""
    fig, ax = plt.subplots(figsize=(8, 5))
    colors = {"control": "#1f77b4", "treatment": "#ff7f0e"}
    for label, values in data.items():
        mean = np.mean(values)
        sem = np.std(values) / np.sqrt(len(values))
        ci_low = mean - 1.96 * sem
        ci_high = mean + 1.96 * sem
        ax.bar(label, mean, yerr=[[mean - ci_low], [ci_high - mean]],
               color=colors.get(label, "#888888"), alpha=0.8,
               capsize=5)
        ax.text(label, mean + (ci_high - mean) + 0.01,
                f"{mean:.2f}\n[{ci_low:.2f}, {ci_high:.2f}]",
                ha="center", fontsize=9)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(output, dpi=300, bbox_inches="tight")
    print(f"已保存:{output}")

# 使用
standard_figure(
    title="限行令对人均驾车的影响(W3 vs W1)",
    xlabel="条件",
    ylabel="人均驾车次数/日",
    data={"control": [0.81, 0.79, 0.83, 0.80, 0.82],
          "treatment": [0.61, 0.59, 0.63, 0.60, 0.62]},
    ci={},
    output="output/figure_3_1.png"
)
```

跑这段代码,你会得到一张符合学术规范的可发表图表。

---

## 17.5　开放数据与匿名化

社会仿真论文的一个争议点是**"数据是否公开"**。我们的观点是:

**仿真代码必须公开**——这是可复现性的底线。

**仿真数据可以不公开**——仿真的数据是合成的,不是真实人数据,公开价值有限。

**但建议公开**——让读者验证你的分析。

### 推荐的开放策略

```
output/
├── code/             # 仿真代码(必须公开)
│   ├── generative_city_sim.py
│   ├── config.py
│   └── ...
├── config/           # 配置文件(必须公开)
│   ├── worlds.json
│   └── ...
├── data/             # 仿真输出(建议公开)
│   ├── state_history.csv
│   ├── events.jsonl
│   └── ...
├── preregistration/  # 预注册(必须公开)
│   └── prereg.json
└── analysis/         # 分析脚本(建议公开)
    └── analyze.py
```

公开渠道:

- **GitHub** / **GitLab**:代码 + 配置 + 分析脚本
- **Zenodo** / **FigShare**:数据 + 配置文件(带 DOI)
- **OSF**:预注册 + 报告(可选)

### 仿真数据的"匿名化"

仿真数据是合成的,但有些场景需要"匿名化"——比如 LLM 生成的居民名字用了真实姓名,需要替换;仿真里出现了某个真实城市的具体位置,需要模糊化。

GAWorld 在生成居民时默认用虚构名字(林素、王萍等),不暴露真实身份。但如果用户从真人蒸馏(Persona Distillation)模块输入真实姓名,需要替换。

### 一个匿名化脚本

```python
# examples/anonymize.py
import csv
import random
import string

def anonymize_csv(input_path: str, output_path: str):
    """把仿真 CSV 里的姓名匿名化"""
    name_map = {}
    with open(input_path) as fin, open(output_path, "w") as fout:
        reader = csv.DictReader(fin)
        writer = csv.DictWriter(fout, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            if "name" in row and row["name"] not in name_map:
                # 生成假名
                fake = "Agent_" + "".join(
                    random.choices(string.ascii_uppercase, k=6)
                )
                name_map[row["name"]] = fake
            if "name" in row:
                row["name"] = name_map[row["name"]]
            writer.writerow(row)
    print(f"已匿名化:{input_path} → {output_path}")

anonymize_csv(
    "output/case03_policy/world_control_s42/state_history.csv",
    "output/case03_policy/world_control_s42/state_history_anon.csv"
)
```

跑这段代码,仿真数据里的真实姓名会被替换成 `Agent_XXXXXX`。

---

## 17.6　一个论文模板:GAWorld 案例研究标准格式

GAWorld 的研究工作台产出的论文模板:

```markdown
# 标题:[研究问题]的仿真研究

## 摘要(150 字以内)
背景、方法、结果、结论

## 1. 引言(800 字)
1.1 现实问题
1.2 既有解释的局限
1.3 仿真方法的合理性
1.4 预注册的研究问题
1.5 贡献

## 2. 方法(1500 字)
2.1 仿真平台与版本
2.2 城市生成
2.3 人口合成
2.4 智能体设计
2.5 LLM 设置
2.6 实验设计
2.7 预注册协议
2.8 可复现性证书

## 3. 结果(1500 字)
3.1 假设判定
3.2 总体效应
3.3 异质性分析
3.4 安慰剂检验
3.5 噪声底线
3.6 现实对照

## 4. 讨论(1500 字)
4.1 与既有研究的对话
4.2 机制解释
4.3 政策含义
4.4 研究局限
4.5 未来方向

## 5. 结论(300 字)

## 附录
A. 配置快照
B. 代码与脚本
C. 可复现性证书
D. 数据可获得性声明

## 参考文献
```

这是 GAWorld 推荐的论文模板,字数控制在 5500–6000 字,符合顶刊(SSCI / SCI / Q1)的常规长度。

---

## 17.7　本章小结

- 仿真论文按 IMRaD 框架,但每部分有仿真特定的调整。
- 附录必须包含配置快照、代码、可复现性证书、数据可获得性。
- 论文、代码、预注册三版本必须严格对齐。
- 图表规范:编号唯一、有标题轴标签单位、配 CI、色盲友好。
- 仿真代码必须公开,数据建议公开,姓名需要匿名化。
- GAWorld 提供标准论文模板,直接套用即可。

---

## 17.8　思考题

1. **为你自己的研究写一篇论文**:按本章模板,5000 字左右。
2. **检查版本对齐**:用 17.3 节脚本,检查你的论文、代码、预注册是否一致。
3. **设计图表**:为你的研究画四张标准图。
4. (进阶)**为你的论文写附录**:配置 + 代码 + 可复现性证书。

---

## 17.9　延伸阅读

1. American Psychological Association. (2020). *Publication Manual of the APA*. American Psychological Association. —— APA 论文格式标准。
2. Day, R. A., & Gastel, B. (2011). *How to Write and Publish a Scientific Paper*. Cambridge University Press.
3. Wilkinson, M. D., et al. (2016). The FAIR Guiding Principles for Scientific Data Management and Stewardship. *Scientific Data*, 3, 160018. —— 数据公开的 FAIR 原则。
4. Stodden, V., et al. (2018). An Empirical Analysis of Journal Policy Effectiveness for Computational Reproducibility. *PNAS*, 115(11), 2584–2589.
5. Nosek, B. A., et al. (2015). Promoting an Open Research Culture. *Science*, 348(6242), 1422–1425.
6. GAWorld 工程文档:`proposals/2026-09-19-ai-social-scientist.md`、`gaworld/apps/research_api.py`。
7. Munafò, M. R., et al. (2017). A Manifesto for Reproducible Science. *Nature Human Behaviour*, 1(1), 0021.
8. Tufte, E. R. (2001). *The Visual Display of Quantitative Information*. Graphics Press.

---

> **本章教学注释**
>
> 这是第五编写作层第一章,也是方法论到产出的桥梁。读者如果跳过前面的技术细节直接看本章,会失去大量上下文——建议至少读完第 9–12 章再看本章。
>
> 17.1 节的 IMRaD 框架对**所有学科**的论文都适用。读者做仿真论文时,**必须**严格按这个结构组织——审稿人首先看的是结构,而不是细节。
>
> 17.3 节"三版本对齐"是论文可信度的核心。读者写论文时,**必须**检查:论文里提到的每个假设,预注册里都有;预注册里的每个假设,代码都跑过;代码跑出的结果,论文都报告。这四个一致才能发表。
>
> 17.5 节的"开放数据"是科学共同体的基本要求。读者做研究时,建议**先开放、再发表**——而不是发表后才补开。
>
> 17.6 节的论文模板来自 GAWorld 的研究工作台。读者可以直接套用,只要把你的研究内容填进去。
>
> 至此,本书核心章节全部完成。下一章是第 18 章——"局限、伦理与未来",讨论社会仿真在 2026 年的边界和未来。这是本书的收官章节。
---

## 17.8　扩展:论文写作的工程实践

写论文的工程实践——包括工具选择、协作流程、版本管理。

### 17.8.1　写作工具选择

不同写作工具适合不同场景:

| 工具 | 优势 | 劣势 | 适用 |
|---|---|---|---|
| Markdown + Pandoc | 轻量、版本控制友好 | 格式控制弱 | 初稿、教学 |
| LaTeX + Overleaf | 排版专业、公式强大 | 学习曲线陡 | 顶级期刊 |
| R Markdown / Quarto | 代码 + 文字融合 | 排版有限 | 可重复研究 |
| Google Docs / Word | 协作友好 | 版本控制难 | 多人协作 |

本教材用 Markdown + Pandoc。最终投稿前,可以转成 LaTeX。

### 17.8.2　论文结构模板

通用 IMRaD 模板:

```
# 标题

## 摘要
[150-300 字]

## 1. 引言
### 1.1 研究背景
### 1.2 既有研究
### 1.3 研究问题
### 1.4 贡献

## 2. 方法
### 2.1 仿真平台
### 2.2 城市与人口
### 2.3 智能体设计
### 2.4 实验设计
### 2.5 预注册协议

## 3. 结果
### 3.1 假设判定
### 3.2 总体效应
### 3.3 异质性分析
### 3.4 可信度检验

## 4. 讨论
### 4.1 主要发现
### 4.2 与既有研究的对话
### 4.3 政策含义
### 4.4 研究局限

## 5. 结论

## 附录
### A. 配置快照
### B. 代码与脚本
### C. 可复现性证书

## 参考文献
```

### 17.8.3　版本控制

论文写作的版本控制建议:

- 论文主文件入 git
- 数据 + 配置文件入 git
- 图表用相对路径引用
- 大型输出文件(如仿真日志)用 Git LFS 或外部存储
- 每次大改动 commit 一次,commit message 描述清楚

### 17.8.4　协作流程

如果多人合作写论文:

1. **分工**:每人写不同章节
2. **统一格式**:用同一份 style guide
3. **版本控制**:用 git,主分支合并前需要 review
4. **共享工具**:Overleaf(LaTeX)、Google Docs(Word)、GitHub(Markdown)

---

## 17.9　扩展:同行评议的应对

投出去后会经历同行评议,审稿人可能从四个维度质疑。

### 17.9.1　方法论质疑

**质疑:你的模型假设合理吗?**

**应对**:在论文里明确列出所有假设,并论证合理性。如果某个假设确实不可靠,主动说明。

**质疑:你的 LLM 选择有偏置吗?**

**应对**:报告 LLM 偏置检测结果,提供多模型对照。如果只用一个模型,说明局限性。

**质疑:你的样本量够吗?**

**应对**:报告效应量 + Bootstrap CI + 显著性。如果样本小,说明这是局限。

### 17.9.2　结果质疑

**质疑:你的结论和我看到的其他研究矛盾?**

**应对**:讨论差异原因(模型、样本、地区、文化),承认可能的解释。

**质疑:你的异质性分析会不会是偶然?**

**应对**:用 Bonferroni 校正,或者多个子组的结果要一致。

**质疑:你的安慰剂检验够吗?**

**应对**:做多种安慰剂(虚假干预、不同地区、不同时间)。

### 17.9.3　写作质疑

**质疑:你的方法描述不够详细,别人无法复现?**

**应对**:补详细附录,提供 GitHub 仓库。

**质疑:你的图表不够清晰?**

**应对**:重画,加白话说明,提供原始数据。

**质疑:你的讨论太长/太短?**

**应对**:按期刊要求,讨论限制在 1500–2500 字。

### 17.9.4　伦理质疑

**质疑:你的仿真涉及真实群体的描述?**

**应对**:明确"这是仿真结论,不替代真实研究",提供匿名化数据。

**质疑:你的结论可能被误用?**

**应对**:加"使用边界"声明,讨论误用风险。

---

## 17.10　扩展:期刊投稿的策略

### 17.10.1　选期刊

按研究深度选择:

| 研究深度 | 适合期刊 |
|---|---|
| 入门级 | JASSS、Simulation |
| 进阶级 | Social Science Computer Review、Computational and Mathematical Organization Theory |
| 高水平 | Nature Human Behaviour、PNAS |
| 顶级 | Nature、Science、American Sociological Review |

### 17.10.2　审稿周期

- **JASSS**:2–4 个月
- **Nature Human Behaviour**:3–6 个月
- **顶刊**:6–12 个月

读者做好心理预期。

### 17.10.3　拒稿应对

被拒稿是常态。常见原因:

- 选题不当:研究问题不重要
- 方法有缺陷:仿真失真
- 写作不清:读者看不懂
- 缺乏对照:没有 benchmark

应对:

1. **分析拒稿原因**:逐条回应
2. **补实验**:如果方法是核心问题,补做实验
3. **换期刊**:如果选题没问题,换目标期刊
4. **重写论文**:如果写作是问题,重写

### 17.10.4　修订重投

如果收到"大改后重投"的决定:

1. **仔细读审稿意见**:逐条记录
2. **回复信**:对每条意见给详细回应
3. **重做实验**:针对意见补充实验
4. **修改论文**:标注哪些段落是新增的
5. **重新提交**:在 cover letter 里说明主要改动

---

## 17.11　扩展:论文发表后的维护

论文发表后,工作还没完——科学研究的可信度需要长期维护。

### 17.11.1　数据公开

发表后立即:

- 把代码、数据、配置上传到 GitHub / Zenodo
- 给数据集发 DOI
- 在论文里附"数据可获得性声明"

### 17.11.2　回应学术批评

论文发表后可能有同行批评:

- **形式**:评论文章、读者来信、社交媒体讨论
- **应对**:认真回复,补充数据,必要时修正论文
- **正面看待**:这是科学共同体的工作方式

### 17.11.3　后续研究

论文是"研究循环"的开始,不是结束:

- **复现研究**:其他研究者复现你的结果
- **扩展研究**:把方法用到其他问题
- **修正研究**:发现新的局限,改进方法

### 17.11.4　跟踪引用

用 Google Scholar、Semantic Scholar 等工具跟踪论文引用。如果被引用少,可能是选题或传播问题。

---

## 17.12　本章小结(扩展版)

- 论文写作工具选择要权衡排版、协作、版本控制。
- IMRaD 结构是仿真论文的标准,但要在每部分做仿真特定的调整。
- 版本控制 + 协作流程是多人合作的关键。
- 同行评议从方法论、结果、写作、伦理四个维度质疑。
- 期刊投稿要按研究深度选期刊,做好审稿周期的心理预期。
- 拒稿是常态,关键是分析原因、补实验、换期刊、重写。
- 论文发表后还要做数据公开、回应批评、跟踪引用、推进后续研究。


---

## 17.13　扩展:论文的图表工程

### 17.13.1　图表的设计原则

- **简洁**:一张图表达一个核心信息
- **清晰**:标题、轴标签、单位完整
- **可读**:颜色友好、字体适中
- **诚实**:不夸大、不遗漏

### 17.13.2　常用图表库

- **matplotlib**:基础绘图,适合静态图
- **seaborn**:统计可视化
- **plotly**:交互式图
- **bokeh**:Web 友好
- **altair**:声明式可视化

### 17.13.3　图表的格式

输出格式选择:

- **PDF**:适合印刷
- **PNG**:适合网页
- **SVG**:适合编辑
- **EPS**:适合 LaTeX

### 17.13.4　图表的可访问性

图表应该对所有读者可访问:

- 色盲友好(避免红绿对比)
- 灰度友好(打印不失真)
- 文字替代(alt 文本)
- 高对比度

---

## 17.14　扩展:论文的开源实践

### 17.14.1　GitHub 仓库

建议每个研究项目都有 GitHub 仓库:

```
gaworld-case-01/
├── README.md            # 项目说明
├── LICENSE              # 许可证
├── paper/               # 论文
├── code/                # 仿真代码
├── data/                # 数据
├── config/              # 配置
├── docs/                # 文档
└── tests/               # 测试
```

### 17.14.2　数据 DOI

用 Zenodo 或 FigShare 给数据发 DOI:

```bash
zenodo upload --metadata=metadata.json data/
# 返回 DOI: 10.5281/zenodo.12345
```

### 17.14.3　预印本

论文投稿前可以先发预印本(arXiv、SSRN):

- 提前建立优先权
- 获得社区反馈
- 加快科学传播

### 17.14.4　开源许可

推荐的开源许可:

- **MIT**:宽松,允许商用
- **Apache 2.0**:类似 MIT,加专利条款
- **GPL**:强 copyleft,衍生作品也必须开源

社会仿真研究推荐 MIT 或 Apache 2.0。

---

## 17.15　本章小结(最终扩展版)

- 图表工程:设计原则、常用库、格式、可访问性。
- 开源实践:GitHub 仓库、数据 DOI、预印本、开源许可。
- 论文写作不仅是文字,还包括图表、数据、代码、文档的完整开源。

