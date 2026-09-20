# 城市教程（Cities）

> 给一个地名，造一座能跑仿真的城。
>
> 面板：控制台「**城市**」页签｜引擎：`gaworld/city/`｜后端：`gaworld/apps/city_api.py`
> CLI：`python -m gaworld.city create "绍兴柯桥"`

---

## 目录

- [0. 这是什么，什么时候该用](#0-这是什么什么时候该用)
- [1. 五分钟跑通](#1-五分钟跑通)
- [2. 造城这条流水线](#2-造城这条流水线)
- [3. 往城里加智能体的三条路](#3-往城里加智能体的三条路)
- [3.5 城市知识库：让城市影响居民](#35-城市知识库让城市影响居民)
- [4. 切换当前城市](#4-切换当前城市)
- [5. 城市包的目录结构](#5-城市包的目录结构)
- [6. 面板导览](#6-面板导览)
- [7. CLI 速查](#7-cli-速查)
- [8. API 速查](#8-api-速查)
- [9. 设计取舍](#9-设计取舍)
- [10. 常见问题](#10-常见问题)

---

## 0. 这是什么，什么时候该用

在这个功能之前，GAWorld 只有**一座**城：`data/citymap.md` 加 `data/hangzhou_*` 那套人口，
全局单值。想换个地方，得手改配置里的三条路径，且改完就回不去了。
`scripts/generate_citymap.py` 能生成地图，但它**忽略你给的地名**（从固定词池随机取名），
而且只会就地覆盖那一个文件。

这个功能把「一座城市」变成了**一等公民**：

| | 旧的 `generate_citymap.py` | `gaworld.city` |
|---|---|---|
| 用真实地名 | ❌ 只读描述里的规模词，名字随机 | ✅ 地名就是城市名 |
| 真实地理 | ❌ | ✅ Nominatim 地理编码 + Overpass 真实 OSM 路网/POI/地铁/河流 |
| 多城市共存 | ❌ 覆盖同一个文件 | ✅ `data/cities/<slug>/` 各自独立 |
| 带环境 | ❌ 只有地图 | ✅ 按纬度定气候、按规模定社会事件、自动写 background 提示词 |
| 带人口 | ❌ | ✅ 复用 `gaworld.population`，住所落在该城真实存在的行政区上 |
| 切换 | 手改 config | `use <city>` 一条命令 |

**什么时候用哪个：** 只想随手换张地图、不在乎它对应哪里 → 旧脚本够用。
想让仿真发生在**某个具体的地方**、或者需要同时维护多座城市做对比 → 用这个。

---

## 1. 五分钟跑通

```bash
# 联网：地理编码 + 抓真实 OSM 路网，顺便生成 200 名居民
python -m gaworld.city create "绍兴柯桥" --size 200

# 让仿真用这座城
python -m gaworld.city use 绍兴柯桥

# 照常跑
python generative_city_sim.py run --sim-days 7
```

没有网络、或者地名是虚构的：

```bash
python -m gaworld.city create "柳溪村" --offline --scale tiny --size 100
```

`--offline` 跳过一切联网查询，完全按地名**确定性**地程序化生成——
同一个地名永远得到同一座城，适合写测试和复现实验。

---

## 2. 造城这条流水线

每一层都能降级，因为「没有网络」和「这个村子 OSM 上没有」都必须仍然给你一座能跑的城：

```
地名
 ├─ 地理编码（Nominatim）───────失败──→ 合成地点记录（offline_place）
 ├─ 真实地图（Overpass / OSM）──失败──→ 只用程序化地图
 ├─ 程序化地图  ← 始终生成
 ├─ 环境配置
 └─ city.json 清单
```

### 2.1 地理编码决定了「这是多大的地方」

Nominatim 返回的 `addresstype`（`village` / `town` / `city` / `province`…）映射成五档规模，
查不到就退回按 `population` 标签猜，再查不到就是 `medium`。规模同时决定了：

- 程序化地图的枢纽数量、以及**有没有地铁**（`tiny`/`small` 没有）
- 环境里社会事件的措辞（村里是「集市开集」，大城市才有「地铁运营延误」）
- bbox 的上限（见下）

`--scale` 可以覆盖这个判断。

### 2.2 bbox 会按规模收敛

行政区的官方 bbox 常常比你想要的「一座城」大得多。柯桥区的原始 bbox 跨 66 km，
抓下来会把隔壁诸暨的枫桥镇、店口镇一并拉进来，居民通勤 70 km。
所以 bbox 按规模收敛到 `2 × SCALE_BBOX_HALF_DEG`，柯桥区收到 28.9 km，
抓到的全是兰亭街道、漓渚镇、福全街道这些真正属于柯桥的地方。

### 2.3 程序化地图始终会生成

即使真实地图抓成功了，`citymap.md` 也一定会写。两个原因：
它是**兜底**（`map.geojson` 被删掉后城市仍然能跑），
也是给 LLM 看的**提示词上下文**。

程序化地图的枢纽名保持英文结构名（`Central Block`、`Riverside Park`），
因为 `infer_category` 是按英文关键词给未声明分类的节点归类的，
已提交的 `data/citymap.md` 也是这个约定。只有城市本身和河流带真实地名。

### 2.4 环境按纬度和规模推导

气候取自 `|lat|`（热带 / 亚热带 / 温带 / 大陆性 / 极地），
决定自然事件池——同一套代码，三亚出「台风外围环流」，诺里尔斯克出「暴风雪预警」。

**这里有个容易忽略但很要紧的点**：`background` 提示词也会被改写。
默认的 background 写着「中国·杭州」，不换掉的话，
新城市里的智能体会一边住在柯桥、一边以为自己在杭州。

---

## 3. 往城里加智能体的三条路

三者都写成仿真器**原生可读**的 `agents.csv` + `profiles.md`，不需要任何转换层。

### 3.1 批量合成居民

```bash
python -m gaworld.city add-agents 绍兴柯桥 --size 200 --preset cn_county_town
```

复用 `gaworld.population` 的完整管线（IPF 采样、家庭、工作单位、社交图），
但把 `geography.district_weights` 换成**这座城市真实存在的行政区**，
所以居民的住所写出来是「兰亭街道·自住房」而不是「余杭·商品房」。

默认**追加**；`--replace` 才是替换。注意追加的一批有自己的家庭和社交图，
不会和先前那批织在一起——要整座城互相连通，就一次生成完。

> `size` 会被 `normalize_spec` 收敛到 20–5000（IPF 需要足够样本才稳定）。
> 要了 5 个人会得到 20 个，CLI 和面板都会把这件事说出来，不会闷声改掉。

### 3.2 追加单个 agent

```bash
python -m gaworld.city add-agent 绍兴柯桥 --name 林素 --age 34 --job "社区医生"
```

不给 `--residence` 就从该城行政区里随机挑一个。

### 3.3 把已有 agent 迁进来

```bash
python -m gaworld.city migrate 绍兴柯桥 --agent-id 31                # 从默认语料
python -m gaworld.city migrate 绍兴柯桥 --agent-id 5 --from-city 柳溪村  # 从另一座城
```

保留状态变量和人物小传，但**重新分配住所**，否则档案会继续自称住在原来的城市。
`--keep-residence` 可以关掉重新分配。

> 住所重写用的是 `parse_profile` 同款正则，不是字面替换：
> 手写语料写的是「居住西湖区。」，生成语料写的是「居住于余杭·商品房。」，
> 字面替换两种都匹配不上。

### 3.4 住所只是叙事，落点是运行时算的

agent 具体住哪个节点、在哪上班，是 `gaworld/sim/_location.py` 的
`assign_agent_locations` 在仿真启动时从地图节点里挑的。
CSV 里的 `residence` 列只进人物小传（「居住于X」），
所以迁城时真正要跟着变的只有「它提到的行政区名」。

---

## 3.5 城市知识库：让城市影响居民

地图决定居民**在哪**，知识库决定这里**是个什么样的地方**——什么产业、在发展什么、缺什么人。
没有它，柯桥和鹤岗的居民除了地名不同，活得一模一样。

### 3.5.1 产业名是自由文本，不绑定六分类

`JOB_INDUSTRY_MAP` 只有 tech/finance/medical/education/service/trade 六类，**没有旅游业**。
知识库里存的是**当地真实叫法**（「纺织业」「跨境电商」「全域旅游」），
只有在需要落到经济模块时才由 `industry_mix()` 映射到最近的一类。

这是刻意的：一座城的性格恰恰活在六分类抹掉的那些区别里——
把旅游业和物流、零售一起压成 `service`，就把我们特意去查来的东西丢掉了。
提示词通道和技能通道用的都是真名。

### 3.5.2 来源分三层，越往下越保守

```
联网搜索 + LLM 结构化 ──失败──▶ OSM 地图统计 ──太稀疏──▶ 空画像（什么都不声称）
```

**LLM 被明确禁止用常识补全**：提示词里写着「不要凭常识补充或推测；搜索结果没提到的就不要写」。
对真实城市，一句自信的「柯桥以旅游业为主」会被下游四个通道全部当成事实，
比空画像坏得多。

**地图兜底也有门槛。** OSM 节点数量衡量的是**标注密度**，不是就业。
绍兴的地图包里只有 55 个住宅区 + 22 所学校，直接按比例算会得出「教育业 100%」——
这是把标注密度伪装成经济结论。所以要求至少 **2 个不同产业类别、6 个节点**，
不够就返回空画像，四个通道全部保持静默，仿真回到没有这个功能时的行为。

### 3.5.3 四条影响通道

| 通道 | 作用点 | 效果 |
|---|---|---|
| **提示词** | `background` → 认知/日程/目标 | 居民知道自己住在什么样的城市 |
| **技能成长** | `derive_growth_profile` + `evolve_growth_profile` | 旅游城市的居民更可能去学导游、酒店管理 |
| **就业收入** | `economy.macro.industry_conditions` | 本地主导且增长的行业收入系数更高 |
| **城市级 RAG** | 每位居民的 `external_info` | 城市事实可被检索，与个人外部信息一起参与排序 |

**技能通道有个必须记住的细节**：`profile_signature` 是成长画像的缓存键。
加入城市影响后城市签名**必须并进这个键**，否则同一个居民在纺织城和旅游城
会共用一份缓存，第二座城的影响永远不会出现。

**就业通道没有改经济模块一行代码**：`industry_conditions` 本来就从配置读，
城市包只是提供了一个配置覆盖。

**职业动机和社交传染是分开的两条路径**：因为政府推旅游而去学导游，
是一次**职业**决策（`kind=skill`、`category=职业`、`career_link=True`），
不是从朋友那里染上的爱好。默认采纳概率是社交传染的一半
（`adopt_chance × opportunity_factor`）——城市经济是按月推着人走的，不会一夜换岗。

### 3.5.4 运行时新闻：两个时钟

仿真 365 天可能一下午就跑完。「每个仿真日拉一次今天的新闻」等于在新闻根本没变的
同一个真实下午里发 365 次搜索。所以：

- **抓取**按**真实时间**门控（`city_news.ttl_hours`，默认 6 小时）——跑多快都只抓一次
- **投喂**按**仿真时间**轮转——每个仿真日取缓存里不同的一小片，长跑不会天天同一条头条

实测：365 个仿真日在同一个 TTL 窗口内 = **2 次搜索**（两条查询各一次）。
网络断了也不会每个仿真日重试——时间戳照常更新，窗口照常推进。

```bash
python -m gaworld.city knowledge 绍兴柯桥               # 看
python -m gaworld.city knowledge 绍兴柯桥 --rebuild     # 联网重建
python -m gaworld.city knowledge 绍兴柯桥 --rebuild --offline  # 只用地图估算
python -m gaworld.city news 绍兴柯桥 --refresh          # 过期才抓
python -m gaworld.city news 绍兴柯桥 --force            # 强制抓
```

面板上在「城市地图」下方，三个按钮对应同样的三件事。

---

## 4. 切换当前城市

三个入口，写的是同一个开关（`dashboard_config.json` 的 `"city"`）：

```bash
python -m gaworld.city use 绍兴柯桥      # CLI
python -m gaworld.city use --clear 绍兴柯桥   # 恢复默认世界
```

- **控制台「城市」页签** → 选中城市后点「用这座城市运行」
- **控制台主面板的「城市」下拉**（运行控件第一项）→ 直接选好再点「运行仿真」

下拉里每项显示 `城市名 · N 人 · 真实地图/程序化`。**没有居民的城市是禁选的**——
它跑不起来，与其让你选完再被服务端拒绝，不如一开始就不给选。

### Agent IDs 是按城市各自编号的

这是最容易踩的一脚：编号在每座城市都从 1 开始。
配置里留着 `agent_ids: [37]` 再切到一座只有 30 人的城，
`build_agent` 会对空结果取 `.iloc[0]`，几分钟后在运行日志里抛一个光秃秃的
pandas `IndexError`——那时你早就不看了。

所以运行前会**先拦下来**：

```
城市「梅湾村」只有 30 位居民，但 Agent IDs 里有 [37]。请改成 1–30 之间的编号。
```

下拉旁边的 Agent IDs 输入框也会跟着把 placeholder 改成当前城市的实际范围（`1-30`）。

选中后，这些配置项整体指向该城市包：

| 配置项 | 来自 |
|---|---|
| `map_mode` / `map_path` / `real_map_path` | 城市包（有 `map.geojson` 才是 `real`） |
| `csv_path` / `md_path` | 城市包（有人口才写入） |
| `environment` / `external_environment` | `environment.json` |
| `background` | `environment.json` |
| `memory_dir` / `log_dir` / 另外 13 个运行期目录 | 该城市的**运行根目录**（见下） |

**优先级**：`dashboard_config.json` → 全局 `data/environment_config.json` → **城市包** → `GAWORLD_CONFIG_OVERRIDES`。

城市排在全局环境文件**之后**是刻意的：那个文件是默认值，不是针对某座城的意图。
否则一座大陆性气候的城市会继承全局文件里的亚热带事件。
而 `GAWORLD_CONFIG_OVERRIDES` 仍然最后生效，保留了逃生舱。

> 配置里写了一座已被删除的城市不会让仿真起不来——解析失败就退回默认世界。

### 每座城市有自己的运行根目录

选中城市后，**整棵运行树**从 `output/` 挪到 `output/cities/<slug>/`：

```
output/cities/<slug>/
├── memory/          记忆、sim_state.json（世界时钟）、向量库、目标、关系、经济状态
├── logs/            每个 agent 的运行日志
├── diaries/         日记
├── state/           状态曲线 CSV      ├── economy/       经济账本
├── visualization/   轨迹 trace        ├── network/       社交网络图
├── environment/     环境事件时间线    ├── life_events/   生活事件
├── intervention/ ├── work/ ├── collaboration/ ├── twin/ ├── imported_agents/
```

这件事是必须的，不是整理癖：记忆和日志只按 **agent id** 命名，`sim_state.json`
里也只有**一个**世界时钟。共用一棵树意味着 A 城的 1 号和 B 城的 1 号是同一份
`agent_1.json`、同一本日历——换城市不是换世界，是让新居民继承上一座城的人生。

几点需要知道的：

- **没选城市时一切照旧**，还是 `output/memory`、`output/logs`。旧数据不动。
- 目录名与默认 `output/` 树**逐项对齐**：Analytics 是把 `state/`、`economy/`
  拼到运行根目录上读的，回放页是靠 glob `output/*/visualization` 找 trace 的。
- 运行根目录放在 `output/` 而**不是**城市包里，因为城市包是这座城的*定义*，
  应当能直接拷给别人，不该捎带某个人二十年的记忆。
- **删城市会连带删掉它的运行目录**。否则重建一座同名的城，
  新居民会直接继承被删那座城的记忆和世界时钟。
- 映射表在 `gaworld/city/config.py` 的 `RUN_PATHS`。

> 相关：从没跑过的 agent 从开局日期起算，而不是接着别的 agent 的天数跑
> （`sim_state.json` 里按 agent 记录的 `agent_last_day`）。

---

## 5. 城市包的目录结构

```
data/cities/<slug>/
├── city.json                 清单：地名、坐标、bbox、规模、地图模式、人口数、操作history
├── citymap.md                程序化地图（始终存在：兜底 + 提示词上下文）
├── map.geojson               真实 OSM 地图（抓取成功才有）
├── environment.json          环境事件 + background
├── knowledge.json            城市画像（产业、发展重点、紧缺岗位、来源链接）
├── news.json                 本地新闻缓存（按真实时间刷新）
├── agents.csv                人口状态（utf-8-sig，仿真器契约）
├── profiles.md               人物小传
└── population_manifest.json  人口生成的可复现记录
```

注册表是**目录扫描**，不是索引文件——索引会在有人手工拷贝或删除文件夹时悄悄和现实脱节。
清单坏掉的目录会被跳过，不会让整个注册表不可用。

### `city.json` 里的投影锚点

真实地图包的 `meta.origin` 记着这座城自己的投影锚点：

```json
{"lat": 30.084796, "lng": 120.490807, "lat_per_km": 0.009009009, "lng_per_km": 0.010381686}
```

地图层的内置常量是按杭州（约 30°N）标定的，一个经度约 96 km。
换到别的纬度，经度度数会随 `cos(lat)` 收缩——巴黎（48.86°N）用杭州常量算东西向距离会**偏大 31%**。
带锚点后误差归零。没有 `meta.origin` 的包（比如已提交的 `data/hangzhou_real.geojson`）行为完全不变。

---

## 6. 面板导览

控制台「**城市**」页签 → `http://127.0.0.1:8766/site/dashboard/city.html`

**左栏**：新建城市表单（地名 / 规模 / 初始人口 / 人口模板 / 随机种子 / 离线开关），
下面是城市列表，每项显示地图来源（真实 / 程序化）、规模、智能体数，
当前运行中的那座带「运行中」标记。

**左栏中部**（选中城市后出现）：**城市地图**预览。滚轮缩放、拖拽平移、双击复位。
用的是控制台地图面板和仿真回放同一个渲染器（`site/dashboard/citymap-view.js`），
所以这里看到的和它跑起来时是同一张图。下方一行标注地图来源、地点数、道路数、河流、地铁。

预览**永远显示这座城实际会用的那张图**——有真实 OSM 包就是真实图，没有就是程序化图，
不会出现"预览一张、跑另一张"。地图在服务端按 `(路径, mtime)` 缓存，
重新生成城市会自动失效。

**右栏**（选中城市后出现）：详情（坐标、地图来源、来源、行政区）、
「用这座城市运行」/「删除城市」、以及三个加 agent 的表单。

> 地图放在**宽的左栏**而不是详情面板旁边：380px 的侧栏里一座 174 个地点的城糊成一团。

联网创建要 20–60 秒（取决于 Overpass 镜像状态），表单期间会禁用并显示进度文案。

---

## 7. CLI 速查

```bash
python -m gaworld.city create <地名> [--slug S] [--scale tiny|small|medium|large|metro]
                                     [--offline] [--force] [--seed N]
                                     [--size N] [--preset P]
python -m gaworld.city list [--json]
python -m gaworld.city show <city>
python -m gaworld.city add-agents <city> --size N [--preset P] [--seed N] [--replace]
python -m gaworld.city add-agent  <city> --name N --age A [--gender] [--job]
                                         [--hukou] [--education] [--income] [--residence]
python -m gaworld.city migrate <city> --agent-id N [--from-city C | --from-csv F --from-md F]
                                      [--keep-residence]
python -m gaworld.city knowledge <city> [--rebuild] [--offline]
python -m gaworld.city news <city> [--refresh] [--force] [--ttl-hours H]
python -m gaworld.city use <city> [--clear]
python -m gaworld.city delete <city> --yes
```

---

## 8. API 速查

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/city` | 城市列表 + 当前选中 + 可选规模/模板 |
| GET | `/api/city/detail?city=<slug>` | 单座城市详情（含行政区、history、解析出的路径） |
| GET | `/api/city/map?city=<slug>` | 地图渲染数据（tile_map + 节点 + 路网 + 河流 + 地铁），按 mtime 缓存 |
| GET | `/api/city/knowledge?city=<slug>` | 城市画像 + 四条通道各自的实际产出 |
| POST | `/api/city/knowledge` | `{city, offline?}` 重建画像 |
| GET | `/api/city/news?city=<slug>` | 新闻缓存 |
| POST | `/api/city/news` | `{city, force?, ttl_hours?}` 刷新新闻 |
| GET | `/api/config` | 含 `city`（当前）与 `cities`（可选列表，带人数与地图模式） |
| POST | `/api/run/start` | `config.city` 指定这次运行在哪座城；未知 slug 或 Agent IDs 越界返回 400 |
| POST | `/api/city/create` | `{name, scale?, offline?, force?, seed?, size?, preset?}` |
| POST | `/api/city/population` | `{city, size, preset?, seed?, replace?}` |
| POST | `/api/city/agent` | `{city, name, age, gender?, job?, ...}` |
| POST | `/api/city/migrate` | `{city, agent_id, from_city?, rehome?}` |
| POST | `/api/city/select` | `{city}` 或 `{clear: true}` |
| POST | `/api/city/delete` | `{city}` |

Python：

```python
from gaworld.city import create_city, add_population, add_agent, migrate_agent, resolve_city

city = create_city("绍兴柯桥", size=None, offline=False)
add_population(city, size=200, preset="cn_county_town", seed=42)
add_agent(city, name="林素", age=34, job="社区医生")
```

---

## 9. 设计取舍

**为什么非 ASCII 地名的 slug 保留原字符。** 没有不引依赖就能做的音译，
退回哈希会让 `data/cities/` 变成一堆乱码目录名。`绍兴柯桥` 直接当目录名，人能读。

**为什么抓取有 deadline。** `urlopen` 的 timeout 是**每次 socket 操作**的，
一个慢速返回的镜像能远远跑过它。公共 Overpass 镜像经常一个个地被墙或过载，
逐个分类重新轮询死镜像会让一次建城拖到几十分钟。
所以：粘住已知可用的镜像 + 整体 wall-clock 预算，超了就降级到程序化地图——
「造城」是交互操作，等 20 分钟比拿一张生成的地图更糟。

**为什么真实地图没河就是没河。** 地图层原先在 OSM 包里找不到河流时会退回示例的钱塘江，
于是绍兴（OSM 包里 0 条河）被画上 2794 个水面 tile（占 16%）和 **15 座凭空的桥**——
水面挡路、桥影响路网判定，提示词还告诉 LLM 这座城有条它从来没有的河。
现在真实地图的"没找到"就是"没有"；虚拟地图保留默认（那本来就是编的）。

**为什么用 `@` 指令的地图不再继承默认地铁。** 地图层原本在没有 `@metro` 时回退到
示例线路，于是一个村庄会凭空长出地铁，进而污染 `choose_transport_mode` 和票价。
现在：用了 `@` 指令的地图就是在明确声明自己的交通，没写就是真没有；
完全没有 `@` 指令的旧地图仍然吃默认值（两个已提交地图行为逐字节不变）。

---

## 10. 常见问题

**Q：建城卡了很久。**
A：多半是 Overpass 镜像不通。日志里会打 `overpass error via <url>`。
整体有 240 秒预算，超了会自动降级成程序化地图。急的话直接 `--offline`。

**Q：抓到的节点太少。**
A：少于 8 个就判定为「太稀疏，撑不起一张真实地图」并降级。
小村庄这是正常的——`--offline` 的程序化地图反而更像个能住人的地方。

**Q：一次建城被 Ctrl-C 打断了，再建说已存在。**
A：不会。没有 `city.json` 的目录会被当作上次中断的残骸直接覆盖，
不需要 `--force`。只有**完整**的城市才要 `--force`。

**Q：改了城市但仿真还是老地图。**
A：`use` 是写配置，**下次运行生效**。已经在跑的进程不会中途换地图。

**Q：能把城市包提交进版本库吗？**
A：可以，它就是一堆文本文件。`data/cities/` 没有进 `.gitignore`，
自己决定要不要跟踪——人口多的城市 `profiles.md` 会比较大。

---

## 相关文档

- [地图模式](MAP_MODES.md) — virtual / real 两种地图的底层差异与包格式
- [功能特性总览](FEATURES.md)
- [参数化人口合成](../gaworld/population/__main__.py) — `python -m gaworld.population --help`
