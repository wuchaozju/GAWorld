# 居民的外部信息源：新闻 · 社交媒体 · 专业网站 · 搜索

日期：2026-09-19
状态：已实现（本提案随代码一起落地）
范围：新增 `gaworld/infosources/`（schema / registry / channels / feed / diet / search / plugin / CLI）+ `data/info_sources.json`；改 `gaworld/sim/_news.py`（feed 模式、新搜索引擎、源清单正则修复、首页缓存 TTL）、`gaworld/settings/behavior.py`（`news.sources`、`news.cache_ttl_hours`、`info_seek.engines` / `search_api`）、`gaworld/settings/config_docs.py`、`gaworld/plugins/__init__.py`（注册插件）。
**`generative_city_sim.py` 零改动。**

---

## 一、现状核查（全仓 grep，非推测）

| 事实 | 位置 |
|---|---|
| 居民读外界的唯一入口是一份扁平 URL 清单，13 个条目全是**首页**（BBC / CNN / NYT / reddit.com / x.com …） | `data/news_source.md` |
| `load_news_sources` 的两个正则在 raw string 里写成 `[^\\s)]`，排除的是字母 `s` 而不是空白：`https://news.baidu.com/` 被读成 `https://new`，其它行一路读到下一行 | `gaworld/sim/_news.py:112-113`（修前） |
| 于是缓存里只有两条垃圾：`"https://www.reddit.com/\nhttp"` → `"Reddit"`，`"https://x.com/\nhttp"` → `"JavaScript is not available"` | `data/news_cache.json` |
| 首页缓存每次启动都重抓，没有真实时间门 | `update_news_cache`（修前） |
| 搜索 = 正则爬 Google / Baidu / Bing 结果页；Google 对裸 `requests` 返回同意页，Baidu 给跳转链接 | `_news.web_search` / `_extract_*_results` |
| 社交媒体只有 X 的 MCP（要 Token） | `gaworld/io/x_mcp.py` |
| 「偏好站点」是对上面那份清单按域名打分，人人一样的一袋子 | `_build_agent_preferred_sites` |
| 城市层已经做对了一件事：本地新闻**按真实时间抓、按仿真时间发** | `gaworld/city/news.py` |

结论：不是「信息源不够多」，而是这条链路从清单加载就断了；「专业领域」和「社交媒体」在结构上不存在——没有「这是什么类型的源」「谁会读它」这两个概念。

## 二、设计

### 2.1 三个新概念

```
Source   一个可读的地方：id / name / kind / channel / url / topics / lang / weight
         kind    = news | social | professional   （居民自己会怎么说：看新闻 / 刷微博 / 读行业站）
         channel = rss | reddit | hackernews | weibo_hot | baidu_hot | bilibili_popular | page
                   （怎么抓、怎么解析；跟 kind 正交——V2EX 是 rss 渠道的 social 源）
         topics  = 科技 / 医疗 / 财经 / 教育 / 热点 / 综合 …（用于匹配职业与兴趣）
InfoItem 那里发布的一条东西：title / url / excerpt / published_at / fetched_at
Diet     一位居民的「信息食谱」：[{source_id, weight, reason}]，权重归一
```

### 2.2 数据流

```
data/info_sources.json ──load_registry──▶ list[Source]
                                             │
   真实时间 TTL（默认 6h）    feed.refresh ◀──┘  fetch_source（GuardedSession：限速 / UA 轮换 / 失败缓存）
                                             ▼
                              output/infosources/feed.json   ←  FeedCache{source_id: [InfoItem]}
                                             │
agents.built / on_day_start   build_media_diet(agent, registry)  →  agent["ext"]["infosources"]["diet"]
                                             │                       output/infosources/diets.json
                                             ▼
info_seek_and_store → _choose_info_target → _feed_target（feed_visit_ratio 掷骰）
                          │ 命中：按食谱权重抽源 → 源内按兴趣词 + 新鲜度挑一条 → 摘要太短就抓正文
                          │ 未命中：老路（首页缓存 → site: 搜索）
                          ▼
   记忆条目多一行  渠道：专业网站 · WHO News    反应提示词写明「浏览自己常看的信息源」
```

**两个时钟的处理跟 `city/news.py` 一致**：抓取按真实小时门控，一个源一个窗口最多抓一次；仿真跑多快都不会把 RSS 抓穿。空抓也盖 `last_fetch` 戳，死掉的源每个窗口只试一次。

### 2.3 信息食谱怎么分

确定性，零 token。对注册表里每个源打分：

| 项 | 规则 | 为什么 |
|---|---|---|
| 基线 0.15 | 谁都可能偶然撞见任何东西 | 不让食谱变成硬过滤 |
| 职业匹配 +1.0/标签 | 职业关键词表 → 领域标签，与 `topics` 求交 | 「专业网站」的定义就是这条：社区医生分到 WHO / STAT，程序员分到 HN / arXiv |
| 主流触达 +0.35/标签（上限 2） | `综合 / 热点 / 社会 / 本地` | 澎湃、微博热搜进所有人的食谱 |
| 兴趣 +0.5/命中（上限 3） | profile 提取的兴趣词 ↔ 标签字面 / 别名表（股票→投资、健身→体育…）/ 站名 | 跟职业不对口但爱看的东西 |
| social 乘 `0.6 + 0.8·platform_dependence` | 状态变量 | 平台依赖高的人刷得多，是已有的九维状态之一 |
| professional 乘 `0.8 + 0.4·openness` | 大五开放性（`rules` 通道） | 不对口又没兴趣命中的行业站再乘 0.6 |
| 外语 乘 `en_weight·(1 + 0.4·z_o)`（夹在 0.1–1） | 默认 0.5 | 开放性把食谱拓向外语源 |
| 无命中 +0.1·max(0, z_o) | | 开放性拓向不对口的源 |

取前 `max_sources`（默认 8）归一。同一个人、同一份注册表 → 同一份食谱；随机只发生在每次检索抽哪一条。无大五记录的居民得到中性开放性，与加入前行为一致。

### 2.4 搜索引擎

`web_search` 的引擎链加了三个结构化提供方，形状与 `x` 引擎完全相同（返回 `[{url,title,snippet}]`，没配就 `[]` 静默落到下一个）：

| 引擎 | 密钥 | 说明 |
|---|---|---|
| `ddg` | 无 | DuckDuckGo HTML 端点，对裸客户端友好，标记稳定 |
| `brave` | `BRAVE_SEARCH_API_KEY` | JSON，免费额度充足 |
| `tavily` | `TAVILY_API_KEY` | JSON，带正文，常可免抓页 |

默认顺序 `x → ddg → brave → tavily → baidu → google → bing`：爬结果页的三个退到兜底。

## 三、接入点（主循环零改动）

- **`InfoSourcesPlugin`**（id `infosources`，注册在 `BigFivePlugin` 之后、`InterventionPlugin` 之前）：
  `agents.built` 读注册表 + TTL 刷新 + 建食谱（此时大五已播种，且早于模拟器自己的 RAG bootstrap）；
  `on_day_start` 再刷新（TTL 门控，通常无网络）+ 重建食谱（`platform_dependence` 会漂、职业会换）；
  `on_simulation_end` 清掉运行时持有者。
- **`_news` 读不到 `SimContext`**，所以 feed 走进程级持有者 `feed.runtime()`（与 `http_guard.get_default_session()` 同一模式），食谱走 `agent["ext"]["infosources"]["diet"]`（`diet.diet_of`）。模拟器三处 `_choose_info_target` 调用点一行不改。
- 食谱里的新闻 / 专业站域名同时进 `_build_agent_preferred_sites`，成为 `site:` 检索候选；社交热榜不进（`site:weibo.com` 搜出来是登录墙）。

## 四、配置

```python
CONFIG["news"]["sources"] = {
    "enabled": True,
    "registry_path": "data/info_sources.json",
    "feed_cache_path": "output/infosources/feed.json",
    "ttl_hours": 6.0,            # 真实小时
    "per_source_limit": 15,
    "timeout": 10,
    "feed_visit_ratio": 0.6,     # 一次检索有多大概率读自己的食谱
    "full_read": True,           # 摘要 < full_read_min_chars 就抓正文（热榜 / Reddit 除外）
    "full_read_min_chars": 200,
    "diet": {"max_sources": 8, "en_weight": 0.5},
}
CONFIG["news"]["cache_ttl_hours"] = 6.0        # 老的首页缓存也按真实时间门控
CONFIG["news"]["info_seek"]["engines"] = ["x", "ddg", "brave", "tavily", "baidu", "google", "bing"]
CONFIG["news"]["info_seek"]["search_api"] = {"brave_api_key_env": ..., "tavily_api_key_env": ...}
```

`sources.enabled=False` 或注册表为空 → 退回修好正则之后的老路，作对照组。

## 五、CLI

```
python -m gaworld.infosources list [--kind professional]
python -m gaworld.infosources refresh [--force]
python -m gaworld.infosources show weibo_hot
python -m gaworld.infosources diet --job "社区医生" --interests 跑步,养生 --openness 1.0
```

## 六、注册表里的源（37 个）

新闻 11（BBC 中文 / 纽时中文 / DW 中文 / 联合早报 / 人民网时政 / 澎湃首页 + BBC / NYT / Guardian / Al Jazeera / CNBC）；
社交 9（微博热搜 / 百度热搜 / B站热门 / 知乎精选 / V2EX + Reddit ×3 / Hacker News）；
专业 17（机器之心 / 36氪 / 虎嗅 / 少数派 / 极客公园 / Solidot + arXiv cs.AI / econ.GN / Nature / ScienceDaily / WHO / STAT / MIT TR / EdSurge / MarketWatch / Stack Overflow）。

全部是公开、免登录、返回结构化文本的端点。它们各自在哪张网络上能通是操作者的事：抓不到只记一条警告，`http_guard` 的失败缓存保证不反复撞。**中文专业站（丁香园、医脉通、法院网…）基本没有公开 RSS**，注册表顶部的说明写了用自建 RSSHub 路由以 `rss` 渠道接入。

## 七、测试

`tests/test_infosources.py`（46 例，全部无网络）：七类解析器的 fixture、抓取分发的失败模式、注册表校验、TTL 门控 / 去重 / 上限 / 往返、食谱的职业 / 兴趣 / 开放性 / 平台依赖 / 确定性、抽条目的 seen 与穿透、三个搜索提供方、`_news` 的正则修复 / 首页 TTL / `ddg` 引擎 / feed 模式 / 记忆格式（老模式逐字不变）、插件在真实内核上的生命周期。

## 八、有意不做的

- **不做「按仿真日期取历史新闻」**：真实世界的时间线跟仿真日历本来就对不上，`city/news.py` 的「真实时间抓、仿真时间轮着发」是对的，这里沿用。
- **不做 Dashboard 面板**：配置项走已有的自动表单（`config_docs` 已登记标签与说明），食谱看 `output/infosources/diets.json` 或 CLI。
- **不把食谱写进 CSV / profile**：它是从职业、兴趣、状态、人格推出来的读数，每次运行重算；持久化会让它跟来源脱钩。
- **不动快进驱动**：`_fastforward.py` 本来就不做主动检索。
