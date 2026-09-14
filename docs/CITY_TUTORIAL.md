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

## 4. 切换当前城市

```bash
python -m gaworld.city use 绍兴柯桥      # 写 dashboard_config.json 的 "city"
python -m gaworld.city use --clear 绍兴柯桥   # 恢复默认世界
```

选中后，这些配置项整体指向该城市包：

| 配置项 | 来自 |
|---|---|
| `map_mode` / `map_path` / `real_map_path` | 城市包（有 `map.geojson` 才是 `real`） |
| `csv_path` / `md_path` | 城市包（有人口才写入） |
| `environment` / `external_environment` | `environment.json` |
| `background` | `environment.json` |

**优先级**：`dashboard_config.json` → 全局 `data/environment_config.json` → **城市包** → `GAWORLD_CONFIG_OVERRIDES`。

城市排在全局环境文件**之后**是刻意的：那个文件是默认值，不是针对某座城的意图。
否则一座大陆性气候的城市会继承全局文件里的亚热带事件。
而 `GAWORLD_CONFIG_OVERRIDES` 仍然最后生效，保留了逃生舱。

> 配置里写了一座已被删除的城市不会让仿真起不来——解析失败就退回默认世界。

---

## 5. 城市包的目录结构

```
data/cities/<slug>/
├── city.json                 清单：地名、坐标、bbox、规模、地图模式、人口数、操作history
├── citymap.md                程序化地图（始终存在：兜底 + 提示词上下文）
├── map.geojson               真实 OSM 地图（抓取成功才有）
├── environment.json          环境事件 + background
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

**右栏**（选中城市后出现）：详情（坐标、地图来源、来源、行政区）、
「用这座城市运行」/「删除城市」、以及三个加 agent 的表单。

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
python -m gaworld.city use <city> [--clear]
python -m gaworld.city delete <city> --yes
```

---

## 8. API 速查

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/city` | 城市列表 + 当前选中 + 可选规模/模板 |
| GET | `/api/city/detail?city=<slug>` | 单座城市详情（含行政区、history、解析出的路径） |
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
