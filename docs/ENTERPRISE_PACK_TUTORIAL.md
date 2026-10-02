# 企业用户数据 → 智能体包 使用说明

> 把企业的用户数据文件（CSV / xlsx / JSONL）**匿名化**后转成 GAWorld 多智能体，打包成一个 zip 下载分发。
>
> 命令：`python -m gaworld.enterprise`｜代码：`gaworld/enterprise/`
> 相关：仪表盘里的批量导入（直接写进城市）见 [`BULK_IMPORT_TUTORIAL.md`](./BULK_IMPORT_TUTORIAL.md)｜城市 bundle 见 [`CITY_TUTORIAL.md`](./CITY_TUTORIAL.md)

---

## 目录

- [0. 它做什么、不做什么](#0-它做什么不做什么)
- [1. 三分钟跑通](#1-三分钟跑通)
- [2. 准备数据文件](#2-准备数据文件)
- [3. 检查列映射（--dry-run）](#3-检查列映射--dry-run)
- [4. 匿名化规则](#4-匿名化规则)
- [5. 缺失字段怎么补](#5-缺失字段怎么补)
- [6. 包里有什么](#6-包里有什么)
- [7. 在 GAWorld 里使用这个包](#7-在-gaworld-里使用这个包)
- [8. 命令行参数一览](#8-命令行参数一览)
- [9. 在 Python 里调用](#9-在-python-里调用)
- [10. 已知限制与分发前检查清单](#10-已知限制与分发前检查清单)
- [11. 常见问题](#11-常见问题)

---

## 0. 它做什么、不做什么

```
users.csv / .xlsx / .jsonl
   │  ① 解析 + 列映射（复用 gaworld.apps.import_api）
   ▼
   │  ② 匿名化：删标识、换化名、粗化收入、清洗自由文本
   ▼
   │  ③ 渲染成智能体（与 gaworld.city.agents 同一种 profile 格式）
   ▼
agents.zip ── agents.csv / profiles.md / agents.jsonl / report.json / README.md
```

- **完全在本机运行**：不联网、不调用大模型，原始数据不离开这台机器。
- **不写入任何城市**：只读 `--city` 指定城市的区划名，产出只有那一个 zip。
  想直接把用户导入某座城市，用仪表盘的批量导入。
- **一行用户 = 一个智能体**：不做人口扩样。需要扩样请用 `python -m gaworld.population`。

## 1. 三分钟跑通

```bash
# ① 先看每一列会被怎样处理（不生成任何文件）
python -m gaworld.enterprise users.csv --dry-run

# ② 生成智能体包，居住地落在「绍兴柯桥」的真实区划里
python -m gaworld.enterprise users.csv -o out/agents.zip --city 绍兴柯桥
```

终端会打印一份 `report.json` 和最后一行：

```
已生成 1200 个智能体 → out/agents.zip
```

## 2. 准备数据文件

| 格式 | 要求 |
|---|---|
| CSV | 第一行是表头；UTF-8（带不带 BOM 都可以） |
| xlsx | 读取**第一个工作表**，第一行是表头；需要 `openpyxl` |
| JSONL | 每行一个 JSON 对象，键就是列名（`.json` 也按 JSONL 读） |

工具能识别的字段（按列名**模糊匹配**，中英文均可）：

| 字段 | 可识别的列名 | 进入智能体？ |
|---|---|---|
| `name` | 姓名、名字、name | 换成化名 |
| `gender` | 性别、sex、gender | ✅ 男/女/M/F/male/female 等 |
| `age` | 年龄、age | ✅ 0–100 的数字 |
| `hukou` | 户口、hukou | ✅ |
| `education` | 学历、教育、education | ✅ |
| `employment` | 在职、工作状态、employment | ✅ 写进「职业」一栏 |
| `industry` | 行业、industry | ✅ 写进「职业」一栏 |
| `monthly_income` | 收入、月薪、salary、income | ✅ 按 500 元取整 |
| `hometown` | 家乡、籍贯、hometown | 换成虚构地名 |
| `personality` | 性格、personality | ✅ 清洗后保留 |
| `daily_life` | 日常生活、daily_life | ✅ 清洗后保留 |
| `values` | 价值观、values | ✅ 清洗后保留 |
| `phone` / `email` / `id_card` | 电话、手机、邮箱、身份证、证件号… | ❌ 删除 |
| `company` / `residence` | 公司、工作单位、住址、居住地… | ❌ 删除 |
| `id` | 编号、id、agent_id | ❌ 删除（智能体从 1 重新编号） |

**没识别出来的列一律丢弃**（白名单，而不是黑名单）。所以漏掉一列只会少信息，不会泄露信息。

> 模拟器里的九个状态变量（`emotion`、`stress`、`econ_security` …）如果文件里恰好有同名列、
> 数值在 0–1 之间，也会沿用；否则随机初始化。

## 3. 检查列映射（--dry-run）

列名是模糊匹配的，**第一次处理一个新文件时一定先跑 `--dry-run`**：

```
$ python -m gaworld.enterprise customers.csv --dry-run
1 行，10 列
  客户编号                 丢弃
  姓名                   → name
  性别                   → gender
  出生年龄                 → age
  手机号                  丢弃
  电子邮箱                 丢弃
  职业                   丢弃      ← 没识别出来
  所在城市                 丢弃
  月收入                  → monthly_income
  备注                   丢弃      ← 想保留
```

用 `--map 列名=字段` 纠正，可以写多次；`--map 列名=`（等号后留空）表示**强制丢弃**：

```bash
python -m gaworld.enterprise customers.csv --dry-run \
  --map 职业=employment \
  --map 备注=daily_life
```

确认无误后，去掉 `--dry-run`、带上同样的 `--map` 再跑一次。
列名写错时会直接报错并列出文件里的所有列。

## 4. 匿名化规则

| 处理方式 | 对象 | 结果示例 |
|---|---|---|
| **删除** | 手机、邮箱、身份证、公司、住址、编号，以及所有未识别列 | — |
| **化名** | 姓名 | `张伟明` → `吴杰`；同一次运行内化名**不重复** |
| **虚构地名** | 家乡 | `绍兴` → `青石镇`；同一家乡映射到同一虚构地名 |
| **重新抽取** | 居住地 | 从 `--city` 城市的区划中随机抽，如 `世安桥村·青年公寓` |
| **粗化** | 月收入 | `18234` → `18000` |
| **清洗** | 性格 / 日常 / 价值观 | 见下 |

**自由文本清洗**分两步：

1. 把**本行**的姓名、公司、住址、家乡等原值找出来替换：姓名换成同一个化名，其余换成「某处」。
2. 用规则再扫一遍：邮箱 → `[邮箱]`，18 位证件号 → `[证件号]`，手机号 → `[电话]`，
   其他 6 位以上的数字串（卡号、订单号、座机、日期…）→ `[号码]`。

```
原文：张伟明性格开朗，常在星辰科技加班，电话13812345678
结果：吴杰性格开朗，常在某处加班，电话[电话]
```

**盐值（salt）**：化名由「盐值 + 原名」哈希决定。默认每次运行随机生成盐值，并且**不写进包里**，
别人拿到包也无法靠重跑工具反推出真名。需要让同一份文件每次得到相同化名（例如数据增量更新）时，
用 `--salt <自定义字符串>`，并把这个盐值当作密钥妥善保管。

## 5. 缺失字段怎么补

企业数据往往只有人口学字段，没有性格描述。模拟器需要完整的 profile，所以缺失项会被补上，
**补了多少会记录在 `report.json` 的 `imputed` 里**：

| 缺失字段 | 补法 |
|---|---|
| 年龄 | 35 岁 |
| 性别 | 男/女随机（受 `--seed` 控制） |
| 性格 / 日常 / 价值观 | 与 `add_agent` 相同的中性默认描述 |
| 学历 / 收入 / 职业 | 写明「未提供」，**不会编造** |
| 九个状态变量 | 0.35–0.70 之间随机 |

补全比例过高（例如 `personality` 几乎全部是补的）意味着这批智能体的行为主要来自默认设定，
解读模拟结果时要考虑这一点。

## 6. 包里有什么

| 文件 | 内容 |
|---|---|
| `agents.csv` | 居民状态表，GAWorld `csv_path` 的格式（UTF-8 带 BOM） |
| `profiles.md` | 居民人物设定，GAWorld `md_path` 的格式，每人一个 `## Profile NN｜化名` 块 |
| `agents.jsonl` | 每行一个智能体的完整字段，方便其他系统读取 |
| `report.json` | 处理报告，**不包含任何原始值** |
| `README.md` | 包的简要说明，随包分发给接收方 |

`report.json` 示例：

```json
{
  "created_at": "2026-09-26T02:09:13+00:00",
  "source_rows": 1200,
  "agents": 1200,
  "columns": {"客户编号": "dropped", "姓名": "name", "手机号": "dropped", "职业": "employment"},
  "free_text": "scrubbed",
  "scrubbed": {"literal": 37, "phone": 12, "email": 3, "number": 8},
  "imputed": {"age": 41, "personality": 1200, "values": 1200},
  "salt": "random (not stored)"
}
```

- `columns`：每一列最终的去向，可以作为合规留档。
- `scrubbed`：自由文本里各类信息被替换的次数。
- `imputed`：各字段被补全的人数。

## 7. 在 GAWorld 里使用这个包

**方式一：直接指向这两个文件。** 解压到仓库内某个目录，然后在 `dashboard_config.json` 中设置：

```json
{
  "csv_path": "data/enterprise/acme/agents.csv",
  "md_path": "data/enterprise/acme/profiles.md"
}
```

再照常运行 `python generative_city_sim.py run`，或在仪表盘里打开 Agent Studio、群体采访等功能。

**方式二：放进一座城市。** 生成时用 `--city <城市>`，居住地就是这座城市的真实区划名；
再把 `agents.csv` / `profiles.md` 复制进 `data/cities/<slug>/`，替换同名文件，
并用 `python -m gaworld.city use <slug>` 切换过去。**替换前请先备份原文件。**

## 8. 命令行参数一览

```
python -m gaworld.enterprise SOURCE [选项]
```

| 参数 | 说明 |
|---|---|
| `SOURCE` | 用户数据文件（必填） |
| `-o, --output` | 输出 zip 路径，默认 `<文件名>_agents.zip`，与源文件放在同一目录 |
| `--city` | 城市 slug 或名称，居住地从该城市的区划中抽取；不给时统一写「城区」 |
| `--map 列名=字段` | 覆盖列映射，可写多次；字段留空表示丢弃该列 |
| `--salt` | 化名盐值，给定后化名可复现（默认随机、不保存） |
| `--seed` | 补全性别、状态变量、居住地所用的随机种子，默认 0 |
| `--drop-free-text` | 丢弃性格、日常、价值观三段自由文本，改用默认描述 |
| `--dry-run` | 只打印列映射，不生成文件 |

退出码：`0` 成功，`1` 数据或参数错误（如列名不存在、文件为空），`2` 文件不存在。

## 9. 在 Python 里调用

```python
from pathlib import Path
from gaworld.enterprise import build_package

report = build_package(
    Path("users.csv"),
    Path("out/agents.zip"),
    overrides={"职业": "employment", "备注": "daily_life"},
    districts=["柯桥区", "越城区"],   # 可选；不给则为「城区」
    drop_free_text=False,
)
print(report["agents"], report["imputed"])
```

只做匿名化、不打包时，可以用 `gaworld.enterprise.prepare(path, overrides)` 读取并映射列，
再用 `gaworld.enterprise.anonymise(rows, salt=...)` 处理。

## 10. 已知限制与分发前检查清单

**限制：**

- **自由文本里其他人的姓名识别不出来**。「和同事李娜一起加班」中的「李娜」如果不是本行用户，
  就不会被替换，这需要识别人名的模型才能做到。敏感场景请用 `--drop-free-text`。
- **准标识符组合**：年龄 + 性别 + 行业 + 收入组合起来，在很小的样本里仍可能锁定到具体某个人。
  用户数很少（例如几十人）或群体很特殊时，建议先在源文件里把年龄分段、收入分档。
- **列名模糊匹配可能出错**：例如带 `id` 字样的列都会被当作编号丢弃。所以务必先跑 `--dry-run`。

**分发前检查清单：**

1. `--dry-run` 确认每一列的去向，敏感列都显示「丢弃」。
2. 打开 `report.json`，看 `columns` 和 `imputed` 是否符合预期。
3. 抽查 `profiles.md` 里 10–20 个人的自由文本，确认没有残留真名或内部编号。
4. 确认 zip 里没有 `--salt` 的值（默认也不会写入）。

## 11. 常见问题

**Q：xlsx 报错「需要 openpyxl」？**
执行 `pip install openpyxl`，或者先把表格另存为 CSV。

**Q：同一个人跑两次，化名不一样？**
这是默认行为：每次盐值随机。需要化名稳定时，用固定的 `--salt`。

**Q：`--city` 报找不到城市？**
先用 `python -m gaworld.city list` 看看有哪些城市，`--city` 填 slug 或名称都可以。

**Q：两个用户同名，会得到同一个化名吗？**
不会。同一次运行内化名保证唯一，所以 `agents.csv` 里的名字可以当作人的区分依据。

**Q：可以把包直接交给第三方吗？**
这个工具只能降低风险，不能替代合规审核。请先按第 10 节的清单检查，并遵守贵司的数据出境、
个人信息保护等相关制度。
