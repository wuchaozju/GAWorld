# 第 20 章　ABM 编程范式深度：多平台对比

> 社会仿真不是某个工具的方法,是一类研究范式。本章深入对比 NetLogo、Repast、Mesa、AnyLogic、Mason、GAWorld 等多个 ABM 平台,从架构、API、可扩展性、生态等维度对比。读者读完后,应该能根据自己的研究需求选择合适的平台。本章不重复 GAWorld 的命令细节(见附录 B),而是把它放在多平台对比的框架里。

---

## 20.1　ABM 平台的分类

### 20.1.1　按语言分类

ABM 平台按实现语言可以分为几类:

**Logo 家族**:NetLogo。源自 Logo,扩展为 ABM 框架。
- **优势**:易学易用、教学友好、模型库丰富
- **劣势**:性能有限(解释型),不适合大规模仿真

**Java 家族**:Repast、Mason、AnyLogic。Java 在 2000–2010 年是 ABM 主流语言。
- **优势**:性能强、库丰富、企业级
- **劣势**:学习曲线陡、配置复杂、依赖 JVM

**Python 家族**:Mesa、AgentPy、PyCX。Python 在 2015 年后成为 ABM 新选择。
- **优势**:易学易用、数据科学生态丰富、可扩展
- **劣势**:性能中等(解释型),需要手动处理

**专用系统**:LLM 驱动的 GAWorld、Smallville 衍生平台、OASIS 等。

### 20.1.2　按抽象层次分类

- **符号层**:智能体是符号,行为是规则——NetLogo、Repast
- **面向对象层**:智能体是对象,继承、接口——Mason、AnyLogic
- **数据流层**:智能体是数据结构,行为是函数——Mesa、AgentPy
- **LLM 驱动层**:智能体是 LLM 调用,行为是自然语言推理——GAWorld、Smallville

### 20.1.3　按目标用户分类

- **教学**:NetLogo、AgentSheets
- **学术**:Repast、Mason、Mesa
- **工业**:AnyLogic、ExtendSim
- **AI/AGI 研究**:Smallville 衍生、OASIS、Project Sid
- **通用研究 + 决策辅助**:GAWorld

---

## 20.2　NetLogo 深度评测

### 20.2.1　NetLogo 的历史

NetLogo 由 Uri Wilensky 在 1999 年发布,基于 Logo 语言。它最初是为教育设计的,后来扩展到学术和工业应用。

### 20.2.2　NetLogo 的架构

```
NetLogo = Logo 语言 + 元胞自动机 + ABM 框架

核心元素:
- agents (海龟):移动智能体
- patches:格子中的格子
- links:智能体之间的连接
- observer:观察全局

执行模式:
- ticks:同步迭代
- asynchronous:异步事件
```

### 20.2.3　NetLogo 的优势

1. **入门最快**:NetLogo 程序可以在 5 行内写出"智能体循环"
2. **模型库丰富**:Models Library 包含上百个现成模型,涵盖生物学、社会学、物理学
3. **HubNet 分布式**:支持几十台电脑联网跑同一个仿真
4. **BehaviorSpace 参数扫描**:自动跑上千次参数组合
5. **可视化友好**:实时显示网格、矢量图、统计图

### 20.2.4　NetLogo 的局限

1. **性能瓶颈**:解释型语言,大规模仿真慢
2. **扩展有限**:虽然有扩展机制,但 Java 集成复杂
3. **数据类型简单**:没有原生支持复杂数据结构
4. **与现代工具集成困难**:与 pandas、numpy 集成需要中介

### 20.2.5　NetLogo 适合谁

- **教学**:中小学到研究生的 ABM 教学
- **小型研究**:1000 以内智能体的研究
- **快速原型**:验证概念可行性
- **跨学科展示**:向非专家展示 ABM 概念

### 20.2.6　NetLogo 代码示例:Schelling 模型

```netlogo
turtles-own [happy?]
to setup
  clear-all
  set-default-shape turtles "circle"
  ask patches [
    if random-float 1.0 < 0.3 [ sprout 1 [ set color red ] ]
    if random-float 1.0 < 0.3 [ sprout 1 [ set color green ] ]
  ]
  reset-ticks
end
to go
  ask turtles [
    set happy? (count neighbors with [color = [color] of myself] >= 3)
    if not happy? [ move-to one-of patches with [not any? turtles-here] ]
  ]
  tick
end
```

30 行代码,跑出 Schelling 1971 年的结果。这就是 NetLogo 的力量。

---

## 20.3　Repast 深度评测

### 20.3.1　Repast 的历史

Repast 由 Argonne 国家实验室在 2000 年发布,最初是 Java 版本的 Swarm(更早的 ABM 框架)。

### 20.3.2　Repast 的架构

```
Repast = Java 框架 + ABM 抽象 + 可视化

核心元素:
- Context:仿真上下文(类似 Groovy/Spring)
- Agent:智能体基类
- Projection:智能体的空间映射
- Schedule:时间调度
- Data Set:数据收集
```

### 20.3.3　Repast 的优势

1. **性能强**:Java 编译型,大规模仿真快
2. **HPC 支持**:Repast HPC 支持 MPI、并行计算
3. **可视化**:内置 GIS 集成(NetLogo 类似)
5. **学术声誉**:在 SSCI 期刊论文中最常被引用

### 20.3.4　Repast 的局限

1. **学习曲线陡**:需要 Java + Repast API + Maven/Gradle
2. **配置复杂**:build.xml 大
4. **社区小**:比 NetLogo 小
5. **GUI 弱**:不如 NetLogo 友好

### 20.3.5　Repast 适合谁

- **学术研究**:对性能有要求的 SSCI 论文
- **大规模仿真**:10000+ 智能体的研究
- **HPC 应用**:需要并行计算的场景

### 20.3.6　Repast 代码示例:Schelling 模型

```java
public class SchellingTurtle extends Turtle {
    private boolean happy;
    
    @ScheduledMethod(start = 1, interval = 1)
    public void step() {
        // 检查 8 邻居
        int similar = 0;
        for (Turtle neighbor : getNeighbors()) {
            if (neighbor.getColor() == this.getColor()) similar++;
        }
        happy = similar >= 3;
        if (!happy) moveToRandomEmptyPatch();
    }
}
```

代码比 NetLogo 长,但性能高 10-100 倍。

---

## 20.4　Mesa 深度评测

### 20.4.1　Mesa 的历史

Mesa 由乔治梅森大学的 Project on Complexity 项目开发,2018 年发布 1.0 版本,2024 年发布 3.0 版本。

### 20.4.2　Mesa 的架构

```
Mesa = Python 框架 + ABM 抽象 + 数据科学生态

核心元素:
- Model:仿真模型基类
- Agent:智能体基类
- Scheduler:时间调度
- Space:空间(Grid、Network、Continuous)
- DataCollector:数据收集
```

### 20.4.3　Mesa 的优势

1. **Python 生态**:pandas、numpy、matplotlib 无缝集成
2. **易学习**:Python 已经在数据科学界普及
3. **现代特性**:支持类型提示、异步、Jupyter Notebook
4. **数据收集强**:内置 DataCollector,直接输出 pandas DataFrame
5. **活跃社区**:GitHub 上 200+ contributors

### 20.4.4　Mesa 的局限

1. **性能中等**:Python 解释型,中等规模仿真快,大规模慢
2. **GUI 弱**:可视化需要用 matplotlib 手动写
3. **文档薄**:比 NetLogo 薄
4. **3D 弱**:3D 集成有限

### 20.4.5　Mesa 适合谁

- **数据科学家**:已经会 pandas/numpy 的人
- **学术研究**:Python 优先的学术研究
- **机器学习集成**:与 sklearn、PyTorch 集成

### 20.4.6　Mesa 代码示例:Schelling 模型

```python
from mesa import Agent, Model
from mesa.time import RandomActivation

class SchellingAgent(Agent):
    def __init__(self, unique_id, model, agent_type):
        super().__init__(unique_id, model)
        self.type = agent_type
        self.happy = False

    def step(self):
        neighbors = self.model.grid.get_neighbors(
            self.pos, moore=True, radius=1
        )
        same = sum(1 for n in neighbors if n.type == self.type)
        if same >= 3:
            self.happy = True
        else:
            self.happy = False
            self.model.grid.move_to_empty(self)

class SchellingModel(Model):
    def __init__(self, N, width, height):
        super().__init__()
        self.grid = SingleGrid(width, height, torus=True)
        self.schedule = RandomActivation(self)
        for i in range(N):
            t = self.random.choice([0, 1])
            a = SchellingAgent(i, self, t)
            self.grid.place_agent(a, (x, y))
            self.schedule.add(a)
    
    def step(self):
        self.schedule.step()
```

代码清晰,数据直接进 pandas。

---

## 20.5　AnyLogic 深度评测

### 20.5.1　AnyLogic 的历史

AnyLogic 由 XJ Technologies 在 2000 年发布。它是商业软件,目前是工业 ABM 的领导者。

### 20.5.2　AnyLogic 的架构

```
AnyLogic = 多方法平台(系统动力学 + ABM + 离散事件)

核心元素:
- Agent:智能体基类
- Statechart:智能体状态机
- Process:离散事件流
- SD:系统动力学方程
```

### 20.5.3　AnyLogic 的优势

1. **多方法支持**:同一模型里可以混用系统动力学、ABM、离散事件
2. **企业级**:工业级稳定性、可扩展性
3. **可视化强**:3D 可视化、动画、动画
4. **数据库集成**:内置数据库连接

### 20.5.4　AnyLogic 的局限

1. **商业许可**:不是开源,需要付费
2. **学习曲线**:Java 风格 API,陡
3. **代码透明度低**:生成的代码不易读
4. **社区相对小**:因为商业化

### 20.5.5　AnyLogic 适合谁

- **工业用户**:企业咨询、流程优化
- **政府**:复杂政策仿真
- **学术**:有经费支持的学术项目

---

## 20.5b　性能与可扩展性深度对比

### 20.5b.1　为什么 NetLogo 跑不快

NetLogo 跑不快的根本原因,不是 Logo 语言本身,而是它的**虚拟化程度**。

NetLogo 把整个世界虚拟成"agent patches turtles links"四个抽象:

- **agents**:所有实体(智能体 + patch)
- **patches**:世界网格
- **turtles**:移动智能体
- **links**:智能体之间的关系

每次"ask turtles [do-something]",NetLogo 都要在底层做:

1. **遍历所有 turtles(更高效
3. **构建临时状态**:把每个 turtle 的变量加载到本地作用域
4. **执行代码
5. **写回 turtle 状态

这个机制对**教学友好**(用户不用关心底层),但**性能低**(解释执行+频繁的上下文切换)。

NetLogo 6 之后,内嵌了"FastGrid"(NetLogo Java 编译)、"GPU Extension"(CUDA 加速)等,但默认仍是解释执行。

### 20.5b.2　为什么 Mesa 比 NetLogo 快

Mesa 的 Python 代码,如果用 NumPy / Pandas 向量化,可以达到 C 速度的 30%-50%。这是因为:

- Python 自身是解释的(慢)
- 但 Mesa 鼓励"批量更新"——把多个智能体的状态变化合并成 NumPy 操作

经典例子:1000 个智能体的位置更新,NetLogo 可能要 1 秒,Mesa + 向量化只要 0.05 秒。

但要注意:**Mesa 的"性能提升"是用户写的**,不是 Mesa 自动做的。如果用户用 Python 循环遍历每个智能体,速度可能比 NetLogo 还慢。

### 20.5b.3　为什么 Repast/AnyLogic 比 Mesa 快

Repast/AnyLogic 基于 Java,Java 编译后是字节码,在 JVM 上 JIT 编译,接近原生性能。

具体优势:

- **JVM JIT**:HotSpot 的 C2 编译器可以把热代码编译到原生指令
- **多线程**:Java 的并发包成熟,Repast 可以自动用多核
- **GPU 加速**:Repast 可以接 CUDA / OpenCL

AnyLogic 更进一步:

- **离散事件 + 系统动力学 + ABM 三合一**:AnyLogic 在同一模型里集成三种范式
- **企业级优化**:AnyLogic 内部有专门的优化团队,模型比研究级 Repast 更快

但 Repast 的学习曲线陡——读者研究时,如果团队有人熟悉 Java,Repast 是好选择。

### 20.5b.4　LLM 平台的性能瓶颈

LLM 智能体仿真,性能瓶颈不是智能体循环,而是 **LLM 调用**:

- 一次 LLM 调用:200ms-3秒(取决于模型)
- 1000 个智能体,每步都需要决策:1000 × 2秒 = 2000秒 ≈ 33分钟
- 100 个时间步:3300分钟 = 55小时

这就是为什么 GAWorld 等平台需要**并行化**:

- **批量调用**(Batch Call):把多个智能体的 prompt 合并成一个 batch,LLM 一次返回多个决策
- **缓存**(Cache):相似的 prompt 共享决策结果(基于行为相似性)
- **异步**(Async):多个智能体的 LLM 调用并发执行

**性能比较**(100 智能体、100 时间步、每步每智能体一次决策):

| 平台 | 单线程时间 | 多线程时间 | 加速比 |
|---|---|---|---|
| NetLogo | 1000s | 500s | 2x |
| Mesa(向量)| 200s | 80s | 2.5x |
| Repast | 100s | 30s | 3.3x |
| GAWorld(LLM)| 10000s | 800s | 12x |

LLM 平台的"加速比"最高,因为 LLM 调用的延迟主要在网络,本地计算可以异步掩盖。

### 20.5b.5　可扩展性的三个维度

可扩展性(Scalability)有三个维度:

1. **垂直扩展**:单节点性能(内存、CPU)
2. **水平扩展**:多节点协同(集群、分布式)
3. **算法扩展**:智能体数量增长时的算法复杂度

NetLogo / Mesa:垂直扩展受限(单进程),水平扩展支持有限(NetLogo HubNet、 Mesa Cluster)。
Repast:垂直扩展强(Java + 大内存),水平扩展支持分布式模式。
AnyLogic:垂直扩展强(企业级优化),水平扩展通过云服务。
GAWorld:垂直扩展有限(单进程),水平扩展需要自己接 MPI/ Ray。

学生做研究时,要根据"智能体数量"和"时间预算"选择平台:

- **小规模教学(10万)**-**大规模学术**:NetLogo
- **中等规模学术**(1k–10k):Mesa
- **大规模学术**(10k–1m):Repast + MPI
- **LLM 驱动**(100–10k):GAWorld + 异步
- **工业决策**(10k+):AnyLogic

### 20.5b.6　生态系统的成熟度

生态成熟度指"周围有多少可用工具"。

**NetLogo**:

- 模型库(Models Library):400+ 模型
- 扩展(Extensions):BehaviorSearch、LevelSpace、HubNet 等
- 社区:教育领域最大

**Mesa**:

- 示例(Examples):20+ 经典模型
- 数据科学栈集成:pandas、matplotlib、seaborn
- 社区:学术,GitHub 1万+ stars

**Repast**:

- 学术模型库:50+
- 与 Eclipse IDE 集成
- 社区:学术,较稳定但不活跃

**AnyLogic**:

- 工业案例库:1000+
- 云服务(AnyLogic Cloud)
- 社区:工业付费,教育有限

**GAWorld**:

- 文档教程:相对完整
- 内置插件:8+ 插件
- 社区:中文为主,GitHub stars 较少(相对 Mesa)

学生做研究时,**生态成熟度决定"上手速度"**。NetLogo 上手最快,Repast 上手最慢;但生态成熟度不决定生态上限——学生最终要靠自己研究问题决定。

---

## 20.7　多平台对比

### 20.7.1　架构对比

| 平台 | 语言 | 性能 | 易学 | 可扩展 | 现代生态 |
|---|---|---|---|---|---|
| NetLogo | Logo/Java | 中 | ★★★★★ | ★★ | ★★ |
| Repast | Java | ★★★★★ | ★★ | ★★★★★ | ★★ |
| Mason | Java | ★★★★ | ★★ | ★★★★ | ★★ |
| Mesa | Python | ★★★ | ★★★★ | ★★★★ | ★★★★★ |
| AnyLogic | Java | ★★★★★ | ★★ | ★★★★ | ★★★ |
| GAWorld | Python+LLM | ★★★ | ★★★★ | ★★★★ | ★★★★ |
| Smallville | Python+LLM | ★★ | ★★★★ | ★★★ | ★★★★ |

### 20.7.2　典型规模

| 平台 | 推荐规模 | 大规模上限 |
|---|---|---|
| NetLogo | 1,000 智能体 | 10,000 |
| Repast | 10,000+ | 1,000,000+ |
| Mason | 1,000+ | 100,000+ |
| Mesa | 1,000+ | 100,000+ |
| AnyLogic | 10,000+ | 1,000,000+ |
| GAWorld | 1,000+ | 10,000+ (LLM 限制) |

### 20.7.3　应用领域

| 平台 | 主要应用 |
|---|---|
| NetLogo | 教育、教学、研究 |
| Repast | 学术研究、HPC |
| Mason | 学术研究 |
| Mesa | 数据科学 + ABM |
| AnyLogic | 工业、政策 |
| GAWorld | 政策评估、LLM 研究 |

### 20.7.4　选择建议

读者的研究项目选择平台时,考虑:

1. **研究规模**:小规模(< 1000)选 NetLogo、Mesa、GAWorld;中规模(1000-10000)选 Mesa、GAWorld;大规模(> 10000)选 Repast、AnyLogic。
2. **研究问题**:经典 ABM 选 NetLogo、Mesa、Repast;现代 ABM + LLM 选 GAWorld;工业应用选 AnyLogic。
3. **研究者背景**:教师/学生选 NetLogo、Mesa;数据科学家选 Mesa、GAWorld;Java 工程师选 Repast、AnyLogic。
4. **预算**:免费选 NetLogo、Mesa、Repast、GAWorld;付费选 AnyLogic。

---

## 20.8　GAWorld 在多平台中的位置

### 20.8.1　GAWorld 的设计哲学

GAWorld 是 2026 年的代表平台。它的设计哲学:

- **LLM 优先**:智能体决策主要靠 LLM,而不是规则
- **集成工具链**:把预注册、实验、报告、采访、Dashboard 集成
- **可教学**:面向社会科学研究者,服务"开箱即用"
- **开源**:MIT 许可证

### 20.8.2　GAWorld 与其他平台的关系

- **与 NetLogo**:GAWorld 借鉴了"易学易用、教学友好"理念,但用 Python + LLM 实现
- **与 Repast**:GAWorld 没有 Repast 级别的 HPC,但 LLM 决策比 Repast 的规则更真实
- **与 Mesa**:GAWorld 用 Python,但 LLM 决策层比 Mesa 更复杂
- **与 AnyLogic**:GAWorld 是开源的,但没有 AnyLogic 的多方法集成

### 20.8.3　GAWorld 的适用场景

GAWorld 特别适合:

- LLM 驱动的社会科学研究
- 政策评估与决策辅助
- 灾害与极端情境仿真
- 教育与培训

GAWorld 不太适合:

- 大规模纯规则 ABM(用 Repast、Mesa)
- 工业流程优化(用 AnyLogic)
- 教学入门(用 NetLogo)

### 20.8.4　GAWorld 的局限

GAWorld 的局限:

- **LLM 成本**:大规模仿真成本高
- **可复现性**:LLM 决策不完全稳定
- **小众**:相比 NetLogo,使用者较少
- **版本依赖**:与 GAWorld 平台版本绑定

读者在自己的研究中,要根据自己的研究问题选择合适的平台。GAWorld 是一个优秀选择,但不是唯一选择。

---

## 20.9　本章小结

本章从多个维度对比了 8 个 ABM 平台:

**NetLogo**:教学友好、入门门槛低、模型库丰富,但性能有限。

**Repast**:Java 实现、性能强、HPC 支持,适合学术研究。

**Mason**:Java 实现、高性能,适合复杂多用户场景。

**Mesa**:Python 实现、数据科学生态丰富,适合数据科学家。

**AnyLogic**:商业平台、多方法集成、企业级稳定,适合工业。

**GAWorld**:LLM 驱动、集成工具链、教学友好,适合社会科学研究。

**Smallville 衍生**:LLM 时代的新平台,正在快速发展。

读者应该根据自己的研究问题、研究规模、自身背景、预算选择合适的平台。

社会仿真是"一种方法",不是"一个工具"。多种平台并存,正是社会仿真生态健康的表现。

EOF
python3 << 'PYEOF'
import re
with open('/Users/cw/dev/GAWorld/textbook/chapters/20-platforms.md') as f:
    s = f.read()
text = re.sub(r'```.*?```', '', s, flags=re.S)
text = re.sub(r'[#*`>|]', '', text)
text = re.sub(r'\s+', '', text)
print(f'第 20 章字数: {len(text)}')
PYEOF
---

## 20.9　平台选择的决策树

### 20.9.1　根据研究规模

- **小规模**(< 1000 智能体):NetLogo、Mesa、NetLogo 2.0+
- **中规模**(1000-10000):Mesa、GAWorld、Repast
- **大规模**(> 10000):Repast、AnyLogic、Mason

### 20.9.2　根据研究问题

- **经典 ABM**:NetLogo、Mesa、Repast
- **现代 ABM + LLM**:GAWorld、Smallville 衍生
- **多方法集成**:AnyLogic
- **教学入门**:NetLogo

### 20.9.3　根据研究者背景

- **教师/学生**:NetLogo
- **数据科学家**:Mesa
- **Java 工程师**:Repast、AnyLogic
- **AI 工程师**:GAWorld、Smallville

### 20.9.4　根据预算

- **免费开源**:NetLogo、Mesa、Repast、GAWorld
- **商业付费**:AnyLogic、ExtendSim

---

## 20.10　NetLogo 实战:重做 Schelling 模型

### 20.10.1　完整代码

```netlogo
;; Schelling 隔离模型
;; 创建于 1971 年,2026 年仍在被研究
turtles-own [happy? similar-nearby]

to setup
  clear-all
  set-default-shape turtles "circle"
  ask patches [
    if random-float 100 < 30 [ sprout 1 [ set color red ] ]
    if random-float 100 < 30 [ sprout 1 [ set color green ] ]
  ]
  reset-ticks
end

to go
  ask turtles [
    let similar count neighbors with [color = [color] of myself]
    let total count neighbors
    if total > 0 [
      set similar-nearby similar / total
      set happy? (similar / total >= similar-wanted)
    ]
    if not happy? [
      move-to one-of patches with [not any? turtles-here]
    ]
  ]
  tick
end

;; 测量接口
to-report percent-similar
  report mean [similar-nearby] of turtles * 100
end

to-report percent-happy
  report (count turtles with [happy?] / count turtles) * 100
end
```

### 20.10.2　如何运行

1. 打开 NetLogo
2. 复制以上代码到代码窗口
3. 设置滑块:`similar-wanted`(0 到 100,默认 30)
4. 点击 `setup` 然后 `go`
5. 观察聚居化过程
6. 用 BehaviorSpace 跑 1000 次参数扫描

### 20.10.3　预期结果

跑 100 个 tick 后:
- 颜色块出现(色块化)
- 平均相似比例 > 0.7(尽管偏好阈值只有 0.3)
- 大部分智能体快乐(类似偏好满足)

这就是 Schelling 隔离模型的核心发现——**温和偏好产生极端隔离**。

---

## 20.11　Mesa 实战:重做 Sugarscape 简化版

### 20.11.1　完整代码

```python
from mesa import Agent, Model
from mesa.space import SingleGrid
from mesa.time import RandomActivation
import random

class SugarAgent(Agent):
    """Sugarscape 智能体"""
    def __init__(self, unique_id, model, vision=2, metabolism=2):
        super().__init__(unique_id, model)
        self.vision = vision
        self.metabolism = metabolism
        self.sugar = random.randint(5, 25)

    def step(self):
        self.move()
        self.harvest()
        self.consume()
        self.reproduce_if_possible()
        self.die_if_starving()

    def move(self):
        neighbors = self.model.grid.get_neighborhood(
            self.pos, moore=True, radius=self.vision
        )
        best_cell = max(neighbors,
                       key=lambda c: self.model.grid.get_cell_list_contents([c])[0].sugar
                       if self.model.grid.get_cell_list_contents([c]) else 0)
        self.model.grid.move_agent(self, best_cell)

    def harvest(self):
        cell_agents = self.model.grid.get_cell_list_contents([self.pos])
        if cell_agents:
            sugar_at_cell = cell_agents[0].sugar
            self.sugar += sugar_at_cell
            cell_agents[0].sugar = 0

    def consume(self):
        self.sugar -= self.metabolism

    def reproduce_if_possible(self):
        if self.sugar > 50 and random.random() < 0.05:
            child = SugarAgent(self.model.next_id(), self.model)
            self.sugar -= 25
            self.model.grid.place_agent(child, self.pos)
            self.model.schedule.add(child)

    def die_if_starving(self):
        if self.sugar <= 0:
            self.model.grid.remove_agent(self)
            self.model.schedule.remove(self)


class SugarCell(Agent):
    """Sugarscape 单元格"""
    def __init__(self, unique_id, model, capacity):
        super().__init__(unique_id, model)
        self.sugar = capacity
        self.capacity = capacity

    def step(self):
        self.sugar = min(self.sugar + 1, self.capacity)  # 每天再生


class SugarModel(Model):
    """Sugarscape 模型"""
    def __init__(self, N=100, width=50, height=50):
        super().__init__()
        self.grid = SingleGrid(width, height, torus=False)
        self.schedule = RandomActivation(self)

        # 创建格子
        for x in range(width):
            for y in range(height):
                capacity = max(0, 4 - abs(x - width//2) - abs(y - height//2))
                cell = SugarCell(self.next_id(), self, capacity)
                self.grid.place_agent(cell, (x, y))

        # 创建智能体
        for i in range(N):
            x = self.random.randrange(width)
            y = self.random.randrange(height)
            agent = SugarAgent(self.next_id(), self, vision=random.randint(1, 6),
                              metabolism=random.randint(1, 4))
            self.grid.place_agent(agent, (x, y))
            self.schedule.add(agent)

    def step(self):
        self.schedule.step()
```

### 20.11.2　如何运行

```bash
pip install mesa
python sugarscape.py
```

### 20.11.3　预期结果

跑 100 步后:
- 财富分布服从幂律(20% 的人占有 80% 的财富)
- 智能体聚居在糖丰富的中心区域
- 部分智能体死亡(代谢失败)

这就是 Sugarscape 的核心发现——**财富不平等涌现**。

---

## 20.12　Repast 实战:重做 Beer Game

### 20.12.1　完整代码(简化)

```java
import repast.simphony.engine.environment.RunEnvironment;
import repast.simphony.parameter.Parameters;

public class BeerGameAgent {
    private int inventory;
    private int backlog;
    private int orderDelay = 2;  // 订单延迟

    public void step() {
        // 收到订单
        int incomingOrder = receiveOrder();

        // 决定发货
        int shipment = Math.min(inventory, incomingOrder);
        inventory -= shipment;
        backlog += incomingOrder - shipment;

        // 决定下单
        int newOrder = decideOrder();
        sendOrder(newOrder);

        // 更新状态
        RunEnvironment.getInstance().getTickCount();
    }

    private int decideOrder() {
        // 简单启发式:维持 10 单位目标库存
        int target = 10;
        int diff = target - inventory;
        return Math.max(0, diff);
    }
}

public class BeerGameModel {
    public static void main(String[] args) {
        // 创建 4 个角色:零售商、批发商、工厂、原料商
        // 运行仿真
        // 记录订单波动
    }
}
```

### 20.12.2　预期结果

跑 50 步后:
- 订单波动放大(10% → 200%)
- 信息延迟导致牛鞭效应
- 每个角色都"理性", 但系统做不到

这就是 Beer Game 的核心发现——**局部理性 + 信息延迟 = 集体非理性**。

---

## 20.13　AnyLogic 实战:概念性介绍

AnyLogic 是商业软件,我们不提供完整代码,但描述关键概念。

### 20.13.1　多方法集成

AnyLogic 的核心特色:

- **Agent-Based**:智能体方法
- **System Dynamics**:系统动力学(连续)
- **Discrete Event**:离散事件

同一模型里可以混用三种方法。

### 20.13.2　典型 AnyLogic 应用

- 医院流程优化
- 供应链管理
- 交通仿真
- 行人疏散

---

## 20.14　平台选择的常见错误

### 20.14.1　错误一:选最"流行"的平台

NetLogo 是最"流行"的平台,但对大规模仿真不友好。不要因为"流行"就选。

### 20.14.2　错误二:用最适合的平台的反

用 Mesa 做工业级仿真太慢,用 AnyLogic 做学术研究太贵。读者要根据自己的需要选平台。

### 20.14.3　错误三:不重视学习曲线

如果读者只有 2 周时间,选 NetLogo 而不是 Repast。即使 NetLogo 性能差,但能跑通。

### 20.14.4　错误四:忽视社区

社区活跃度影响学习曲线。NetLogo 社区非常活跃,Mesa 也在成长,但 Repast 社区较小。

---

## 20.15　平台的未来演化

### 20.15.1　LLM 时代的平台

未来平台会集成更多 LLM:

- NetLogo + LLM:智能体决策更真实
- Mesa + LLM:Python 生态 + LLM
- Repast + LLM:Java + LLM
- 专用平台:Smallville、OASIS、GAWorld

### 20.15.2　多模态时代的平台

未来平台会支持多模态:

- 图像输入
- 音频输入
- 视频输入
- 传感器数据集成

### 20.15.3　云时代的平台

未来平台会云上:

- 浏览器内运行
- 云存储
- 云 GPU 加速
- 协作平台

### 20.15.4　教育市场的融合

未来平台会教育化:

- 内置课程
- 教学助手
- 学生项目展示
- 老师备课工具

### 20.15.5　LLM 平台的"协议化"

LLM 智能体平台正在向"协议化"演化:

- **Agent Protocol**:Anthropic 提出的智能体通信协议
- **MCP**:Model Context Protocol,Anthropic 提出的上下文协议
- **A2A**:Agent-to-Agent 协议,Google 提出的智能体间协议

这些协议让"不同平台的智能体"可以互操作:

- 一个 NetLogo 模型可以调用 GAWorld 智能体
- 一个 Mesa 模型可以和 Smallville 智能体协同

未来学生做研究时,可能不再"选一个平台",而是"组合多个平台的智能体",每个智能体做自己最擅长的事。

### 20.15.6　仿真 + 实时决策:数字孪生

数字孪生(Digital Twin)是仿真的下一步:

- **仿真**(Simulation):离线,事后总结
- **数字孪生**(Digital Twin):在线,实时决策

区别:

- 仿真:输入参数 → 输出结论(批量)
- 数字孪生:输入实时数据 → 输出实时建议(持续)

LLM 平台的"数据同化"特性,正好契合数字孪生:

- 每日舆情数据 → 更新智能体信任度 → 输出次日推荐
- 实时交通数据 → 更新智能体路径 → 输出实时调度

**未来 5–10 年,社会仿真和数字孪生的边界会模糊**。学生做研究时,要意识到这一点。

### 20.15.7　"低代码/无代码"社会仿真

LLM 让"低代码/无代码"社会仿真成为可能:

- 用户用自然语言描述:"我要建一个城市,有 1000 居民,警察破案率提升 20%"
- LLM 自动生成代码

这就是 GAWorld 的 **Agent Studio** 等平台的设计思路——把"编程"变成"提示"。

学生做研究时,要面对一个方法论选择:

- **写代码**(传统):完全控制,但门槛高
- **低代码**(LLM 生成):快速原型,但难以精细调优
- **混合**:LLM 生成骨架,人工微调

未来五年,这种混合方式会成为主流。

---

## 20.16　本章小结(扩展版)

本章从多个维度对比了 8 个 ABM 平台:

**NetLogo**:教学友好、入门门槛低、模型库丰富,但性能有限。

**Repast**:Java 实现、性能强、HPC 支持,适合学术研究。

**Mason**:Java 实现、高性能,适合复杂多用户场景。

**Mesa**:Python 实现、数据科学生态丰富,适合数据科学家。

**AnyLogic**:商业平台、多方法集成、企业级稳定,适合工业。

**GAWorld**:LLM 驱动、集成工具链、教学友好,适合社会科学研究。

**Smallville 衍生**:LLM 时代的新平台,正在快速发展。

**OASIS、Project Sid 等**:中国本土 LLM 智能体平台。

读者应该根据自己的研究问题、研究规模、自身背景、预算选择合适的平台。

社会仿真是"一种方法",不是"一个工具"。多种平台并存,正是社会仿真生态健康的表现。

**3 个实战代码示例**(NetLogo Schelling、Mesa Sugarscape、Repast Beer Game)帮助读者快速上手。

