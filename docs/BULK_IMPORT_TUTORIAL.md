# 批量导入居民教程

> 在 Agent Studio 顶栏点击「＋ 批量导入」，把一份外部用户表变成这座城市里的居民。
>
> 面板：Agent Studio 顶栏按钮｜引擎：`gaworld/apps/import_api.py`｜测试：`tests/test_import_api.py`

---

## 目录

- [0. 这是什么，什么时候该用](#0-这是什么什么时候该用)
- [1. 五分钟跑通](#1-五分钟跑通)
- [2. 支持的输入格式与列名](#2-支持的输入格式与列名)
- [3. 两个开关：匿名化 & 扩容](#3-两个开关匿名化--扩容)
- [4. 写进哪里：城市包的 atomic 流程](#4-写进哪里城市包的-atomic-流程)
- [5. 程序化调用：HTTP API](#5-程序化调用http-api)
- [6. 排查清单](#6-排查清单)
- [7. 与其它管线的关系](#7-与其它管线的关系)

---

## 0. 这是什么，什么时候该用

把外部用户数据（CRM、问卷、注册表等）一次性导入到指定城市，让它们以仿真居民的身份参与社会动力学。

**适用**：

* 你的真实业务想跑一次 A/B 仿真，看看人群在某个公共事件下会怎么反应；
* 你想让仿真的人口结构贴近某份调研结果；
* 你想保留一批「种子居民」，再用 IPF 抽样补齐到 N 人，保证分布不偏。

**不适用**：

* 你只有 1–3 个真实用户想蒸馏 —— 用 Agent Studio 顶栏「＋ 从真人蒸馏」更合适；
* 你想完全虚构一座城 —— 用 `python -m gaworld.city create "地名"` 或 Dashboard 的「人口与群体」向导。

---

## 1. 五分钟跑通

1. 打开 `http://localhost:<port>/site/dashboard/studio.html`。
2. 在左侧「选择城市」里挑好目标城市。
3. 顶栏点「＋ 批量导入」。
4. 把一份 CSV 拖到上传框（也可以是 .xlsx 或 .jsonl）。
5. 第二步检查「列映射」—— 系统已按表头含义给出推荐；调一下错的列。
6. 第三步勾选「匿名化（推荐）」，填「扩容到」人数（≥上传库人数），点「开始导入」。
7. 等进度条到 100%，会出现「直接导入 / 抽样新增 / 城市人口」三栏摘要。点「完成」关掉 Modal，居民已落到当前城市。

> 想撤销这次导入？目前没有原子回滚。批量导入会 append 到 `agents.csv` 与 `profiles.md`；如果你立刻后悔，从 `data/cities/<slug>/` 恢复对应备份即可。

---

## 2. 支持的输入格式与列名

### 2.1 格式

| 后缀 | 说明 |
| --- | --- |
| `.csv` | UTF-8 / UTF-8-BOM；首行表头；引号字段支持 |
| `.xlsx` | 走 SheetJS CDN 在浏览器里解析；首行表头 |
| `.jsonl` / `.ndjson` | 每行一个 JSON 对象；行内数组会被展开成多行 |
| `.json` | 同 JSONL（数组 / 对象混排都可） |

最大 5 MB；更大文件会被前端拒绝（限制来自浏览器读取策略，不是后端）。

### 2.2 列名识别

按 canonical field 同义词识别。**中文 / 英文都能识别**，识别失败留空（可在第二步改）。

| Canonical | 常见同义词 |
| --- | --- |
| `name` | 姓名 / 名字 / name |
| `gender` | 性别 / gender / sex |
| `age` | 年龄 / age |
| `hukou` | 户口 / hukou |
| `residence` | 居住地 / 住址 / 现居 / residence / address |
| `employment` | 在职 / 工作状态 / employment / job_status |
| `industry` | 行业 / industry |
| `monthly_income` | 月薪 / 收入 / 工资 / income / salary |
| `education` | 学历 / 教育 / education |
| `hometown` | 家乡 / 籍贯 / hometown |
| `company` | 公司 / 工作单位 / workplace |
| `personality` / `daily_life` / `values` | 性格 / 日常生活 / 价值观 / personality / daily_life / values |
| `phone` / `email` / `id_card` | 电话 / 邮箱 / 身份证 / phone / email / id_card |
| 9 个心理变量 | emotion / stress / econ_security / city_identity / policy_sensitivity / platform_dependence / risk_preference / voice_propensity / mobility_intent |

未识别的列默认「忽略」（不写入 agent 也不污染分布推断）。不会让导入失败。

### 2.3 一个能跑的最小例子

```csv
姓名,性别,年龄,户口,行业,月薪,家乡
张伟,男,32,本地,互联网,18000,杭州
李娜,女,28,外省,金融,22000,绍兴
王强,男,45,省内,医疗,15000,宁波
```

三行上传，「扩容到 30」，匿名化开启 → 直接导入 3 人，再由 IPF 抽样 27 人（与上传库同分布但身份独立）。

---

## 3. 两个开关：匿名化 & 扩容

### 3.1 匿名化（默认开启）

**强烈建议保持默认开启**。它的动作：

| 字段类别 | 处理方式 |
| --- | --- |
| `name` | 替换为 1024 × 64 池中的确定性假名（同 salt + 同原名 → 同一假名） |
| `phone` / `email` / `id_card` | 直接丢弃，不写入 agent |
| `hometown` | 替换为 13 个池地之一 |
| `residence` 含人名/地名 | 同 hometown 处理 |
| `personality` / `daily_life` / `values` / `company` 自由文本 | 用正则扫掉 2-4 字 CJK 姓名形 token 与 `家乡是X` 显式提及 |

`salt` 默认 `web-<timestamp>`（即「同一用户在浏览器内重复上传得到同一假名；换浏览器 / 隔天上传得到不同假名」）。如果你的内部流程要求跨会话稳定，改为固定字符串。

> 这是「启发式匿名化」，不是合规级的去标识化。处理医疗 / 金融等强隐私场景，请先在内部做 PII 清洗。

### 3.2 扩容（默认 = 上传库人数 = 不扩容）

填 N（≥上传库人数）。系统会：

1. 把上传库的前 N_直接 行逐条写入（匿名化 + 字段映射后）；
2. 把上传库的年龄 / 性别 / 行业 / 月薪等边际分布聚合成一个 `PopulationSpec`；
3. 调用现有的 IPF 采样器生成剩余 N − N_直接 人，append 到同城市。

合成的虚拟居民与上传库**同分布但不同身份**——不会复刻某个真实用户，但性别比、年龄金字塔、行业占比、月薪中位数都来自你上传的库。`seed` 由前端随机生成，可重复点「再导一批」会换 seed。

---

## 4. 写进哪里：城市包的 atomic 流程

批量导入会写入目标城市的两个文件：

* `data/cities/<slug>/agents.csv`（BOM UTF-8，CSV_COLUMNS 顺序）
* `data/cities/<slug>/profiles.md`（每行 `## Profile N｜Name`）

新增 id 从当前 `agents.csv` 的最大 id + 1 开始；不重用旧号，避免和 `memory / big_five / social / finance` 等按 id 命名的子状态错位。

如果「扩容」被启用，合成的虚拟居民由 `add_population` 走与「创建」人口完全相同的路径：

```
gaworld/population/normalize_spec → generate_population → render_state_csv + render_profiles_markdown
```

所以行为和「人口与群体」向导里「选模板 + 跑模拟」得到的合成居民完全一致。

---

## 5. 程序化调用：HTTP API

后端是标准 JSON over HTTP；前端只是它的 UI 包装。

### 5.1 `GET /api/import/schema`

返回允许的 canonical field 列表、同义词字典、支持的文件格式。用于脚本里做列映射自检。

```bash
curl -s http://localhost:<port>/api/import/schema | jq
```

### 5.2 `POST /api/import/preview`

请求体（任选其一）：

```json
// 方式 A：已在前端解析过
{
  "format": "csv",
  "headers": ["姓名", "性别", "年龄"],
  "rows": [{"姓名":"张伟","性别":"男","年龄":"32"}, ...],
  "mapping": {"姓名": "name"},            // 可选；不传则用 suggest_mapping
  "anonymise": true,
  "expand_to": 30
}

// 方式 B：把原文 / base64 一起送
{
  "format": "xlsx",
  "filename": "people.xlsx",
  "file_text": "<base64>",
  "file_encoding": "base64"
}
```

响应：推断出的 demography 概览、推荐 mapping、expand_to 与 expand_extra（要补多少人）。

### 5.3 `POST /api/import/run`

请求体同上，但**会真正写入**目标城市。

```bash
curl -s -X POST http://localhost:<port>/api/import/run \
  -H "Content-Type: application/json" \
  -d '{
    "city": "wuzhen",
    "format": "csv",
    "filename": "people.csv",
    "file_text": "姓名,性别,年龄\n张伟,男,32",
    "anonymise": true,
    "expand_to": 30,
    "seed": 42,
    "salt": "gaworld-2026-09"
  }' | jq
# => {"job_id": "import-3a8e7c2d"}
```

### 5.4 `GET /api/import/jobs/<id>`

轮询 job 状态：

```bash
curl -s http://localhost:<port>/api/import/jobs/import-3a8e7c2d | jq
# => {"status": "running", "progress": 0.42, "message": "..."}
# => {"status": "done", "progress": 1.0, "result": {"inserted_direct": 3, "expanded_extra": 27, "total": 30, "city": "wuzhen"}}
# => {"status": "failed", "error": "CityNotFoundError: ..."}
```

实现细节：`/api/import/*` 在 `gaworld.apps.import_api`，路由由 `dashboard_server._handle_api_get` / `_handle_api_post` 转发，复用与 `population_api` 相同的 job 注册表（`GATE` 上限 20 条）。

---

## 6. 排查清单

| 现象 | 原因 | 修法 |
| --- | --- | --- |
| 「解析失败」 | 文件不是 UTF-8 / 没表头 / 空文件 | 用 `file -i` 看编码；首行加表头 |
| 「预览失败」 | 后端 500 / 缺列 | 看 terminal / `output/logs/`；列名是否在 §2.2 同义词里 |
| 「导入失败：CityNotFoundError」 | 当前 dashboard_config.city 没切到目标城市 | 调「城市」面板 → 切过去 → 再导入；或在 API 请求体里写绝对路径 |
| 写进去的姓名还是「张伟」 | 忘了勾匿名化 | 重新导入；匿名化是「写时」动作，不补改旧数据 |
| 扩容后行业分布跟上传库对不上 | 上传库某行业只有 1–2 个人 | IPF 会按目标行业 mix 平衡，不是「原样放大」；这是预期行为 |
| 找不到「＋ 批量导入」按钮 | 你在浏览模式浏览其他城市；按钮在浏览模式仍可见但被 disable | 切回「当前运行城市」再操作 |

---

## 7. 与其它管线的关系

* **`population_api`**：批量导入的「扩容」部分复用了 `add_population` 的 IPF 管线；同 IPF / 同 `PopulationSpec`，行为一致。
* **`persona_api`**：「批量导入」生成的是「按分布合成的居民」，不带心智模型；要做真人画像蒸馏用顶栏「＋ 从真人蒸馏」按钮，背后是 `persona_api`。
* **`city_api`**：切换 / 列出 / 删除城市的 API 与本功能正交；批量导入要求「目标城市在 `data/cities/<slug>/` 已存在」。
* **`moltbook / memory / family / work`**：导入完成后，这些插件会在下一次 `python generative_city_sim.py run` 启动时按 id 1..N 自然 attach 到新居民上，不需要额外触发。