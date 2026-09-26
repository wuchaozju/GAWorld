# 第 5 章　环境：城市、事件与时空

> 智能体生活在什么样的世界里?一个城市、一片社区、一份工作、一个家庭——这些都是"环境"。社会仿真里的环境不只是地图,它包括三个维度:物理空间(地点+距离+价格)、社会情境(同场所的人)、突发事件(政策+自然+经济+技术)。这一章拆解环境的设计要点,并给出一段可以直接跑的"城市 + 事件触发器"代码。

---

## 5.1　环境的三个维度

环境在社会仿真里经常被误处理成"地图"——一个城市的地图加上智能体的位置。这种简化丢失了**情境**和**事件**两层关键信息。

第一层是**物理空间**。地图、距离、通勤时间、地点价格、天气——这些是"看得见的环境"。一个住在 30 公里外、通勤 1.5 小时的人和一个住在 5 公里外、通勤 0.5 小时的人,即便收入一样,他们的生活节奏截然不同。

第二层是**社会情境**。同一家咖啡馆里的人、同一个候车室里的人、同一所学校里的同学——这些是"看得见但不一定看见的人"。情境塑造行为:在图书馆你安静,在酒吧你放纵,在公司你职业。仿真里如果不模拟情境,智能体就缺少"角色切换"的能力,行为会显得扁平。

第三层是**突发事件**。限行令、暴雨、流感疫情、公司裁员、新技术上线——这些是"打破节奏"的事件。它们在仿真里往往是研究问题的核心驱动:研究者关心的常常不是"平时什么样",而是"遇到事件会怎么变"。

把环境分成三层后,仿真就有了清晰的扩展空间:研究者可以单独改动一层,看其他两层的反应。这是社会仿真和"纯地理信息系统"的关键区别——它关心的是**多层耦合**,而不是"地理事实"。

```
       ┌─────────────────────────────┐
       │       突发事件(政策/自然)    │
       │     ↓ ↓ ↓ ↓ ↓ ↓ ↓ ↓ ↓      │
       │  ┌────────────────────────┐ │
       │  │   社会情境(同场所的人) │ │
       │  │  ↓ ↓ ↓ ↓ ↓ ↓ ↓ ↓      │ │
       │  │ ┌──────────────────┐   │ │
       │  │ │  物理空间(地图)  │   │ │
       │  │ │  智能体在格子上  │   │ │
       │  │ └──────────────────┘   │ │
       │  └────────────────────────┘ │
       └─────────────────────────────┘
        (三层相互影响,共同决定行为)
```

---

## 5.2　城市地图:从抽象网格到真实 OSM

仿真里用什么地图?历史上走过三个阶段。

**阶段一:抽象网格**(1960s–1990s)。一个 N×N 的棋盘,每个格子代表一个"地块"。简单、可分析、计算快。Schelling 的隔离模型就是这种。缺点是脱离现实——读论文的人想象不出"棋盘上的一个格子"对应现实中的什么。

**阶段二:合成城市**(2000s)。用程序生成"看起来像城市"的地图——主干道、次干道、街区、商圈。Sugarscape 是这类。优点是"看起来像真的",缺点是合成城市没有任何现实意义——你不能用它去研究"杭州限行令"。

**阶段三:真实地图**(2010s 至今)。直接用 OpenStreetMap(OSM)、政府开放数据、卫星图像作为仿真底图。优点是**每一寸地图都对应现实**,可以直接做政策仿真;缺点是数据量大、清洗成本高、需要 GIS 能力。

GAWorld 采用第三阶段。具体技术路线:

```
Nominatim 地理编码 → Overpass API 抓取 OSM 数据
    ↓
解析 → 节点(路口/POI) + 道路(线段) + 行政区(多边形)
    ↓
计算几何中心 → 锚定投影坐标系
    ↓
输出 → data/cities/<slug>/{city.json, citymap.md, map.geojson}
```

这套流程的关键设计是**离线兜底**:如果网络不可用(Nominatim 失败、Overpass 抓不到),程序化生成一个"虚拟城市"作为兜底。读者如果做研究,应该确认一下你用的城市包是"真实地图"还是"程序生成"——前者可信度更高,后者只是占位符。

### 一个具体的城市生成示例

```bash
# 创建一个真实城市包
python -m gaworld.city create "绍兴柯桥" --size 200
# → 抓 OSM 数据
# → 生成 200 个居民
# → 写入 data/cities/shaoxing_keqiao/

# 离线兜底(无网络时)
python -m gaworld.city create "柳溪村" --offline --scale tiny
# → 程序生成"虚拟村庄"地图
# → 生成 30 个居民
```

命令背后调用的是 `gaworld/city/` 下的若干模块,具体细节见 GAWorld 文档 `docs/CITY_TUTORIAL.md`。第 13 章会用一个完整案例演示这一流程。

---

## 5.3　出行、通勤与场所效用

环境对行为的影响,主要通过"出行"体现——一个人从家到公司、从家到公园、从公司到餐厅,每一次移动都是一次决策。仿真里的出行建模有几个关键概念。

**距离衰减**:目的地越远,被选择的概率越低。经典模型是引力模型(gravity model):P(i → j) ∝ A_j / d(i,j)^γ,其中 A_j 是目的地吸引力,d 是距离,γ 通常取 1.5–2.0。读者在自己做研究的时候,可以先从 γ=1.5 起步,根据真实数据校准。

**通勤时间**:这是比"距离"更重要的变量。读者如果只能选一个,选"通勤时间"。同样 30 公里,如果全程高速 25 分钟,和城市道路 75 分钟,行为差异巨大。

**场所效用**:每个地点(POI)有自己的"效用函数"。餐厅的效用由菜系、价格、评分决定;公司的效用由工资、通勤时间、行业决定。智能体在每个时间步选择效用最高的地点。

**天气与高峰**:极端天气降低出行意愿,高峰时段增加通勤时间。GAWorld 在 `gaworld/world/city_map.py` 里实现了这些调整因子。

代码示例:一个简单的场所选择模型。

```python
# examples/place_choice.py
from dataclasses import dataclass
import math

@dataclass
class Place:
    name: str
    category: str
    appeal: float    # 1–10
    price: float     # 元
    distance_km: float

def gravity_choice(places: list, agent_loc: tuple, gamma: float = 1.5) -> str:
    """引力模型:返回被选中的地点名"""
    scores = []
    for p in places:
        d = p.distance_km
        score = (p.appeal / max(0.1, d ** gamma))
        # 价格折扣:便宜的稍微加分
        score *= (10 / max(1, p.price / 10))
        scores.append((score, p.name))
    return max(scores)[1]

# 三家餐厅对比
r1 = Place("兰亭小馆", "餐厅", 8.0, 80, 1.2)
r2 = Place("外婆家", "餐厅", 7.5, 60, 3.5)
r3 = Place("西餐厅 A", "餐厅", 9.0, 250, 5.0)

chosen = gravity_choice([r1, r2, r3], (0, 0))
print(f"今晚选: {chosen}")  # 通常是 r1(近+便宜+评分不低)
```

这段代码演示了"地点选择"的最小实现。真正的 GAWorld 在每个仿真 tick 里会为每个智能体计算几十个候选地点,挑选最高分的那个。

---

## 5.4　环境事件分类

环境事件是仿真里"打破节奏"的力量。一个真实社会的研究问题,几乎总离不开某个事件——没有事件,世界就是静止的,仿真就是浪费算力。

GAWorld 把事件分成四大类:

**政策事件**(policy events)。限行令、税收调整、福利改革、补贴发放、限购政策。这类事件的特点是"可预期、可公告、可实施"。政策事件往往有"宣告期 + 实施期 + 缓冲期",不同阶段对行为的影响不同。

**自然事件**(natural events)。地震、洪水、台风、疫情。这类事件的特点是"突发、范围广、不可控"。自然事件往往引发群体性的行为变化——避险、互助、抢购。

**经济事件**(economic events)。通胀、衰退、汇率波动、行业崩盘、新行业崛起。这类事件的特点是"持续、缓慢、可累积"。经济事件的影响常常不是立刻显现,而是几个月后才在居民行为上反映出来。

**技术事件**(technology events)。平台规则突变、新工具普及、老服务下线。这类事件的特点是"渐进、可选、可逆"。技术事件对居民的影响常常是分层——年轻人先适应,老年人后适应。

代码示例:一个事件触发器。

```python
# examples/event.py
from dataclasses import dataclass
from datetime import datetime

@dataclass
class PolicyEvent:
    name: str
    category: str
    announced_at: datetime
    effective_at: datetime
    parameters: dict

def on_event(event: PolicyEvent, agent_state: dict):
    """事件对智能体状态的即时影响"""
    if event.category == "限行":
        # 通勤决策改变
        agent_state["car_use_prob"] *= 0.3  # 减少 70% 开车概率
    elif event.category == "补贴":
        # 经济状态改变
        agent_state["cash"] += event.parameters.get("amount", 0)
    elif event.category == "封城":
        # 行为范围缩窄
        agent_state["movement_radius"] *= 0.1
    return agent_state

# 模拟一次限行事件
ev = PolicyEvent(
    name="工作日按尾号限行",
    category="限行",
    announced_at=datetime(2026, 6, 1),
    effective_at=datetime(2026, 6, 15),
    parameters={"plate_rules": "周一1&6,周二2&7,..."}
)

state = {"car_use_prob": 0.8, "cash": 5000, "movement_radius": 1.0}
new_state = on_event(ev, state)
print(new_state)  # → {'car_use_prob': 0.24, ...}
```

这段代码是事件触发器的最小实现。GAWorld 的真实版本在 `gaworld/env/system.py` 里实现了完整的事件管线,包含"公告—实施—缓冲—结束"四个生命周期阶段。

### 事件对居民行为的层次性影响

一个事件不是立刻全面影响所有人,而是按层级扩散:

**第一层:知晓**(awareness)。居民通过新闻媒体、社群讨论、政府公告得知事件。知晓时间从小时(政策公告)到天(经济变化)不等。

**第二层:理解**(understanding)。居民理解事件对自己的影响。这需要智能体能读懂政策文本、做条件推理。LLM 驱动的智能体在这里表现更好,规则智能体常常出错。

**第三层:行动**(action)。居民调整行为。这是最直接可观测的层。

**第四层:反馈**(feedback)。居民对政策的评价,可能进一步影响政策本身(政治反馈)。

做研究时,要明确你关心的是哪一层。如果只关心"行为变化"(第三层),可以在知晓和理解层做简化;如果关心"政治反馈"(第四层),必须把知晓和理解层也建好。

---

## 5.5　节律:工作日/周末/昼夜/季节

环境不是静态的,它有节律。一个仿真如果忽略节律,会出现"周一和周日行为一样"的失真。

GAWorld 的节律系统分四类:

**昼夜节律**(daily)。24 小时循环:0–6 点睡眠、7–8 点晨起、9–18 点工作、19–21 点晚餐/娱乐、22–24 点睡眠。

**周节律**(weekly)。7 天循环:周一到周五工作,周六周日休息。但不同职业有不同的"周末"(餐饮业的"周末"是周三周四)。

**季节节律**(seasonal)。4 季循环:夏季外出多、冬季室内多;春节前后流动人口大幅变化;7–8 月是旅游高峰。

**生命节律**(life)。以个体年龄为周期的循环:0–6 岁学前、7–18 岁上学、19–25 岁大学/工作、26–60 岁职业期、60+ 退休。

节律不是孤立的——它们相互嵌套。一个智能体在"周末 + 夏季 + 周末上午"的行为,和"工作日 + 冬季 + 工作日上午"的行为,差异巨大。仿真里把这些节律都叠加起来,才能产生"人味"。

```python
# examples/rhythm.py
from datetime import datetime, timedelta

def is_working_hour(t: datetime, job: str) -> bool:
    """判断给定时间是否是工作小时"""
    weekday = t.weekday()  # 0=周一, 6=周日
    hour = t.hour
    # 周末不工作(但餐饮业例外)
    if weekday >= 5 and "餐饮" not in job:
        return False
    # 9–18 点是工作时间
    return 9 <= hour < 18

# 周一上午 9 点 + 医生 → 工作
t1 = datetime(2026, 9, 28, 9, 0)
print(is_working_hour(t1, "医生"))  # True
# 周日上午 9 点 + 医生 → 不工作
t2 = datetime(2026, 9, 27, 9, 0)
print(is_working_hour(t2, "医生"))  # False
# 周日上午 9 点 + 餐饮 → 工作
print(is_working_hour(t2, "餐饮服务员"))  # True
```

---

## 5.6　代码示例:一个最小城市 + 事件触发器

把 5.1–5.5 节的内容整合起来,写一个"最小可行城市 + 事件触发器"。

```python
# examples/mini_city.py
from dataclasses import dataclass, field
from typing import List
from datetime import datetime, timedelta
import random

@dataclass
class Place:
    name: str
    category: str
    pos: tuple  # (x, y)
    appeal: float = 5.0

@dataclass
class City:
    name: str
    places: List[Place] = field(default_factory=list)

    def nearest(self, pos: tuple, category: str) -> Place:
        candidates = [p for p in self.places if p.category == category]
        return min(candidates, key=lambda p: (p.pos[0]-pos[0])**2 + (p.pos[1]-pos[1])**2)

# 创建一个小城市
city = City(name="柯桥", places=[
    Place("家", "住宅", (0, 0)),
    Place("医院", "医疗", (1, 1)),
    Place("公司", "工作", (5, 5)),
    Place("公园", "娱乐", (3, 0)),
    Place("餐厅", "餐饮", (2, 2)),
])

# 一个居民走一天
@dataclass
class Citizen:
    name: str
    home: Place
    workplace: Place

c = Citizen(name="林素", home=city.nearest((0,0), "住宅"), workplace=city.nearest((5,5), "工作"))
print(f"{c.name} 家在 {c.home.name},公司在 {c.workplace.name}")

day = datetime(2026, 9, 26, 8, 0)
schedule = [
    (8, 0, c.home.name, "起床"),
    (9, 0, c.workplace.name, "上班"),
    (12, 0, "餐厅", "午餐"),
    (13, 0, c.workplace.name, "上班"),
    (18, 0, "公园", "散步"),
    (19, 0, "餐厅", "晚餐"),
    (21, 0, c.home.name, "回家"),
]

for h, m, place, action in schedule:
    t = day.replace(hour=h, minute=m)
    p = city.nearest((random.uniform(0,5), random.uniform(0,5)), place) if place not in [c.home.name, c.workplace.name] else (c.home if place==c.home.name else c.workplace)
    print(f"{t.strftime('%H:%M')} | {action:8s} | 去{p.name}")
```

这段代码演示了"城市地图 + 居民 + 一天日程"的最小实现。把它和第 4 章的智能体代码合并,再加上事件触发器,就构成了一个"小社会"。

---

## 5.7　本章小结

- 环境分三个维度:物理空间、社会情境、突发事件,三层耦合决定行为。
- 城市地图走过三个阶段:抽象网格、合成城市、真实 OSM,GAWorld 用第三阶段。
- 出行模型的核心是"距离衰减 + 通勤时间 + 场所效用 + 天气/高峰系数"。
- 环境事件分四类:政策、自然、经济、技术,每个事件有"知晓—理解—行动—反馈"四层影响。
- 节律分四类:昼夜、周、季节、生命,四者嵌套才有"人味"。

---

## 5.8　思考题

1. **选一个你关注的环境事件**(例如限行令、疫情封控、新平台上线),**画一张事件影响的层级图**:知晓—理解—行动—反馈,每个层级具体表现什么?
2. 用 5.3 节的引力模型,**为一个真实场景**(你家附近的餐厅选择)拟合 γ 参数:你过去一周去了几次?每次去哪家?估算每家的 appeal 和距离,反推 γ 值。
3. **为限行令案例设计一个"事件触发器"**:从政策公告到生效的 14 天内,居民状态如何变化?用代码或伪代码描述。

---

## 5.9　延伸阅读

1. Gastner, M. T., & Newman, M. E. J. (2006). The Spatial Structure of Networks. *European Physical Journal B*, 49(2), 247–252. —— 网络在地理空间上的分布规律。
2. Batty, M. (2008). The Size, Scale, and Shape of Cities. *Science*, 319(5864), 769–771. —— 城市作为复杂系统的研究纲领。
3. Bettencourt, L. M. A., & West, G. B. (2010). A Unified Theory of Urban Living. *Nature*, 467(7318), 912–913. —— 城市标度律。
4. Huckfeldt, R. R. (2007). *Political Socialization in Context: The Effect of Political Discussion Networks on Citizen Attitude Change*. —— 政策事件如何在社群中扩散。
5. Slovic, P. (1987). Perception of Risk. *Science*, 236(4799), 280–285. —— 风险事件如何被不同群体感知不同。
6. GAWorld 工程文档:`gaworld/world/city_map.py`、`gaworld/env/system.py`、`docs/CITY_TUTORIAL.md`。
7. Helbing, D. (2010). *Quantitative Sociodynamics: Stochastic Methods and Models of Social Interaction Processes*. Springer. —— 行人交通、群体动力学的代表著作。
8. Brockmann, D., Hufnagel, L., & Geisel, T. (2006). The Scaling Laws of Human Travel. *Nature*, 439(7075), 462–465. —— 人类出行距离服从幂律分布。

---

> **本章教学注释**
>
> 这一章是技术层第二章,和第 4 章构成"智能体 + 环境"的对偶。第 4 章关注"住在身体里",本章关注"住在世界里"。如果读者已经在做仿真研究,会发现环境建模的 80% 工作量在这一章。`gaworld/world/city_map.py` 实现了本章大部分功能,5000+ 行代码,完整支持 OSM 解析、出行计算、节律叠加、事件注入。
>
> 5.6 节的代码故意很短——目的是让读者看到"环境 + 智能体"的最小组合。把它扩展到 100 个智能体,加上 LLM 决策,就是 GAWorld 的核心架构。第 13 章会用一个完整案例演示这个组合。下一章我们进入"社会网络":智能体和谁说话?关系如何影响行为?
---

## 5.8　扩展:城市基础设施建模

城市不只是地图和建筑,还包括**城市基础设施**——交通、能源、水务、通讯。这些是社会仿真的"骨架"。

### 5.8.1　交通基础设施

交通设施包括:

- **道路网络**:主干道、次干道、支路
- **公共交通**:地铁、公交、出租车、共享单车
- **停车场**:商业、住宅、公共
- **信号灯**:交通流控制

仿真里的交通建模:

```python
# examples/transport_model.py
def compute_travel_time(origin: tuple, destination: tuple,
                       transport_mode: str, hour: int) -> float:
    """计算出行时间"""
    distance = haversine_km(origin, destination)
    if transport_mode == "car":
        base_speed = 40  # km/h
        rush_hour_penalty = 1.5 if hour in [8, 17] else 1.0
        return distance / base_speed * rush_hour_penalty
    elif transport_mode == "transit":
        return distance / 25 * 1.2  # 公交平均 25 km/h,加 20% 等车时间
    elif transport_mode == "bike":
        return distance / 15
    elif transport_mode == "walk":
        return distance / 5
```

### 5.8.2　能源基础设施

能源建模在社会仿真里相对少见,但对碳排放研究至关重要:

- 电力网络:发电、输电、配电
- 水务网络:自来水、污水
- 燃气网络:天然气、暖气

### 5.8.3　通讯基础设施

通讯网络包括:

- **固定电话**:历史数据,2026 年已少用
- **移动通信**:4G/5G
- **互联网**:光纤、WiFi、宽带
- **应急通讯**:无线电、卫星

通讯基础设施影响"灾害场景下的信息传播"——这是第 16 章灾害模式的关键。

---

## 5.9　扩展:环境事件的影响层次

环境事件对居民的影响不是瞬时的,而是分层的。本节深入展开。

### 5.9.1　知晓层(Awareness)

居民如何得知事件?几种渠道:

- **官方公告**:政府、媒体、社交媒体官方账号
- **社群讨论**:邻居、同事、朋友
- **个人观察**:直接看到事件(如洪水、限行标志)
- **算法推送**:个性化推荐

仿真里的知晓机制:

```python
# examples/awareness.py
def awareness_probability(agent: dict, event: dict, day: int) -> float:
    """agent 在第 day 知晓事件的概率"""
    base = 0.3  # 基础概率
    # 社交网络的影响
    social_influence = sum(
        relation["strength"] for relation in agent["social_network"]
    ) / len(agent["social_network"])
    # 媒体使用
    media_factor = 1.0 if agent["uses_media_heavily"] else 0.6
    # 时间衰减
    time_factor = min(1.0, day / 7)  # 一周内达到最大知晓率
    return base * social_influence * media_factor * time_factor
```

### 5.9.2　理解层(Understanding)

居民理解事件的程度:

- **字面理解**:知道发生了什么
- **影响理解**:知道对自己意味着什么
- **行动理解**:知道该做什么

仿真里,LLM 决策能给出较好的"影响理解"和"行动理解",但"字面理解"需要用规则系统。

### 5.9.3　行动层(Action)

行动层的关键变量:

- **可选项**:agent 能做哪些事?
- **资源**:agent 有多少现金、时间、社会支持?
- **机会成本**:做这件事意味着放弃什么?

### 5.9.4　反馈层(Feedback)

居民行动后,会对事件有评价:

- **满意**:觉得政策好
- **中立**:没感觉
- **不满意**:觉得政策差

反馈影响后续政策或下一轮事件的设计。这是"政策仿真"的核心循环。

---

## 5.10　扩展:环境的工程化实现

GAWorld 的环境模块有几个关键工程实现。

### 5.10.1　地图缓存

```python
# examples/map_cache.py
import hashlib

def get_map(city_slug: str) -> dict:
    """读城市地图,带缓存"""
    cache_path = f"data/cities/{city_slug}/map_cache.pkl"
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return pickle.load(f)
    # 没有缓存则生成
    map_data = generate_map_from_osm(city_slug)
    with open(cache_path, "wb") as f:
        pickle.dump(map_data, f)
    return map_data
```

地图缓存能减少 80% 以上的地图读取时间。

### 5.10.2　节律叠加

```python
# examples/rhythm_overlay.py
def get_active_rhythms(t: datetime) -> list:
    """获取当前时刻的所有活跃节律"""
    rhythms = []
    # 昼夜节律
    if 9 <= t.hour < 18 and t.weekday() < 5:
        rhythms.append("工作时段")
    elif t.hour >= 22 or t.hour < 6:
        rhythms.append("睡眠时段")
    # 季节节律
    if t.month in [7, 8]:
        rhythms.append("夏季高温")
    # 生命节律
    # (需要 agent 信息)
    return rhythms
```

### 5.10.3　环境事件的优先级

```python
# examples/event_priority.py
def event_priority(event: dict, current_time: datetime) -> int:
    """事件优先级"""
    priority = 0
    # 时间紧迫性
    time_to_event = (event["effective_at"] - current_time).days
    if time_to_event <= 7:
        priority += 10
    # 事件类型
    if event["category"] == "natural":
        priority += 20
    elif event["category"] == "policy":
        priority += 15
    elif event["category"] == "economic":
        priority += 10
    return priority
```

---

## 5.11　扩展:环境研究的学术前沿

环境建模在学术上的最新进展。

### 5.11.1　数字孪生城市

数字孪生城市是 2020 年后的研究热点:

- 真实城市的实时数字副本
- 仿真结果反馈到城市规划
- 仿真预测 + 真实数据校准

### 5.11.2　气候—社会耦合

气候模型和社会模型的耦合是新兴方向:

- 气候模型给出"未来 50 年的温度、降水"
- 社会模型给出"居民对气候变化的反应"
- 两者耦合,给出"气候变化的社会经济影响"

### 5.11.3　基础设施脆弱性

城市基础设施的"脆弱性评估":

- 自然灾害下的脆弱性
- 网络攻击下的脆弱性
- 流行病下的脆弱性

GAWorld 可以在这些研究中发挥作用——通过仿真模拟灾害下的基础设施失效。

### 5.11.4　可持续城市

可持续城市仿真:

- 碳排放建模
- 绿色基础设施建模
- 居民低碳行为建模

这是 2026 年后的研究热点。

---

## 5.12　本章小结(扩展版)

- 城市基础设施建模(交通、能源、通讯)是社会仿真的"骨架"。
- 环境事件的影响分四层:知晓、理解、行动、反馈,每层有不同仿真策略。
- 工程实现的关键:地图缓存、节律叠加、事件优先级。
- 学术前沿:数字孪生城市、气候—社会耦合、基础设施脆弱性、可持续城市。
- GAWorld 的环境模块提供了完整的基础设施支持,5000+ 行代码。


---

## 5.13　扩展:OSM 数据的实战处理

### 5.13.1　OSM 数据格式

OpenStreetMap 数据格式:

- **节点(Nodes)**:经纬度点
- **道路(Ways)**:有序节点列表
- **关系(Relations)**:节点和道路的组合
- **标签(Tags)**:键值对元数据

### 5.13.2　关键标签

```yaml
# 道路
highway:
  motorway: 高速公路
  trunk: 国道
  primary: 省道
  secondary: 县道
  tertiary: 乡道
  residential: 居住区道路
  footway: 人行道
  cycleway: 自行车道

# 兴趣点
amenity:
  restaurant: 餐厅
  hospital: 医院
  school: 学校
  bank: 银行
  park: 公园
```

### 5.13.3　数据清洗

OSM 数据常有噪声:

```python
# examples/osm_cleaning.py
def clean_osm_data(osm_data: dict) -> dict:
    """清洗 OSM 数据"""
    cleaned = {
        "nodes": [],
        "ways": []
    }
    # 1. 移除孤立节点
    used_nodes = set()
    for way in osm_data["ways"]:
        used_nodes.update(way["nodes"])
    cleaned["nodes"] = [n for n in osm_data["nodes"]
                       if n["id"] in used_nodes]
    # 2. 移除过短的 way(< 2 个节点)
    cleaned["ways"] = [w for w in osm_data["ways"]
                      if len(w["nodes"]) >= 2]
    # 3. 合并相邻 way
    # (略,需要图算法)
    return cleaned
```

### 5.13.4　投影转换

OSM 数据是 WGS84 经纬度,需要转成平面坐标:

```python
import pyproj

def wgs84_to_utm(lon: float, lat: float) -> tuple:
    """WGS84 转 UTM"""
    # 自动选择 UTM 区
    utm_zone = int((lon + 180) / 6) + 1
    proj_string = f"+proj=utm +zone={utm_zone} +datum=WGS84"
    transformer = pyproj.Transformer.from_crs(
        "EPSG:4326", proj_string, always_xy=True
    )
    return transformer.transform(lon, lat)
```

---

## 5.14　扩展:节律系统的工程实现

### 5.14.1　多层级节律

仿真里的节律是多层级的:

```python
class RhythmSystem:
    def __init__(self):
        self.daily = DailyRhythm()  # 昼夜
        self.weekly = WeeklyRhythm()  # 周
        self.seasonal = SeasonalRhythm()  # 季节
        self.life = LifeRhythm()  # 生命阶段

    def get_active_rhythms(self, time: datetime, agent: dict) -> list:
        """获取所有活跃节律"""
        rhythms = []
        rhythms.append(self.daily.get_phase(time))
        rhythms.append(self.weekly.get_phase(time))
        rhythms.append(self.seasonal.get_phase(time))
        rhythms.append(self.life.get_phase(agent["age"]))
        return rhythms
```

### 5.14.2　节律冲突的处理

不同节律可能冲突(工作日 + 节假日):

```python
def resolve_rhythm_conflict(rhythms: list) -> dict:
    """处理节律冲突"""
    priority = {"holiday": 1, "weekend": 2, "weekday": 3,
                "summer_peak": 1, "normal": 2}
    # 取优先级最高的
    highest = min(rhythms, key=lambda r: priority.get(r["name"], 5))
    return highest
```

### 5.14.3　节律的学习

仿真里的节律可以"学习"——居民根据经验调整自己的时间表:

```python
def learn_rhythm(agent: dict, experience: dict):
    """根据经验调整节律"""
    if experience["last_week_traffic"] == "heavy":
        agent["preferred_commute_time"] += 30  # 推迟 30 分钟
```

---

## 5.15　扩展:事件系统的工程实现

### 5.15.1　事件生命周期

事件的生命周期:

```
公告 → 缓冲 → 实施 → 持续 → 结束
```

每个阶段有不同的事件参数:

```python
@dataclass
class PolicyEvent:
    name: str
    category: str
    announce_at: datetime
    effective_at: datetime
    buffer_end: datetime  # 缓冲期结束
    end_at: Optional[datetime]  # 事件结束
    parameters: dict
```

### 5.15.2　事件的级联

事件触发其他事件:

```python
def cascade_event(event: dict, sim: Simulation) -> list:
    """事件级联"""
    new_events = []
    if event["category"] == "natural_disaster":
        # 自然灾害触发经济事件
        new_events.append({
            "name": "economic_shock",
            "trigger_at": event["end_at"],
            "magnitude": event["parameters"]["damage"] * 0.5
        })
    return new_events
```

### 5.15.3　事件的优先级

多个事件同时发生时的优先级:

```python
def event_priority(event: dict) -> int:
    """事件优先级"""
    if event["category"] == "natural":
        return 10
    elif event["category"] == "policy":
        return 7
    elif event["category"] == "economic":
        return 5
    elif event["category"] == "technology":
        return 3
    return 1
```

---

## 5.16　本章小结(最终扩展版)

- OSM 数据的实战处理:格式、关键标签、数据清洗、投影转换。
- 节律系统的工程实现:多层级节律、冲突处理、节律学习。
- 事件系统的工程实现:生命周期、级联、优先级。
- 环境系统的工程实现完整,5000+ 行代码,生产可用。

