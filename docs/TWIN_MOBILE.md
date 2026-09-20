# 手机端数字孪生（Mobile Digital Twin）

> 把你自己接进仿真：手机上报真实位置与行为，驱动一个属于你的智能体，
> 并在小屏上看到它的形象与今日轨迹。
>
> 后端：`gaworld/apps/twin_server.py`｜逻辑：`gaworld/twin/`｜前端：`site/mobile/`
> 设计：[spec](./superpowers/specs/2026-08-08-mobile-digital-twin-design.md)

---

## 目录

- [0. 这是什么，什么时候该用](#0-这是什么什么时候该用)
- [1. 五分钟跑通（本机）](#1-五分钟跑通本机)
- [2. 让手机连上：HTTPS 是硬要求](#2-让手机连上https-是硬要求)
- [3. 绑定：邀请码与令牌](#3-绑定邀请码与令牌)
- [4. 三条消费通道](#4-三条消费通道)
- [5. 在仿真里启用孪生](#5-在仿真里启用孪生)
- [5b. 手机上有什么](#5b-手机上有什么)
- [6. 离线画像标定](#6-离线画像标定)
- [7. API 速查](#7-api-速查)
- [8. 参数速查](#8-参数速查)
- [9. 已知限制](#9-已知限制)

---

## 0. 这是什么，什么时候该用

一句话：**手机采集你的真实位置与行为，服务端把它变成仿真里某个智能体的状态与记忆。**

适合：

- 想验证"真实数据驱动的智能体"这个想法本身
- 需要一份真实作息/轨迹数据，用来标定或对照仿真中的 agent
- 给合作者/评审演示"我的孪生"

**不适合**：面向真实用户的产品。当前定位是研究与演示，**没有注册体系、没有个人信息合规流程**。
位置历史属于个人信息保护法下的敏感个人信息，若要开放给研究对象以外的人，必须先补齐告知同意、
留存期限与删除机制。

### 为什么是独立进程

`twin_server` 与控制台 `dashboard_server` 是**两个进程**，这不是洁癖：

`dashboard_server` 接受**无鉴权**的 `POST /api/config`（改全局配置）与 `POST /api/run/start`
（拉起仿真子进程）。把它绑到 `0.0.0.0`，等于把改配置和起进程的能力开放给任何扫到端口的人。
所以它**永远留在 `127.0.0.1:8766`**，公网上只放 `twin_server` 那一组孪生端点（见第 7 节）。

`tests/test_twin_server.py::test_dashboard_endpoints_are_not_reachable` 守着这条线：
在 twin 服务上 `POST /api/config` 必须是 404。

---

## 1. 五分钟跑通（本机）

**第一步，签发一个邀请码**：

```bash
python3 -m gaworld.apps.twin_server --issue-code --label "我"     # 不指定，手机上自己挑
python3 -m gaworld.apps.twin_server --issue-code 1 --label "我"   # 或直接指定 agent 1
```

不带 agent id 就是**未绑定邀请码**：兑换后手机上会先出现一个名单，
让使用者自己挑孪生哪一位。想把某个特定 agent 交给某个特定的人时，再用第二种。

输出一串短码，例如 `52t8-ylFmr0b`。这串码只出现这一次——服务端只存它的哈希。

**第二步，起服务**：

```bash
python3 -m gaworld.apps.twin_server --port 8767
```

**第三步，浏览器打开** `http://127.0.0.1:8767/`。

首次打开会先看到一页**介绍**（现实与仿真两条同步轨迹的示意动画 + 三步说明），
点「开始」进入邀请码输入。介绍只出现一次，标记存在 `localStorage` 的
`gaworld.twin.introSeen`；已经持有令牌的用户永远不会看到它。想再看一次就清掉这个键。

注意 `/` 会 **302 跳到 `/site/mobile/`**。这是必需的：前端的相对路径、manifest 的
`start_url` 与 Service Worker 的 scope 都依赖真实的 base URL；如果直接在 `/` 上吐
index.html，浏览器会去要 `/core.js` 而不是 `/site/mobile/core.js`，页面返回 200 但
没有样式也没有脚本。

本机 `http://127.0.0.1` 下浏览器允许定位；**换成手机就不行了**，见下一节。

---

## 2. 让手机连上：HTTPS 是硬要求

浏览器的 Geolocation API 在**非 HTTPS 且非 localhost** 的页面上直接不可用。
所以"手机连远程服务器"这件事，TLS 不是加分项而是前提。

推荐 Cloudflare Tunnel：零公网 IP、零证书运维。

```bash
cloudflared tunnel --url http://127.0.0.1:8767
```

它会打印一个 `https://<随机名>.trycloudflare.com` 域名，手机直接访问即可。
需要固定域名与第二层鉴权时，用具名隧道并挂上 Cloudflare Access。

> **别把 8766 也开出去。** 隧道只指向 8767。

自建服务器 + Caddy 同样可行：

```
twin.example.com {
    reverse_proxy 127.0.0.1:8767
}
```

---

## 3. 绑定：邀请码与令牌

```
邀请码 ──redeem──▶ 令牌（Bearer）──▶ 唯一确定一个 agent_id
```

关键设计：**`agent_id` 不在请求体里**，而是由令牌反查得出。否则任何持有合法令牌的人，
改一个字段就能写别人的 agent。`tests/test_twin_backend.py::test_a_client_cannot_write_another_agents_data`
就是守这条的。

邀请码与令牌都是随机不透明串，服务端**只存 SHA-256 哈希**，读绑定文件不足以冒充任何人。

一个邀请码可以多次兑换（重装 PWA、清了站点数据），每次发新令牌。撤销邀请码会
**连带失效由它签出的全部令牌**——否则撤销就形同虚设。

绑定存在 `data/twin_bindings.json`，已加入 `.gitignore`。

---

## 4. 三条消费通道

`output/twin/agent_<id>/reports.jsonl` 是**唯一事实来源**，只追加。三条通道都从它派生，互不耦合：

| 通道 | 读什么 | 写什么 | 时机 |
|---|---|---|---|
| A 镜像 | `snapshot.json` | agent 的 `locations.current` 与当前动作 | 每 tick |
| B 感知注入 | 上次消费位点之后的新上报 | episodic memory | 每 tick |
| C 画像标定 | 全量 `reports.jsonl` | habits/profile 补丁 | 离线，**人工确认后** |

C 刻意不自动写 profile：让采集数据静默改写实验对象，会让后续结果无法归因——
到底是配置改了，还是画像悄悄漂了？

**上报过期怎么办**：超过 `snapshot_ttl_minutes`（默认 30）没有新上报，镜像通道停止覆盖，
agent 回到自主行为，手机端显示「未同步」，而不是把几小时前的位置当作当前位置继续展示。

**人不在地图范围怎么办**：`out_of_map` 的含义是「**没有匹配到地图节点**」，不是「位置无效」。

真实经纬度**永远照常记录**，也照常画在轨迹图上。落点离所有节点都超过 `max_snap_km`
（默认 3 公里）时：

- `node_id` 为空，`place` 给出离线推断的地名（如「北京」）
- 镜像通道把 agent 的位置写成 `异地（北京）`，而**不是**留在原地假装它还在城里
- 绝不吸附到最近节点——伪造的位置会同时污染镜像与标定数据

> 地名是**完全离线**算出来的：先看坐标是否落在你已建过的城市 bundle 的 bbox 里，
> 否则查一张内置的省级中心表，都不命中就直接给经纬度。
> **不走任何反向地理编码 API**——那等于把用户的精确位置发给第三方，
> 与「位置数据只发到你自己的服务器」这条承诺直接冲突。
> 代价是精度只到省级（加上你自己建过的城市），这是标注「异地」够用的分辨率。

---

## 5. 在仿真里启用孪生

两步，都是配置，**不用改任何代码**。

```python
CONFIG["twin"]["enabled"] = True

CONFIG["pipeline"]["agent_step"] = [
    "prepare", "perceive", "gaworld.twin.stages:twin_perceive", "interrupts",
    "plan", "adjust_activity", "move", "select_action",
    "gaworld.twin.stages:twin_mirror", "reflect", "update_state",
    "broadcast", "memorize", "record",
]
```

### 两个插入点，不能合并

```
perceive → [twin_perceive] → interrupts → plan → …
    … → select_action → [twin_mirror] → reflect
```

- `twin_perceive` 在 `perceive` 之后：真实上下文进入感知，`plan` 能看见，agent 自己决定怎么反应。
- `twin_mirror` 在 `select_action` 之后：agent 正常规划、正常移动，**最后**才被真实数据覆盖。

> ⚠️ **`twin_mirror` 必须在 `move` 之后。** 放在 `move` 之前会被 `move` 原样改回去，
> 而且**不报错**——stage 照跑，值照写，然后被覆盖。
> `tests/test_twin_stages.py::TestStageOrdering` 把这条顺序钉死了。

### 每次镜像都有审计

覆盖走 `set_agent_twin_state` 干预，落进 `controller.intervention` 审计表
（`output/records/controller.intervention.jsonl`）。这不是锦上添花：没有这条轨迹，
事后分析无法区分某个行为是仿真自己生成的，还是从现实注入的。

（标准的 `set_agent_state` 只接受 float，写不了字符串型的 location 与 action，所以另起了一个。）

### 开关即对照组

孪生默认**关闭**，且默认流水线不含这两个 stage。开启是显式动作——这正好让
「有孪生 / 无孪生」成为一组干净的对照实验。

---

## 5b. 手机上有什么

| 区域 | 内容 |
|---|---|
| 选择孪生对象 | 首次兑换未绑定邀请码时出现，列出当前城市全部居民，标注哪些在仿真中、哪些已被别的设备占用；主界面底部的「换一个智能体」可随时更换 |
| 形象卡 | 头像（随行为切换姿态动画）、同步状态、当前行为与地点 |
| 上报 | 十个行为标签 + 备注 + 上报；「和刚才一样」一键重复上一次的标签 |
| 今日上报 | 当天每条上报，下拉改标签、✕ 删除（会二次确认，手机上删了撤不回来） |
| 智能体的今天 | 它写的日记、状态条、当前三层目标 |
| 今日轨迹 | canvas 折线 + 「回放」按时间轴重放当天路径 |

**自动记录位置**是一个可选开关，每 10 分钟采样一次，**只在页面可见时生效**。

> iOS 上的 PWA 拿不到真正的后台定位，这是平台限制不是实现问题。
> 别按"装上就能自动记录一整天"来设计流程——要连续轨迹只有原生 App 或让页面常驻前台两条路。

**拿不到定位时**会弹出可搜索的地点列表让你手动选。选中的地点是以**坐标**发出去的，
服务端照常跑吸附与 `out_of_map` 判定——客户端从来没有直接指定节点 id 的权力。
也可以选「仅上报行为」，那条上报会被标成 `out_of_map`，位置不同步但行为照常记录。

首次打开会先看到一页介绍（现实与仿真两条同步轨迹的动画 + 三步说明），
点「开始」进入邀请码输入。只出现一次，标记在 `localStorage` 的 `gaworld.twin.introSeen`。

---

## 6. 离线画像标定

```bash
python3 scripts/twin_calibrate.py 1
```

打印一份可读的 diff（常去地点、行为分布），**什么都不写**。确认无误后：

```bash
python3 scripts/twin_calibrate.py 1 --approve --out output/twin/calibration.json
```

`--min-occurrences`（默认 3）过滤偶发信号：只去过一次的地方不算习惯。

---

## 7. API 速查

全部端点走同一个鉴权入口，除签发令牌本身外没有例外路径。

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/twin/auth` | POST | `{"code": "..."}` 换令牌 |
| `/api/twin/report` | POST | 请求体**永远是数组**，长度 1 为常规上报，更长为离线补传 |
| `/api/twin/amend` | POST | `{target, op, patch}` 更正或删除一条已有上报 |
| `/api/twin/snapshot` | GET | 最新上报 + `fresh` 新鲜度 |
| `/api/twin/profile` | GET | 头像 SVG、标签、可选行为词表 |
| `/api/twin/trail` | GET | 今日轨迹点，支持 `?since_ts=` |
| `/api/twin/reports` | GET | 上报历史（已折叠修订），最新在前 |
| `/api/twin/life` | GET | 智能体的日记、状态变量、当前目标 |
| `/api/twin/places` | GET | 可选地点，支持 `?q=` 搜索与 `?limit=` |
| `/api/twin/agents` | GET | 可选的智能体名单，标注「仿真中」与「已占用」 |
| `/api/twin/bind` | POST | `{agent_id}` 选择或更换孪生对象 |

**未选择孪生对象时，其它端点返回 409 而不是 401。** 令牌有效但还没挑人，
手机应该弹名单，而不是把用户踢回邀请码页面。`agent_id` 仍然只从令牌解析——
`/bind` 是唯一接受客户端传 agent_id 的地方，它把选择写进令牌记录。

上报体的 `report_id` 由客户端生成，是**幂等键**：同一个 id 传两次只落一行。
离线补传因此可以放心重发。

### 更正与删除：追加，不是原地改

`reports.jsonl` 只追加，`report_id` 是幂等键，所以更正是**引用旧记录的新记录**：

```json
{"report_id":"<新 uuid>","kind":"amend","target":"<原 report_id>","op":"delete"}
{"report_id":"<新 uuid>","kind":"amend","target":"<原 report_id>",
 "op":"update","patch":{"action_tag":"meal","note":"改成吃饭"}}
```

读取时折叠，所以镜像 stage、感知注入、轨迹、标定脚本全都自动看到更正后的数据。

> **位置不可改，只能删。** `patch` 只接受 `action_tag` 与 `note`。位置是传感器测出来的，
> 允许改会把标定语料从「谁在哪」的记录变成「谁声称自己在哪」。报错了就删掉重报。
>
> 另外：删除是墓碑标记，原始行仍留在 `reports.jsonl` 里。对研究工具这是对的（审计链完整），
> 但它**不等于**个保法/GDPR 意义上的删除，对外不能这么描述。

---

## 8. 参数速查

`CONFIG["twin"]`：

| 键 | 默认 | 说明 |
|---|---|---|
| `enabled` | `False` | 总开关，同时控制两个 stage |
| `root` | `output/twin` | 上报与快照的落盘位置 |
| `bindings_path` | `data/twin_bindings.json` | 绑定与令牌哈希 |
| `snapshot_ttl_minutes` | `30` | 超过则镜像停用、前端显示「未同步」 |
| `max_snap_km` | `3.0` | 超过则判定 `out_of_map` |

### 选了城市，路径会整体搬家

上表的默认值只在**没选城市**时成立。一旦在控制台选了城市，所有运行产物路径会一起
重定向到 `output/cities/<slug>/` 下（`gaworld/city/config.py` 的 `RUN_PATHS`）：

```
twin.root         → output/cities/wuzhen/twin
diary_output_dir  → output/cities/wuzhen/diaries
memory_dir        → output/cities/wuzhen/memory
state_output_dir  → output/cities/wuzhen/state
```

孪生服务是独立进程，但它 `from gaworld.settings import CONFIG`，而城市补丁是在
`apply_runtime_overrides()` 里应用的，所以**它会自动跟着走**，不需要额外配置。

想确认当前落在哪，跑一句：

```bash
python3 -c "from gaworld.settings import CONFIG; print(CONFIG['twin']['root'])"
```

> 如果你选了城市却去 `output/twin/` 找上报数据，会找到一个空目录——数据在城市目录下。

> `max_snap_km` 默认 3 公里偏松——它意味着你可能被归到两公里外的地点。
> 拿到真实 GPS 轨迹后建议收紧。

---

## 9. 已知限制

坦白列出，免得有人踩坑才发现：

1. **尚未在真机上验证。** 所有验证都是无头浏览器 + curl。定位授权弹窗、
   iOS Safari 在独立模式下的 IndexedDB 行为、安装流程，都需要真机 + HTTPS 才能确认。
2. **地图节点名是英文，手动选点的搜索框对中文基本无效。** 实际节点叫
   `Riverside Park`、`Central Parking Lot`，所以搜「咖啡」返回空，搜 `park` 才有结果。
   要么给节点补中文名，要么改成按类别分组而不是靠搜索。
3. **换绑不会搬走历史数据。** 上报日志只追加、按 agent 分目录，所以换成另一位之后，
   之前的上报仍留在原来那位名下。换回去就又能看到。
4. **地名只到省级。** 出差到北京会显示「异地（北京）」，不会精确到区或街道——
   这是为了不把位置发给第三方反查服务而付出的代价。
5. **manifest 没有图标**，安装后用的是系统默认。
6. **Service Worker 缓存需手动失效**：改动 `site/mobile/` 下任何 shell 文件后，
   必须同步提升 `sw.js` 里的 `CACHE_NAME`，否则老用户拿到的是旧包。
7. **Service Worker 注册尚未在真实浏览器中成功过。** 内嵌预览环境会拒绝注册
   （`An unknown error occurred when fetching the script`），而 `sw.js` 本身
   200 且 MIME 正确。`app.js` 对注册失败做了静默降级，所以应用照常可用，
   只是没有离线外壳——这一条同样要靠真机确认。

---

## 相关文件

- 设计：[spec](./superpowers/specs/2026-08-08-mobile-digital-twin-design.md)
- 实施计划：[数据层与服务](./superpowers/plans/2026-08-08-twin-data-spine-and-server.md)
  ｜[仿真接入](./superpowers/plans/2026-08-08-twin-simulation-integration.md)
  ｜[手机端](./superpowers/plans/2026-08-08-twin-mobile-pwa.md)
- 测试：`tests/test_twin_*.py`（123 项）、`site/mobile/core.test.js`（34 项）

其中 `tests/test_twin_e2e.py` 是唯一一个真正跑 `run_simulation` 的：stage 的单元测试
用的是手搭的 step 字典和替身 `move`，即便流水线接入坏了也照样通过。它跑真实仿真并断言
审计表里出现了镜像写入，是唯一会在集成断裂时失败的测试。
