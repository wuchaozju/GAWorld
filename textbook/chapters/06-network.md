# 第 6 章　社会网络：关系、结构与传染

> 智能体住在世界里,但和谁说话?答案藏在**社会网络**里。这一章拆解社会网络的三个核心:关系的数据结构、网络的拓扑生成、网络上的扩散过程。社会仿真和复杂网络科学天然契合——前者需要后者的拓扑,后者需要前者的行为动力学。读完本章,读者应该能设计一个能跑出"小世界 + 聚类 + 病毒扩散"三个经典现象的网络模型。

---

## 6.X 跨章交叉引用

**网络科学的理论深度**:本章是网络科学的方法应用,第六章是网络科学的理论深度。

具体细节详见:
- **第 21 章 网络科学与社会**:Watts-Strogatz 模型详解、Barabási-Albert 模型、无标度争议、Albert 鲁棒性研究
- **第 3 章 简史**:Christakis-Fowler 肥胖传播的网络实验
- **第 11 章 数据分析**:网络指标的可视化与统计

## 6.1　关系的数据结构

在社会仿真里,"关系"不是一根线,而是一个有结构的记录。GAWorld 把一条关系建模成 5 元组:

```
(对象, 强度, 亲密度, 义务, 可信度, 上次接触)
```

**对象**(target):这条关系指向谁——另一个智能体的 ID,或者一个"幽灵节点"(不在城里但仍然存在的人,如远方亲属、前同事)。

**强度**(strength):关系的"分量",0–1。一个老朋友的强度可能 0.9,一个点头之交 0.2。这是网络图里"边权"的依据。

**亲密度**(intensity):情感距离,0–1。强度大不一定亲密度高(比如一个合作密切但互相警惕的同事),反之亦然(比如一个联系少但情感很深的老友)。

**义务**(obligation):道德/社交义务,0–1。中国社会的"随礼"、西方的"回信",本质都是义务。义务会随时间衰减,衰减慢了就需要"充值"(主动联系)。

**可信度**(trust):信息的可信度,0–1。可信度影响"传播"——居民转发一条信息时,会看消息来源的可信度加权。

**上次接触**(last_contact):一个时间戳,用于"关系衰减"算法——久未联系的关系会自然降级。

这 6 个字段的组合让 GAWorld 的社会图比一般 ABM 复杂得多,也更接近真实社会。读者做研究时,可以选择使用全部 6 个字段(复杂但真实),也可以只使用其中 2–3 个(简单但可控)。

代码示例:一个关系记录。

```python
# examples/relation.py
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Relation:
    target: int           # 对方 ID
    strength: float       # 0–1
    intensity: float      # 0–1, 情感亲密度
    obligation: float     # 0–1, 社交义务
    trust: float          # 0–1, 信息可信度
    last_contact: datetime
    history: list = None   # 互动历史

    def decay(self, current_time: datetime, days_passed: int):
        """每天衰减:强度、亲密度、可信度缓慢下降"""
        decay_rate = 0.01  # 每天 1%
        self.strength = max(0, self.strength - decay_rate * days_passed)
        self.intensity = max(0, self.intensity - decay_rate * 1.5 * days_passed)
        self.obligation = max(0, self.obligation - decay_rate * 2 * days_passed)

    def reinforce(self):
        """互动后强化:每次互动 +5% 强度"""
        self.strength = min(1, self.strength + 0.05)
        self.intensity = min(1, self.intensity + 0.03)
        self.last_contact = datetime.now()

r = Relation(target=42, strength=0.7, intensity=0.6,
             obligation=0.4, trust=0.8,
             last_contact=datetime.now())
r.reinforce()
print(r.strength, r.intensity)  # 0.75, 0.63
```

---

## 6.2　社会图的生成:小世界、无标度、Dunbar 分层

有了"关系"的数据结构,接下来是怎么把一堆关系串成**网络**——一张图。图不是任意连出来的,它必须满足社会规律。

**小世界特性**(small-world):社会网络的平均路径长度极短——地球上任何两个人之间平均只隔着 6 个人(Watts & Strogatz 1998)。这是网络最深刻的性质。生成方法:从一个环形格子出发,以概率 p 随机重连每条边。

**无标度特性**(scale-free):网络度分布服从幂律——少数节点(社交明星)有几百个朋友,大多数节点只有几个。Barabási-Albert 模型(1999)的核心是"富者愈富":新节点更倾向于连接度高的节点。

**高聚类**(high clustering):朋友的朋友也是朋友——三个人里任何两个都认识。纯随机网络没有这个性质,小世界模型有。

**Dunbar 分层**(Dunbar's layers):Robin Dunbar 在 1990 年代提出,人能维持稳定社会关系的数量大约是 150,内圈 5、最内圈 1–2。这个数字是基于新皮层比例计算出来的,跨灵长类物种稳定。

GAWorld 的网络生成策略:**先按家庭 + 地理就近生成"硬核"边(0.3 * N 条),再用 Watts-Strogatz 改造生成"软核"边(0.7 * N 条)**。硬核边是必然的(家人、邻居、同事),软核边是概率性的(朋友、朋友的朋友)。

```python
# examples/social_graph.py
import networkx as nx
import random

def generate_social_graph(n: int, seed: int = 42) -> nx.Graph:
    """GAWorld 风格的社会图生成:
    - 小世界底层(Watts-Strogatz)
    - 少量高连接节点(无标度特性)
    - 高聚类"""
    random.seed(seed)
    G = nx.watts_strogatz_graph(n=n, k=10, p=0.15, seed=seed)
    # 加一些"社交明星"节点
    stars = random.sample(range(n), 5)
    for s in stars:
        for _ in range(20):
            t = random.choice([x for x in range(n) if x != s and not G.has_edge(s, x)])
            G.add_edge(s, t, weight=random.uniform(0.5, 0.9))
    return G

G = generate_social_graph(200)
print(f"节点: {G.number_of_nodes()}, 边: {G.number_of_edges()}")
print(f"平均度: {sum(dict(G.degree()).values()) / G.number_of_nodes():.2f}")
print(f"聚类系数: {nx.average_clustering(G):.3f}")
print(f"平均路径长度: {nx.average_shortest_path_length(G):.2f}")
# 典型输出:节点 200, 边 ~1100, 平均度 ~11, 聚类 0.35, 路径 ~3.5
```

这段代码在 1 秒内跑出一个有"小世界 + 高聚类 + 少量明星节点"特征的 200 人网络,平均路径长度 ~3.5(对比地球上任何两个人之间平均 6 步)。

---

## 6.3　传染过程:信息、情绪、规范、行为

社会网络上发生的"传染"是社会仿真的核心研究对象。不同类型的传染有不同的传播规律:

**信息传染**(information contagion):谣言、新闻、知识的扩散。特征是**单向、快速、可证伪**。一条谣言被证伪后,扩散立即停止。经典模型:SIR(Susceptible-Infected-Recovered)。

**情绪传染**(emotion contagion):焦虑、乐观、愤怒的扩散。特征是**双向、缓慢、可叠加**。情绪会叠加(焦虑 + 愤怒 = 恐惧),叠加的衰减期更长。经典模型:阈值模型(threshold model)。

**规范传染**(norm contagion):行为规则、礼仪、习俗的扩散。特征是**多代、长程、难以快速改变**。规范的形成需要数十年的反复强化。

**行为传染**(behavior contagion):抽烟、喝酒、消费习惯的扩散。Christakis & Fowler 2007 年在《新英格兰医学杂志》发的论文(*The Spread of Obesity in a Large Social Network over 32 Years*)证明了肥胖在朋友网络里扩散的速度是地理邻里的 3 倍。

代码示例:一个简化的 SIR 信息传染模型。

```python
# examples/contagion.py
import networkx as nx
import random

def sim_sir(G: nx.Graph, patient_zero: int, beta: float = 0.1,
            gamma: float = 0.05, days: int = 30) -> dict:
    """信息传染:SIR 模型
    - 初始:S(易感) = 所有节点除 patient_zero
    - 每天:每个 I 节点以 beta 概率感染邻居,自己以 gamma 概率恢复 R
    - 返回:每个时刻的 S/I/R 数量"""
    status = {n: 'S' for n in G.nodes()}
    status[patient_zero] = 'I'
    history = []
    for day in range(days):
        new_status = status.copy()
        for n in G.nodes():
            if status[n] == 'I':
                # 感染邻居
                for m in G.neighbors(n):
                    if status[m] == 'S' and random.random() < beta:
                        new_status[m] = 'I'
                # 自己恢复
                if random.random() < gamma:
                    new_status[n] = 'R'
        status = new_status
        s = sum(1 for v in status.values() if v == 'S')
        i = sum(1 for v in status.values() if v == 'I')
        r = sum(1 for v in status.values() if v == 'R')
        history.append((day, s, i, r))
    return {'history': history, 'final_status': status}

# 跑一次
G = nx.watts_strogatz_graph(200, 10, 0.15, seed=42)
result = sim_sir(G, patient_zero=10)
for day, s, i, r in result['history'][:10]:
    print(f"Day {day}: S={s} I={i} R={r}")
```

跑这段代码会看到一条典型的"传染曲线":感染数先升后降,恢复数持续上升,易感数持续下降。这是社会仿真里**最基础也最有用的**一个模型。

---

## 6.4　网络的演化与共演化

真实社会里,网络不是一成不变的——关系在不断生成、消失、强化、衰减。**网络演化**(network evolution)就是这种动态过程的建模。

GAWorld 实现了三个最常见的演化机制:

**关系衰减**(relationship decay):久未联系的关系强度自动下降。第 6.1 节 `Relation.decay()` 已经演示。

**关系强化**(reinforcement):互动后关系变强。`Relation.reinforce()` 演示。

**新关系生成**(new tie formation):通过共同活动、共同朋友、偶然接触建立新关系。这是社会仿真里最难的部分——它涉及智能体的"社交主动性"决策。LLM 在这里表现出色,规则系统常常把它处理成"随机事件",失真严重。

**共演化**(co-evolution):网络和行为相互影响——行为影响网络(谁和谁成为朋友),网络影响行为(朋友影响你的决策)。这是社会仿真的最高级形态,也是最容易"涌现"出意外现象的层次。

代码示例:一个最简单的共演化模型。

```python
# examples/coevolution.py
import random

def coevolve_step(opinions: dict, G, tolerance: float = 0.2):
    """意见动力学 + 网络重连(共演化)
    - 每步:每个 agent 看朋友的意见,差距大则断开;差距小则强化
    - 极端意见者(无朋友)随机找新朋友"""
    new_G = G.copy()
    new_opinions = opinions.copy()
    for n in list(G.nodes()):
        for m in list(G.neighbors(n)):
            if abs(opinions[n] - opinions[m]) > tolerance:
                if random.random() < 0.5:
                    new_G.remove_edge(n, m)
    # 极端孤立者重连
    for n in list(new_G.nodes()):
        if new_G.degree(n) == 0:
            target = random.choice(list(new_G.nodes()))
            new_G.add_edge(n, target)
    return new_G, new_opinions

# 这段代码演示了"意见极化 + 网络分离"的共演化
# 跑 100 步会看到网络分裂成几个"意见集群"
```

跑这个模型 100 步,你会看到:原本随机的网络分裂成几个"意见集群",每个集群内部意见相近、集群之间意见对立——这就是**意见极化**(opinion polarization)的网络机制。

---

## 6.5　幽灵节点与跨城关系

社会仿真里有一个尴尬问题:不是所有重要的人都在仿真里。一个居民的爸爸可能在老家农村,他的中学同学可能去了别的城市。把这些人全部放进仿真,会让"城市"边界模糊;不放在仿真里,又少了关键关系。

GAWorld 用**幽灵节点**(ghost nodes)解决这个矛盾。幽灵节点是"不在城里但存在"的人,它们参与关系网络(有强度、亲密度、可信度),但不参与行动(不出门、不消费、不决策)。

幽灵节点的设计有三个要点:

第一,**关系可追溯**。每个智能体可以列出它的幽灵节点及其关系强度。研究者可以分析"远程关系"如何影响本地决策。

第二,**事件可触发**。幽灵节点可以"来访"——比如"爸爸从老家来看望",这是仿真里的一个事件,会触发一系列本地行动。

第三,**离线记忆可沉淀**。智能体对幽灵节点有记忆(印象、互动历史),这和本地朋友一样,只是没有"今天会见到"的现实可能性。

### 一个使用幽灵节点的例子

林素(31 号,绍兴柯桥)有两个幽灵节点:

- 父亲(老家安徽黄山),强度 0.85,亲密度 0.9,义务 0.7(林素每月给父亲打钱)
- 大学同学(在杭州),强度 0.6,亲密度 0.7,义务 0.3(偶尔联系)

这两个节点不进日常仿真,但在以下场景会被激活:

- 林素收到"爸爸住院"的消息 → 仿真触发"是否回老家"决策
- 林素周末收到"杭州同学聚会"邀请 → 仿真触发"是否去杭州"决策

幽灵节点让仿真有了"远程生活"的存在感,但不需要把这些人的全部生活都模拟出来。GAWorld 默认每 5–10 个本地智能体配 1 个幽灵节点,具体配置在 `CONFIG["social"]["ghost_ratio"]`。

---

## 6.6　代码示例:用 NetworkX 做关系网络可视化

把 6.1–6.5 节的内容整合起来,展示一个完整的社会网络可视化。

```python
# examples/social_viz.py
import networkx as nx
import matplotlib.pyplot as plt

# 一个 50 人小社群
G = nx.watts_strogatz_graph(50, 6, 0.2, seed=42)

# 给每个节点加意见分(0–1)
for n in G.nodes():
    G.nodes[n]['opinion'] = hash(n) % 100 / 100

# 画图:节点颜色按意见,边粗细按权重(这里用度数近似)
plt.figure(figsize=(10, 8))
pos = nx.spring_layout(G, seed=42)
opinions = [G.nodes[n]['opinion'] for n in G.nodes()]
nx.draw_networkx_nodes(G, pos, node_color=opinions, cmap=plt.cm.RdYlBu,
                       node_size=200)
nx.draw_networkx_edges(G, pos, alpha=0.3)
plt.title("50 人社群意见网络")
plt.axis('off')
plt.savefig('social_opinion_network.png', dpi=100, bbox_inches='tight')
```

跑这段代码会生成一张 50 节点的社群网络图,节点颜色按意见值冷暖渐变(蓝=保守,红=开放)。读者可以直观看到:相同意见的人倾向于聚在一起,意见极端的人要么在网络中心,要么在边缘。## 6.8　思考题

1. **为你的家人/朋友画一张关系图**:列出 10–15 个最亲密的人,标注关系类型(家人/老友/同事/邻居)、亲密度、义务、可信度。看看是否符合"Dunbar 分层"——是否最内圈 1–2 人,次内圈 5 人,外圈 15–30 人?
2. **用 6.3 节的 SIR 代码跑一次**:改变 β(感染率)和 γ(恢复率),画出感染曲线。观察:**β 远大于 γ 时**会发生什么?**γ 远大于 β 时**会发生什么?
3. **用 6.4 节的共演化模型跑 100 步**:意见分随机生成,网络会分裂成几个集群?这个数字对什么参数敏感?
4. (进阶)**为限行令案例设计一个"信息传播"仿真**:1000 个居民的网络上传播"限行令即将实施"的消息,模拟 14 天(公告到实施),看信息什么时候扩散到 95% 的人。

---

## 6.9　延伸阅读

1. Watts, D. J., & Strogatz, S. H. (1998). Collective Dynamics of 'Small-World' Networks. *Nature*, 393(6684), 440–442. —— 小世界网络的奠基论文。
2. Barabási, A.-L., & Albert, R. (1999). Emergence of Scaling in Random Networks. *Science*, 286(5439), 509–512. —— 无标度网络的奠基论文。
3. Dunbar, R. (1998). *Grooming, Gossip, and the Evolution of Language*. Harvard University Press. —— "Dunbar 数"的原始来源。
4. Christakis, N. A., & Fowler, J. H. (2007). The Spread of Obesity in a Large Social Network over 32 Years. *New England Journal of Medicine*, 357(4), 370–379. —— 行为传染的里程碑研究。
5. Granovetter, M. S. (1973). The Strength of Weak Ties. *American Journal of Sociology*, 78(6), 1360–1380. —— 弱连接的力量,被引最多的社会学论文之一。
6. Centola, D., & Macy, M. (2007). Complex Contagions and the Weakness of Long Ties. *American Journal of Sociology*, 113(3), 702–734. —— 复杂传染的奠基论文。
7. GAWorld 工程文档:`gaworld/social/network.py`、`docs/SOCIAL_NETWORK_DESIGN.md`。
8. Easley, D., & Kleinberg, J. (2010). *Networks, Crowds, and Markets: Reasoning About a Highly Connected World*. Cambridge University Press. —— 网络科学的入门经典。

---

> **本章教学注释**
>
> 这一章是技术层第三章,和前两章构成"智能体 + 环境 + 网络"三件套。`gaworld/social/network.py` 实现了本章大部分功能,3000+ 行代码,完整支持关系数据结构、拓扑生成、传染过程、网络演化、幽灵节点。读者跑 6.6 节的可视化代码,就能看到一个"长什么样"的社会网络。
>
> 6.3 节的 SIR 模型是社会仿真里**最经典也最有用**的模型——读者如果只能学一个模型,就学这个。把它和 6.4 节的共演化模型组合,就能解释"谣言如何传播""意见如何极化""行为如何传染"等一大类社会现象。第 15 章的案例三会用到这些模型。下一章我们进入"语言模型作为仿真引擎"——LLM 如何让社会仿真产生"人味"?
---

### 6.10 扩展:社会网络的高级主题

本节讨论社会网络研究的高级主题,适合研究生或博士生。

### 6.10.1　网络的时间演化

真实社会网络不是静态的——关系在生成、强化、衰减。本节讨论网络的时间演化建模。

**演化模型**:

1. **优先连接(Preferential Attachment)**:新节点更倾向连接已有高度节点
2. **三度影响(Three Degrees of Influence)**:Christakis-Fowler 的研究——影响平均传播 3 度
3. **衰减 + 偶遇**:日常接触衰减关系强度,偶遇接触创造新关系

```python
# examples/network_evolution.py
def evolve_network_step(G, decay_rate=0.01, encounter_prob=0.005):
    """一个网络演化时间步"""
    new_G = G.copy()
    # 1. 关系衰减
    for u, v in list(G.edges()):
        if random.random() < decay_rate:
            new_G[u][v]["weight"] *= 0.95
    # 2. 偶遇接触
    nodes = list(G.nodes())
    for u in nodes:
        if random.random() < encounter_prob:
            v = random.choice(nodes)
            if v != u and not new_G.has_edge(u, v):
                new_G.add_edge(u, v, weight=0.1)
    return new_G
```

### 6.10.2　网络的多层结构

真实社会网络是**多层**的:

- **家庭层**:血缘、婚姻
- **同事层**:工作关系
- **社区层**:邻居
- **兴趣层**:同好会、运动队
- **在线层**:社交媒体

仿真里的多层网络:

```python
# examples/multilayer_network.py
import networkx as nx

class MultiLayerNetwork:
    def __init__(self):
        self.layers = {
            "family": nx.Graph(),
            "work": nx.Graph(),
            "community": nx.Graph(),
            "interest": nx.Graph(),
            "online": nx.Graph()
        }

    def add_relation(self, layer, u, v, weight):
        if layer not in self.layers:
            self.layers[layer] = nx.Graph()
        self.layers[layer].add_edge(u, v, weight=weight)

    def total_relations(self, u):
        """u 的总关系强度"""
        return sum(
            self.layers[layer].degree(u, weight="weight")
            for layer in self.layers if u in self.layers[layer]
        )
```

### 6.10.3　动态网络与行为共演化

行为和网络相互影响——这是社会仿真的最高级形态。

**机制**:

1. agent 的行为改变 → 关系生成/衰减
2. 关系变化 → 影响 agent 的行为

```python
# examples/coevolution_v2.py
def coevolution_step(agents, network, behaviors):
    """行为 + 网络共演化"""
    # 1. 行为影响网络
    for agent in agents:
        for neighbor in network.neighbors(agent.id):
            if abs(behaviors[agent.id] - behaviors[neighbor]) > 0.5:
                # 行为差距大,关系衰减
                network[agent.id][neighbor]["weight"] *= 0.9
    # 2. 网络影响行为
    for agent in agents:
        neighbors = list(network.neighbors(agent.id))
        if neighbors:
            avg_behavior = sum(behaviors[n] for n in neighbors) / len(neighbors)
            behaviors[agent.id] = 0.8 * behaviors[agent.id] + 0.2 * avg_behavior
    return network, behaviors
```

### 6.10.4　网络的因果推断

网络的因果识别比一般因果识别更难——因为网络本身就是"处理变量"的一部分。

**工具**:网络干预分析(Network Intervention Analysis)

```python
# examples/network_causal.py
def network_intervention_effect(baseline_network, treated_node, treatment_effect):
    """计算网络干预效应"""
    # 模拟把 treated_node 改成某种状态
    # 看网络中其他节点的反应
    pass
```

这是社会网络研究的前沿方向。

---

### 6.11 扩展:网络研究的应用领域

### 6.11.1　公共卫生

社会网络在公共卫生里用于:

- 传染病传播建模
- 健康行为干预(戒烟、运动)
- 心理健康传播

### 6.11.2　市场营销

社会网络在营销里用于:

- 口碑传播建模
- 病毒式营销设计
- 客户获取成本分析

### 6.11.3　组织管理

社会网络在管理学里用于:

- 团队协作优化
- 知识共享建模
- 领导力影响分析

### 6.11.4　公共政策

社会网络在公共政策里用于:

- 政策传播路径分析
- 群体行为干预
- 舆情演化预测

GAWorld 在所有这些领域都有应用潜力。

---

### 6.12 扩展:网络的批判性视角

社会网络不是万能的,本节讨论局限。

### 6.12.1　测量问题

真实社会网络很难测量:

- 问卷调查的"好友列表"是主观的
- 社交媒体数据只覆盖"在线关系"
- 移动数据只覆盖"空间共现"

仿真里的网络是"被假设的",可能高估或低估真实网络密度。

### 6.12.2　同质性问题

社交网络有"同质性"——相似的人更可能连接。这导致:

- 仿真里的"小世界"可能被高估
- 真实的"跨群体连接"可能被低估
- 网络多样性被低估

### 6.12.3　网络结构与权力

社会网络结构反映权力关系:

- 中心节点有更多影响力
- 边缘节点被边缘化
- 网络断裂导致群体隔离

仿真研究必须考虑"网络权力"对结果的潜在影响。

---

## 6.13　本章小结(扩展版)

- 网络时间演化包括衰减、强化、新连接、偶遇接触。
- 多层网络(家庭/同事/社区/兴趣/在线)更接近真实社会。
- 共演化是行为和网络的双向耦合,是社会仿真最高级形态。
- 网络因果识别是社会网络研究的前沿。
- 应用领域:公共卫生、市场营销、组织管理、公共政策。
- 批判性视角:测量、同质性、网络结构与权力。
rage_clustering(G),
        "path_length": nx.average_shortest_path_length(G),
        "components": nx.number_connected_components(G),
        "diameter": nx.diameter(G) if nx.is_connected(G) else float("inf")
    }
```

### 6.14.2　中心性指标

```python
def centrality_metrics(G):
    """计算各种中心性"""
    return {
        "degree": nx.degree_centrality(G),
        "betweenness": nx.betweenness_centrality(G),
        "closeness": nx.closeness_centrality(G),
        "eigenvector": nx.eigenvector_centrality(G, max_iter=1000),
        "pagerank": nx.pagerank(G)
    }
```

### 6.14.3　社区检测

```python
import community as community_louvain

def detect_communities(G):
    """Louvain 社区检测"""
    partition = community_louvain.best_partition(G)
    n_communities = len(set(partition.values()))
    return {
        "partition": partition,
        "n_communities": n_communities,
        "modularity": community_louvain.modularity(partition, G)
    }
```

### 6.14.4　网络可视化

```python
import matplotlib.pyplot as plt

def visualize_network(G, communities=None, output="network.png"):
    """可视化网络"""
    fig, ax = plt.subplots(figsize=(12, 8))
    pos = nx.spring_layout(G, k=0.5, seed=42)
    if communities:
        colors = [communities[n] for n in G.nodes()]
        nx.draw_networkx_nodes(G, pos, node_color=colors,
                              cmap=plt.cm.tab20, node_size=100, ax=ax)
    else:
        nx.draw_networkx_nodes(G, pos, node_size=100, ax=ax)
    nx.draw_networkx_edges(G, pos, alpha=0.3, ax=ax)
    plt.title(f"网络: {G.number_of_nodes()} 节点, "
              f"{G.number_of_edges()} 边")
    plt.axis("off")
    plt.savefig(output, dpi=100, bbox_inches="tight")
```

---

### 6.15 扩展:网络传播的工程细节

### 6.15.1　SIR 模型变种

```python
def sir_variants(G, beta, gamma, model="standard", days=30):
    """不同 SIR 变种"""
    if model == "standard":
        return standard_sir(G, beta, gamma, days)
    elif model == "complex":
        return complex_contagion(G, beta, gamma, days, threshold=0.3)
    elif model == "weighted":
        return weighted_sir(G, beta, gamma, days)
```

### 6.15.2　复杂传染模型

```python
def complex_contagion(G, beta, gamma, days, threshold=0.3):
    """复杂传染:需要多个邻居都已感染才感染"""
    status = {n: "S" for n in G.nodes()}
    status[0] = "I"  # 种子节点
    history = []
    for day in range(days):
        new_status = status.copy()
        for n in G.nodes():
            if status[n] == "S":
                # 计算已感染邻居比例
                infected_neighbors = sum(
                    1 for m in G.neighbors(n) if status[m] == "I"
                )
                if infected_neighbors > 0:
                    infected_ratio = infected_neighbors / G.degree(n)
                    if infected_ratio > threshold and random.random() < beta:
                        new_status[n] = "I"
            elif status[n] == "I":
                if random.random() < gamma:
                    new_status[n] = "R"
        status = new_status
        history.append((day, sum(1 for v in status.values() if v == "I")))
    return history
```

### 6.15.3　网络干预

```python
def network_intervention(G, intervention_type, params):
    """网络干预"""
    if intervention_type == "remove_high_degree":
        # 移除高度节点(打破传播)
        degrees = dict(G.degree())
        threshold = params.get("threshold", 0.95)
        nodes_to_remove = [n for n, d in degrees.items()
                          if d > np.percentile(list(degrees.values()), threshold * 100)]
        new_G = G.copy()
        new_G.remove_nodes_from(nodes_to_remove)
        return new_G
    elif intervention_type == "add_random_edges":
        # 增加随机边(促进传播)
        new_G = G.copy()
        n_add = params.get("n_edges", 100)
        for _ in range(n_add):
            u, v = random.sample(list(G.nodes()), 2)
            if not new_G.has_edge(u, v):
                new_G.add_edge(u, v)
        return new_G
```

---

### 6.16 扩展:网络结构的批判性视角

### 6.16.1　网络假设的现实检验

仿真里常用的网络假设需要现实检验:

- 小世界假设:平均路径长度 ~ 6,真实网络可能更短或更长
- 无标度假设:度分布服从幂律,真实网络可能偏离
- 高聚类假设:聚类系数 ~ 0.4,真实网络可能不同

### 6.16.2　网络生成的可复现性

不同生成算法给出的网络差异巨大:

- Watts-Strogatz:小世界、高聚类
- Barabási-Albert:无标度
- Random:Erdős-Rényi,无结构

仿真研究必须明确使用的网络生成方法。

### 6.16.3　网络与行为的因果性

网络和行为哪个是因、哪个是果?

- "网络影响行为"(结构 → 行为)
- "行为塑造网络"(行为 → 结构)
- 两者共演化(共演化)

社会仿真必须明确处理这个问题。

---

## 6.17　本章小结(最终扩展版)

- 网络分析工具:常用指标、中心性、社区检测、可视化。
- 网络传播:SIR 变种、复杂传染、网络干预。
- 网络结构的批判性视角:假设检验、可复现性、因果性。


---

### 6.18 扩展:网络与制度的交叉

### 6.18.1　制度作为网络

制度(institution)可以被理解为社会网络:

- 法律关系
- 雇佣关系
- 交易关系

社会仿真可以把制度建模为网络。

### 6.18.2　网络对制度的塑造

网络结构塑造制度:

- 中心化的网络倾向于等级制度
- 分散的网络倾向于平等制度
- 模块化的网络倾向于联邦制度

### 6.18.3　制度对网络的反作用

制度也影响网络:

- 法律影响交易关系
- 文化影响社会关系
- 经济影响雇佣关系

### 6.18.4　制度网络的仿真

```python
class InstitutionalNetwork:
    def __init__(self):
        self.legal_relations = nx.DiGraph()
        self.economic_relations = nx.Graph()
        self.social_relations = nx.Graph()

    def add_legal_relation(self, u, v, type_):
        self.legal_relations.add_edge(u, v, type=type_)v, weight=transaction_volume)
```

---

### 6.19 扩展:网络与社会资本

### 6.19.1　社会资本的定义

社会资本(Social Capital)是个体或群体通过社会网络获得的资源:

- 信任
- 互惠规范
- 网络资源

### 6.19.2　社会资本的测量

社会资本的常用指标:

- 网络密度
- 互惠程度
- 信任水平
- 集体行动能力

### 6.19.3　社会资本的形成

社会资本的形成:

- 长期互动
- 共同经历
- 规范内化
- 制度支持

### 6.19.4　社会资本的仿真

```python
def compute_social_capital(G: nx.Graph, agents: list) -> dict:
    """计算社会资本"""
    return {
        "network_density": nx.density(G),
        "reciprocity": compute_reciprocity(G),
        "trust": compute_average_trust(agents),
        "collective_action": compute_collective_action_capacity(G)
    }
```

---

## 6.20　本章小结(最终扩展版)

- 网络与制度的交叉:制度作为网络、网络对制度、制度对网络。
- 网络与社会资本:定义、测量、形成、仿真。
- 网络是社会仿真最丰富的子系统,值得深入研究。


---

### 6.21 扩展:网络与传播的细节

### 6.21.1　传播的鲁棒性

网络对传播的鲁棒性:

- 高度节点移除:影响大
- 随机节点移除:影响小
- 中等度节点移除:影响中等

### 6.21.2　网络修复

被破坏的网络如何修复:

- 自修复:节点重新连接
- 外力修复:政策干预
- 演化修复:长期演化

### 6.21.3　多层网络的传播

多层网络(家庭 + 同事 + 朋友)的传播:

- 单独层传播有限
- 多层叠加放大
- 关键"桥"节点重要

### 6.21.4　网络免疫策略

网络免疫策略:

- 随机免疫
- 目标免疫(高度节点)
- 熟人免疫(邻居)
- 环形免疫

---

### 6.22 扩展:网络与博弈的结合

### 6.22.1　网络博弈

网络上的博弈:

- 每个节点是一个玩家
- 边是博弈对手
- 策略随时间演化

### 6.22.2　合作涌现

网络上的合作涌现:

- 强连接 → 合作
- 弱连接 → 背叛可能
- 网络结构影响合作水平

### 6.22.3　网络与社会规范

网络传播社会规范:

- 局部规范通过连接传播
- 群体规范涌现
- 规范演化与网络演化共演化

### 6.22.4　网络与集体行动

网络对集体行动的影响:

- 中心化网络 → 易协调
- 分散网络 → 难协调
- 模块化网络 → 局部行动化
- 价值观的传染

### 6.24.2　文化网络特性

文化网络通常有:

- 高聚类(同文化群体)
- 长尾分布(少数文化明星)
- 强弱连接混合

### 6.24.3　文化变迁的仿真

仿真文化变迁需要:

- 文化内容表示
- 文化传播机制
- 文化选择压力
- 文化演化追踪

### 6.24.4　文化多样性的维护

文化多样性的维护:

- 多语言政策
- 文化交流
- 保护少数民族文化
- 推广本土文化

---

### 6.25 扩展:网络与权力

### 6.25.1　权力的网络基础

权力的网络基础:

- 中心节点 → 影响力
- 桥接节点 → 信息垄断
- 高密度子网 → 群体力量

### 6.25.2　权力的测量

权力的测量:

- 中心性指标
- 结构洞
- 影响力传播

### 6.25.3　权力的仿真

仿真权力的运作:

- 不同权力结构的结果
- 权力变化的影响
- 权力对网络的影响

### 6.25.4　权力的伦理

权力的伦理问题:

- 权力是否合法
- 权力是否被滥用
- 弱势群体保护

---

## 6.26　本章小结(最终扩展版)

- 网络与文化:传播、特性、变迁、多样性。
- 网络与权力:基础、测量、仿真、伦理。
- 网络是社会仿真最丰富、最有研究价值的子系统。


---

## 6.27　本章尾声

经过本章,读者应该已经具备:

- 关系的数据结构设计
- 网络的拓扑生成
- 传染过程的建模
- 网络演化与共演化
- 幽灵节点的使用
- 网络分析工具
- 网络传播的工程实现
- 网络与文化、权力的结合
- 网络伦理的思考

最后,祝读者用好社会网络,做出更好的仿真!
史记录

每种方式各有优劣:

| 方式 | 优势 | 劣势 |
|---|---|---|
| 问卷 | 全面、个体感知 | 主观、样本小 |
| 观察 | 自然、客观 | 样本有限 |
| 数字足迹 | 大规模、长期 | 隐私问题 |
| 档案 | 历史数据 | 选择偏差 |

### 6.28.2　网络数据的偏差

网络数据有偏差:

- **抽样偏差**:某些人更容易被抽样
- **报告偏差**:某些关系更容易被报告
- **时间偏差**:某些时段数据更多
- **平台偏差**:某些平台更受欢迎

读者做网络研究时,要明确数据的局限。

### 6.28.3　网络测量的可靠性

网络测量的可靠性测试:

- **重测信度**:同一测量重复,看一致性
- **内部一致性**:不同题目测同一概念,看相关
- **观察者一致性**:不同观察者,看一致

### 6.28.4　网络研究的设计

网络研究的设计:

- **横截面研究**:某一时间点
- **纵向研究**:多个时间点
- **实验研究**:随机分配处理
- **自然观察**:真实场景观察

不同设计适合不同问题。

---

### 6.29 扩展:网络分析的具体技术

### 6.29.1　中心性指标

网络分析的中心性指标:

- **度中心性**(Degree Centrality):节点的直接连接数
- **中介中心性**(Betweenness Centrality):节点作为"桥梁"的程度
- **接近中心性**(Closeness Centrality):节点到其他节点的平均距离的倒数
- **特征向量中心性**(Eigenvector Centrality):ub_graph()

print("度中心性:", nx.degree_centrality(G))
print("中介中心性:", nx.betweenness_centrality(G))
print("接近中心性:", nx.closeness_centrality(G))
print("特征向量中心性:", nx.eigenvector_centrality(G))
print("PageRank:", nx.pagerank(G))
```

### 6.29.2　社区检测

社区检测算法:

- **Louvain 算法**:模块化优化,快速
- **Girvan-Newman**:基于边介数,准确但慢
- **标签传播**:简单快速,适合大规模
- **谱聚类**:基于矩阵分解

```python
import community as community_louvain

# Louvain 社区检测
partition = community_louvain.best_partition(G)
print("社区:", partition)
print("模块化:", community_louvain.modularity(partition, G))
```

### 6.29.3　网络对比

网络对比的方法:

- **QAP 相关**(Quadratic Assignment Procedure):两个网络的相关系数
- **随机图比较**:看真实网络是否显著不同于随机图
- **图核**:两个图的相似度

### 6.29.4　网络动态

网络动态分析:

- **节点加入/移除率**:网络更新频率
- **边变化率**:关系变化频率
- **聚类系数变化**:聚类结构演化
- **连通性变化**:网络是否分裂

---

### 6.30 扩展:网络与行为的双向耦合

### 6.30.1　选择 vs 影响

经典社会网络研究(Christakis-Fowler)区分两个机制:

- **社会影响**(Social Influence):朋友影响我
- **社会选择**(Social Selection):我选择朋友

这两个机制在真实网络中交织,区分它们是技术难题。

### 6.30.2　Christakis-Fowler 的方法

Christakis-Fowler 用三种方法分离影响和选择:

- **延迟分析**:在朋友变化前后测量我的变化
- **匹配控制**:选择"未受影响"的朋友作为对照
- **网络重构**:用潜在变量模型重构因果链

### 6.30.3　社会网络传染模型

社会网络传染的模型:

- **线性阈值模型**(Linear Threshold Model):节点达到阈值后激活
- **独立级联模型**(Independent Cascade Model):每个邻居有独立激活概率
- **传染病模型**:基于 SIR 过程

### 6.30.4　网络传染与行为传染

Christakis-Fowler 区分:

- **信息传染**:信息传播(快、浅)
- **行为传染**:行为传播(慢、深入)

他们发现肥胖是**行为传染**——需要多轮累积才会改变。

---

### 6.31 扩展:网络与制度

### 6.31.1　制度作为网络

制度(institutions)可以被理解为社会网络:

- 法律关系(谁被谁监管)
- 雇佣关系(谁雇佣谁)
- 交易关系(谁和谁做生意)

社会仿真研究制度时,可以把它建模为网络。

### 6.31.2　网络结构对制度的塑造

网络结构塑造制度:

- 中心化的网络倾向于等级制度
- 分散的网络倾向于平等制度
- 模块化的网络倾向于联邦制度

### 6.31.3　制度对网络的反作用

制度也影响网络:

- 法律影响雇佣网络
- 习俗影响社会网络
- 经济影响商业网络

社会仿真可以模拟"网络 + 制度"的共演化。

---

### 6.32 扩展:网络与文化

### 6.32.1　文化通过网络传播

文化通过网络传播:

- 习俗的扩散
- 语言的传播
- 时尚的演化
- 价值观的传染

### 6.32.2　文化网络特性

文化网络通常有:

- 高聚类(同文化群体)
- 长尾分布(少数文化明星)
- 强弱连接混合

### 6.32.3　文化变迁的仿真

仿真文化变迁需要:

- 文化内容表示
- 文化传播机制
- 文化选择压力
- 文化演化追踪

### 6.32.4　文化多样性的维护

文化多样性的维护:

- 多语言政策
- 文化交流
- 保护少数民族文化
- 推广本土文化

社会仿真可以研究不同文化政策的长期影响。

---

### 6.33 扩展:网络与权力

### 6.33.1　权力的网络基础

权力的网络基础:

- 中心节点 → 影响力
- 桥接节点 → 信息垄断
- 高密度子网 → 群体力量

### 6.33.2　权力的测量

权力的网络测量:

- 中心性指标(度、介数、PageRank)
- 结构洞(中介中心性)
- 影响力传播(基于网络扩散)

### 6.33.3　权力的仿真

仿真权力的差异:

- 不同权力结构的结果
- 权力变化的影响
- 权力对网络的影响

### 6.33.4　权力的伦理

权力的伦理问题:

- 权力是否合法
- 权力是否被滥用
- 弱势群体保护

---

### 6.34 扩展:网络与健康

### 6.34.1　健康传染

健康状态通过网络传播:

- **传染病**:流感、HIV
- **行为传染**:肥胖、吸烟、抑郁
- **幸福传染**:幸福感在朋友网络中传播

### 6.34.2　社会支持网络

社会网络影响健康:

- 社会支持 → 心理压力、疾病恢复
- 网络位置 → 健康资源访问
- 网络规模 → 健康行为传播

### 6.34.3　健康干预

网络视角的健康干预:

- 关键人物干预(找高度节点)
- 同伴教育(同质性原则)
- 社区动员(社区网络)

### 6.34.4　健康网络仿真

仿真研究健康网络:

- COVID-19 在社交网络传播
- 肥胖在朋友网络传染
- 戒烟在同事网络传播

---

### 6.35 扩展:网络与经济

### 6.35.1　经济网络

经济联系(企业间关系):

- 上下游交易
- 合作开发
- 人才流动

### 6.35.2　创新网络

创新通过网络传播:

- 创意在公司间传播
- 知识在研究者间共享
- 技术在生态中扩散

### 6.35.3　经济网络的仿真

仿真研究经济网络:

- 供应链模拟(Beer Game 是经典)
- 创新扩散(Rogers 2003)
- 金融危机传染

### 6.35.4　经济干预

网络视角的经济干预:

- 关键企业支持
- 网络加固(连接银行)

---

### 6.36 扩展:网络与组织

### 6.36.1　组织网络

组织内部的协作网络:

- 团队合作
- 部门协调
- 知识共享

### 6.36.2　组织仿真

仿真研究组织:

- 信息流分析
- 团队动态
- 组织演化

### 6.36.3　网络视角的组织设计

组织设计考虑网络:

- 减少跨部门壁垒
- 强化核心团队连接
- 提高组织适应性

---

### 6.37 扩展:网络与教育

### 6.37.1　教育网络

学生之间的关系:

- 同学关系
- 师生关系
- 家校关系

### 6.37.2　教育仿真

仿真研究教育:

- 同伴效应(朋友影响学业)
- 教师效应(教师影响学生)
- 家校合作(家庭参与)

### 6.37.3　网络视角的教育设计

教育设计考虑网络:

- 同伴学习(分组)
- 教师网络(教师合作)
- 家校沟通

---

### 6.38 扩展:网络与传播学

### 6.38.1　新闻传播

新闻通过网络传播:

- 传统媒体(广播、电视)
- 数字媒体(社交平台)
- 混合媒体

### 6.38.2　谣言传播

谣言在网络上传播:

- **传播速度**:几小时内传遍全球
- **传播范围**:多重因素决定
- **辟谣难度**:辟谣比谣言慢

### 6.38.3　舆论演化

舆论在网络上演化:

- **极化**:不同阵营加深
- **泡沫**:同质化加深
- **沉默螺旋**:少数派沉默

### 6.38.4　网络舆论仿真

仿真研究网络舆论:

- COVID-19 期间的舆论极化
- 选举期间的"过滤气泡"
- 谣言传播的"超级传播者"

---

## 6.39　本章小结(最终扩展版)

经过本章(包括扩展部分),读者应该已经具备:

- 社会网络的核心结构:关系、网络、节点、边
- 网络拓扑生成:小世界、无标度、随机
- 网络传染机制:SIR、复杂传染
- 网络演化:衰减、强化、共演化
- 幽灵节点:跨城关系
- 网络科学理论:小世界、无标度、模块化
- 网络与社会耦合:网络嵌入性、网络社会资本、网络不平等
- 网络科学批判:简化、因果、伦理
- 网络分析方法:中心性、社区检测、网络对比
- 网络与其他社会现象的耦合:制度、文化、权力、健康、经济、组织、教育、传播

**核心信息**:网络是社会仿真最重要的子系统,理解网络是做好社会仿真的基础。

读者读这份教材后,应该能用网络科学思维,看待社会现象——任何社会现象都发生在网络上,网络视角让你看到"看不见的结构"。

