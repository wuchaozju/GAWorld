const fs = require('fs');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, LevelFormat, HeadingLevel, BorderStyle, WidthType,
  ShadingType, PageNumber, Header, Footer, TabStopType, TabStopPosition,
  PageOrientation,
} = require('docx');

// =====================================================================
// Helpers
// =====================================================================
const FONT = "Microsoft YaHei";

const P = (text, opts = {}) => new Paragraph({
  spacing: { before: 60, after: 80, line: 320 },
  children: [new TextRun({ text, font: FONT, size: 22, ...opts })],
});

const H1 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_1,
  spacing: { before: 360, after: 160 },
  children: [new TextRun({ text, font: FONT, size: 32, bold: true, color: "1F4E79" })],
});

const H2 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_2,
  spacing: { before: 260, after: 120 },
  children: [new TextRun({ text, font: FONT, size: 26, bold: true, color: "2E74B5" })],
});

const H3 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_3,
  spacing: { before: 180, after: 100 },
  children: [new TextRun({ text, font: FONT, size: 23, bold: true, color: "404040" })],
});

const Bullet = (text, opts = {}) => new Paragraph({
  numbering: { reference: "bullets", level: 0 },
  spacing: { before: 20, after: 60, line: 300 },
  children: [new TextRun({ text, font: FONT, size: 22, ...opts })],
});

const Code = (text) => new Paragraph({
  spacing: { before: 60, after: 60, line: 260 },
  shading: { fill: "F2F2F2", type: ShadingType.CLEAR },
  children: [new TextRun({ text, font: "Consolas", size: 20, color: "333333" })],
});

const Tip = (text) => new Paragraph({
  spacing: { before: 40, after: 80, line: 300 },
  shading: { fill: "FFF8E1", type: ShadingType.CLEAR },
  children: [new TextRun({ text, font: FONT, size: 21, italics: true, color: "5D4037" })],
});

const RichP = (...runs) => new Paragraph({
  spacing: { before: 60, after: 80, line: 320 },
  children: runs,
});

const T = (text, opts = {}) => new TextRun({ text, font: FONT, size: 22, ...opts });

// Standard table cell builder
const border = { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" };
const borders = { top: border, bottom: border, left: border, right: border };

const Cell = (paragraphs, { fill, width, bold } = {}) => new TableCell({
  borders,
  width: { size: width, type: WidthType.DXA },
  shading: fill ? { fill, type: ShadingType.CLEAR } : undefined,
  margins: { top: 80, bottom: 80, left: 120, right: 120 },
  children: paragraphs.map(t =>
    new Paragraph({
      spacing: { before: 20, after: 20 },
      children: [new TextRun({ text: t, font: FONT, size: 21, bold: !!bold })],
    })
  ),
});

// =====================================================================
// Document content
// =====================================================================
const children = [];

// Title block
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { before: 200, after: 80 },
  children: [new TextRun({ text: "GAWorld 项目改进建议", font: FONT, size: 44, bold: true, color: "1F4E79" })],
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { before: 0, after: 80 },
  children: [new TextRun({ text: "面向生成式多智能体城市仿真器的工程化与可演进性优化", font: FONT, size: 24, italics: true, color: "595959" })],
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { before: 0, after: 320 },
  children: [new TextRun({ text: "版本 v1.0  |  分析对象：/Users/cw/dev/GAWorld", font: FONT, size: 20, color: "808080" })],
}));

// =====================================================================
// 1. 项目概览
// =====================================================================
children.push(H1("一、项目概览"));

children.push(P("GAWorld 是一个基于大语言模型（LLM）驱动的生成式多智能体城市仿真平台，面向城市治理、政策模拟、社会行为研究与复杂系统教学等场景。系统将智能体画像、记忆、社交影响、环境事件、政策冲击、经济行为、地图移动、平台干预评估等模块整合在一个可回放的仿真流程中。"));

children.push(H2("1.1 模块构成"));
children.push(P("项目以 Python 为主，约 15400 行源代码，主要由以下模块构成："));

// Module table
const moduleTableWidth = 9360;
const moduleCols = [3000, 4760, 1600];

const moduleTable = new Table({
  width: { size: moduleTableWidth, type: WidthType.DXA },
  columnWidths: moduleCols,
  rows: [
    new TableRow({
      tableHeader: true,
      children: [
        Cell(["模块文件"], { fill: "D9E2F3", width: moduleCols[0], bold: true }),
        Cell(["职责"], { fill: "D9E2F3", width: moduleCols[1], bold: true }),
        Cell(["代码行数"], { fill: "D9E2F3", width: moduleCols[2], bold: true }),
      ],
    }),
    ...[
      ["generative_city_sim.py", "主仿真器、CLI 入口、agent 主循环、调度、动作选择、日志、对外抓取等", "7391"],
      ["economy_module.py", "经济模块：货币、收支、资产、追求财富的行为驱动", "748"],
      ["city_map_system.py", "地图、节点、路径、瓦片渲染", "702"],
      ["environment.py", "环境事件、生成器、外部环境客户端", "683"],
      ["memory_store.py", "记忆与日志持久化、向量数据库辅助", "645"],
      ["human_realism.py", "需要、习惯、关系、记忆显著性等真实性建模", "550"],
      ["config.py", "运行配置（含多 LLM、经济、干预、人类行为等子配置）", "470"],
      ["dashboard_server.py", "本地仪表盘后端", "423"],
      ["intervention_policy.py", "推荐 / 曝光 / 立场 / 风险评估指标", "409"],
      ["life_events.py", "运行期可注入的生命事件队列", "401"],
      ["llm_providers.py", "Ollama / OpenAI / Anthropic 提供商封装与路由", "352"],
      ["distributed_comm(_server).py", "多机分布式通讯与中继服务", "292+313"],
      ["其他", "可视化、地图生成、画像生成、RAG 种子、外部环境服务等", "约 1400"],
    ].map(([n, d, l]) => new TableRow({
      children: [Cell([n], { width: moduleCols[0] }), Cell([d], { width: moduleCols[1] }), Cell([l], { width: moduleCols[2] })],
    })),
  ],
});
children.push(moduleTable);

children.push(H2("1.2 当前优点"));
children.push(Bullet("功能完整：覆盖了智能体画像、调度、行动、社交网络、记忆、习惯、需要、经济、地图、政策事件、外部 RAG、可视化、仪表盘、分布式扩展等多个层面，是一个相当完整的生成式仿真平台。"));
children.push(Bullet("多 LLM 后端：通过 LLMRouter 同时支持 Ollama、OpenAI 兼容、Anthropic 兼容三类提供商，并允许按任务（如 schedule、planning、reflection）定向路由。"));
children.push(Bullet("可状态化运行：通过 sim_state、agent_*.json、agent_*_episodes.jsonl、向量数据库等多重持久化，使得仿真可以跨日继续，并支持 reset / 兼容性版本号。"));
children.push(Bullet("钩子化扩展：HookBus 提供 on_simulation_start / on_day_start / on_agent_pre_step 等生命周期钩子，使经济模块、自定义模块可以以插件方式参与仿真。"));
children.push(Bullet("初步对照实验能力：compare-event 子命令支持事件 / 无事件并行对照，输出 stance、toxicity、misinformation 等干预指标。"));
children.push(Bullet("已建立 19 个单元测试模块，覆盖 memory、recall、习惯学习、经济、视觉化、干预等核心子系统。"));

// =====================================================================
// 2. 总体评估
// =====================================================================
children.push(H1("二、总体评估"));

children.push(P("从一个研究原型走向可持续维护的工程项目，GAWorld 当前主要受到下列三类问题的牵制："));
children.push(Bullet("结构层面：generative_city_sim.py 单文件长达 7391 行，承担了主循环、IO、HTML 抓取、调度、记忆、可视化等几乎所有逻辑，存在严重的「上帝模块」问题。"));
children.push(Bullet("可演进层面：缺少类型注解、文档字符串、Lint / Format 工具与 CI；测试虽存在，但被 mock 的 LLM 接入面狭窄，端到端流程没有受测覆盖。"));
children.push(Bullet("性能层面：智能体步循环纯串行，所有 LLM 调用同步阻塞；网络抓取使用正则解析 HTML 而非成熟解析器；向量库每次写入都打开 sqlite。"));

children.push(P("以下章节将按维度给出可操作的改进建议，并给出相对优先级（P0 高 / P1 中 / P2 低）。"));

// =====================================================================
// 3. 架构与代码组织 (P0)
// =====================================================================
children.push(H1("三、架构与代码组织（P0）"));

children.push(H2("3.1 拆分 generative_city_sim.py"));
children.push(P("当前主文件包含 200+ 个顶级函数，覆盖了不同抽象层级的关注点。建议按职责拆为以下子包，统一在 gaworld/ 下组织："));

children.push(Code("gaworld/\n  cli/                # 命令行入口（run / reset / interview / compare-event ...）\n  core/               # 主仿真循环 run_simulation()、Agent 构建、调度、状态推进\n  perception/         # perception、social_context、env_context\n  planning/            # planning、reflection、interview、daily_diary\n  action/             # action_space、choose_action、move_agent\n  memory/             # memory_store、experience_store、向量库封装\n  realism/            # human_realism、needs、habits、relationships\n  economy/            # economy_module 及对应 hook\n  intervention/       # intervention_policy 与对照实验工具\n  io/                 # 新闻抓取、RAG 注入、社交主页解析\n  vis/                # simulation_visualizer、social_network、state plot\n  llm/                # providers、router、prompts（集中管理 prompt 模板）\n  data/               # CSV / Markdown 加载与 schema 校验"));

children.push(P("拆分原则："));
children.push(Bullet("一个文件 ≤ 800 行；类与函数按职责单一原则收口。"));
children.push(Bullet("把 generative_city_sim.py 中的 HTML 抓取（_strip_html、_extract_*、fetch_news_excerpt、fetch_social_page_*）整体迁出到 gaworld/io/web_scrape.py，并替换为 BeautifulSoup + readability-lxml 的实现。"));
children.push(Bullet("将 prompt 文本统一抽取到 gaworld/llm/prompts/*.txt 或 *.j2 模板，避免大段提示词散落在 Python 字符串里，提升可审阅性与可调优性。"));

children.push(H2("3.2 引入 Agent 类"));
children.push(P("目前智能体是一个不断被各处函数读写的 dict，缺少不变量保护。建议引入数据类："));
children.push(Code("from dataclasses import dataclass, field\nfrom typing import Any\n\n@dataclass\nclass Agent:\n    id: int\n    name: str\n    profile: dict[str, Any] = field(default_factory=dict)\n    state:   dict[str, float] = field(default_factory=dict)\n    memory:  list[dict[str, Any]] = field(default_factory=list)\n    schedule: list[dict] = field(default_factory=list)\n    location: str | None = None\n    # ... 其他持久化字段\n\n    def need(self, key: str, default: float = 0.0) -> float:\n        return float(self.state.get(key, default))"));
children.push(Tip("过渡期可保留 dict-like 接口（实现 __getitem__ / __setitem__）以避免一次性大改。"));

children.push(H2("3.3 配置与依赖注入"));
children.push(P("config.py 中的 CONFIG 是单例全局字典，被 generative_city_sim.py 顶部直接读取出几十个模块级常量。这导致：测试时几乎无法切换配置；多线程 / 多进程时存在隐式共享状态；模块互相耦合。"));
children.push(Bullet("将 CONFIG 改为 dataclass + pydantic 模型（如 SimulationConfig、LLMConfig、EconomyConfig、HumanRealismConfig 等），提供 from_file() / from_env() 工厂方法。"));
children.push(Bullet("通过依赖注入把 cfg 传给 run_simulation(cfg)，禁止子模块直接 import CONFIG。"));
children.push(Bullet("覆盖优先级显式化：默认值 < dashboard_config.json < environment_config.json < 环境变量 < CLI 参数。"));
children.push(Bullet("在启动时输出一份「effective config」摘要到 output/run_<ts>/effective_config.json，便于复现。"));

// =====================================================================
// 4. LLM 集成 (P0)
// =====================================================================
children.push(H1("四、LLM 集成与提示词管理（P0）"));

children.push(H2("4.1 提供商封装存在的具体问题"));
children.push(Bullet("OllamaProvider 与 OpenAIProvider 使用 requests.models.complexjson.loads —— 这是 requests 的私有内部 API，未来版本可能移除；应改用标准库 json。"));
children.push(Bullet("失败处理仅对 401 自动切换 Authorization scheme，5xx / 429 / 网络错误没有指数退避，也没有跨提供商 fallback。"));
children.push(Bullet("没有调用次数 / token 计数 / 失败率指标，无法评估提示词与模型成本。"));
children.push(Bullet("生成被随机性影响后无法复现：即便配置 random_seed，LLM 本身随机性也未被记录。"));

children.push(H2("4.2 推荐改造"));
children.push(Bullet("封装统一的 LLMResult 对象（text、prompt_tokens、completion_tokens、provider、latency_ms、attempt、error），并通过 logging 输出到 JSONL，落盘到 output/llm_calls.jsonl。"));
children.push(Bullet("加入装饰器或中间件链：retry（tenacity）、timeout、token bucket rate limit、按 task 缓存。"));
children.push(Bullet("提供「LLM 重放模式」：将历史 LLM 调用序列写盘，回放时对相同 prompt 直接返回历史响应——使端到端测试得以确定性化。"));
children.push(Bullet("将 24 处 call_llm 调用对应的提示词模板移到 gaworld/llm/prompts/，引入 jinja2 渲染：模板变更可被 review，实验中可一次替换 prompt 集合。"));

children.push(H2("4.3 安全与凭据"));
children.push(Bullet("api_key 不应通过环境变量直接以明文打印；目前 AnthropicProvider 在 HTTPError 时会把 attempts 等信息抛出，注意脱敏 base_url 中可能携带的 token。"));
children.push(Bullet("建议引入 .env + python-dotenv，并在 README / TUTORIAL 中显式列出所需 ENV，配套提供 .env.example。"));

// =====================================================================
// 5. 性能与并发 (P1)
// =====================================================================
children.push(H1("五、性能与并发（P1）"));

children.push(P("仿真主循环目前对 agents 串行调用 perception / planning / action / reflection，每一步往往触发 4–6 次 LLM 调用，单日数百次同步等待。"));

children.push(H2("5.1 引入并发"));
children.push(Bullet("对单 tick 内的 agent 推进使用 concurrent.futures.ThreadPoolExecutor（IO bound）或 asyncio + httpx 改造 LLM provider 为协程。"));
children.push(Bullet("注意保护共享状态：social_context、agents_by_id、向量库写入需要按 agent id 分桶或加锁。"));
children.push(Bullet("将「每个 agent 内部的多次 LLM 调用」合并为单次 chain-of-thought / 工具调用，减少往返。"));

children.push(H2("5.2 持久化效率"));
children.push(Bullet("memory_store 中 _VECTOR_DB_CONN 已经做了缓存，但 save_agent_memory、save_agent_schedule 等仍是「每改一次写一次整个 JSON」。建议为 STATEFUL 写入引入差量写入或 N tick 节流（visualization.flush_every_frames 已有此模式）。"));
children.push(Bullet("vector_db.sqlite 启用 WAL：sqlite3.connect(...).execute('PRAGMA journal_mode=WAL') 与 synchronous=NORMAL，能显著提升并发写入性能。"));
children.push(Bullet("output/ 下大量小文件（每个 agent 多个 json）写入容易被 macOS 的 mds 索引拖慢。建议在 reset 时使用 shutil.rmtree 替代逐个删；运行期使用 atomic_write_json（dashboard_server.py 已有），其他模块也复用。"));

children.push(H2("5.3 HTML 抓取"));
children.push(Bullet("用 readability-lxml 或 trafilatura 替换自写正则；同时为 fetch_news_excerpt / fetch_social_page_profile_source 增加同主机限速、UA 轮换、403/404 缓存（避免反复触发 ban）。"));
children.push(Bullet("requests 调用建议统一通过 requests.Session() 并启用 keep-alive、HTTPAdapter(max_retries=...)。"));

// =====================================================================
// 6. 可靠性与错误处理 (P0)
// =====================================================================
children.push(H1("六、可靠性与错误处理（P0）"));

children.push(P("代码内出现 17 处 except Exception 捕获后不区分错误类型，部分仅 pass 或返回空。这会掩盖真正的 bug，也让长跑仿真出现的偶发异常无法被复盘。"));

children.push(Bullet("将 except Exception 收口为：精确异常类型（json.JSONDecodeError、OSError、requests.RequestException 等），其余抛出。"));
children.push(Bullet("引入统一的 logging（gaworld.log）：替换大量 print('⚠️ ...')；按级别（DEBUG / INFO / WARNING / ERROR）落盘到 output/logs/run.log。"));
children.push(Bullet("失败时记录上下文：agent_id、day、time_str、stage、prompt 片段，便于事后定位。"));
children.push(Bullet("HookBus.emit 已有 errors 收集，但 strict=False 时只是丢弃；建议至少打印 WARNING，并支持 strict 模式触发熔断。"));

children.push(H2("6.1 容错策略矩阵"));
const errCols = [2400, 3300, 3660];
const errTable = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: errCols,
  rows: [
    new TableRow({
      tableHeader: true,
      children: [
        Cell(["失败类别"], { fill: "D9E2F3", width: errCols[0], bold: true }),
        Cell(["现状"], { fill: "D9E2F3", width: errCols[1], bold: true }),
        Cell(["建议"], { fill: "D9E2F3", width: errCols[2], bold: true }),
      ],
    }),
    ...[
      ["LLM 超时 / 5xx", "被吞掉或抛出，无重试", "tenacity 指数退避 3 次；可配置跨 provider fallback"],
      ["LLM 解析失败", "fallback heuristic", "保留并记录原始响应到 output/llm_calls.jsonl 以便 prompt 调优"],
      ["新闻抓取失败", "返回空字符串", "记录 URL+ 状态码，缓存「最近失败」窗口避免循环重试"],
      ["JSON 落盘损坏", "返回 [] 或 {}", "atomic_write + .bak 双写；启动时校验并自动回滚"],
      ["分布式 relay 不可达", "本地继续，缺失消息", "熔断器 + 关键告警；可选 fail_fast"],
    ].map(([a, b, c]) => new TableRow({
      children: [
        Cell([a], { width: errCols[0] }),
        Cell([b], { width: errCols[1] }),
        Cell([c], { width: errCols[2] }),
      ],
    })),
  ],
});
children.push(errTable);

// =====================================================================
// 7. 测试与质量保证 (P0)
// =====================================================================
children.push(H1("七、测试与质量保证（P0）"));

children.push(P("当前 tests/ 下有 19 个测试文件，但："));
children.push(Bullet("19 个文件总共仅约 60 个 test_ 函数，相对 15400 行源代码偏低。"));
children.push(Bullet("test_compare_event_metrics.py 等测试只覆盖辅助函数，没有跑通 run_simulation 的最小端到端用例。"));
children.push(Bullet("没有 conftest.py 与 pytest.ini，没有覆盖率门槛，没有 CI。"));

children.push(H2("7.1 测试体系建议"));
children.push(Bullet("引入 pytest + pytest-cov + pytest-mock，并补 conftest.py 提供 mock_llm fixture（基于场景路径加载预录响应）。"));
children.push(Bullet("增加端到端 smoke：以 sim_days=1、agent_ids=[1,2]、stateful=False、LLM=mock 跑通 run_simulation()，断言 output/ 关键产物存在。"));
children.push(Bullet("为 choose_action 增加属性测试（hypothesis）：在多种 state、action_space 下结果是合法选项之一。"));
children.push(Bullet("增加 schema 测试：CSV / md profile / citymap 加载缺字段或非法值时抛出可读错误。"));
children.push(Bullet("覆盖率目标：核心模块（memory_store / human_realism / economy_module / intervention_policy）≥ 80%；其他 ≥ 50%。"));

children.push(H2("7.2 静态质量"));
children.push(Bullet("加入 ruff + black（或 ruff format）：自动统一风格、捕获 unused-import、bare except 等。"));
children.push(Bullet("分阶段加 mypy（先 strict_optional + ignore_missing_imports；再扩展到 disallow_untyped_defs）。"));
children.push(Bullet("pre-commit：black、ruff、mypy、json 格式校验、Markdown 行尾。"));

children.push(H2("7.3 持续集成"));
children.push(Bullet("增加 .github/workflows/ci.yml：在 PR 上跑 ruff + pytest + coverage（fail under 50%）。"));
children.push(Bullet("跑 LLM 相关测试时使用 mock 路径，CI 不依赖外部网络。"));
children.push(Bullet("将 requirements.txt 升级为 requirements.in + pip-tools（或 pyproject.toml + uv），固定版本以保证可复现。当前 requirements 仅 5 行，远少于实际依赖（如 sqlite3 标准库不需要，但 networkx、matplotlib 应当固定版本）。"));

// =====================================================================
// 8. 数据 & 仿真模型 (P1)
// =====================================================================
children.push(H1("八、数据与仿真模型（P1）"));

children.push(H2("8.1 关键词驱动的语义判别"));
children.push(P("intervention_policy.toxicity_keywords / misinformation_keywords / stance.positive_keywords 与 economy_module.INCOME_KEYWORDS 等大量决策依赖中文关键词列表。这导致："));
children.push(Bullet("误报率高（如「攻击」可能出现在游戏剧情）。"));
children.push(Bullet("不易扩展到其他语言或文化背景。"));
children.push(Bullet("被研究者复用时无法解释。"));

children.push(P("建议："));
children.push(Bullet("把关键词从硬编码挪到 data/keywords/*.yaml，按主题与语言组织；提供「研究者一行替换」入口。"));
children.push(Bullet("对真正影响干预指标的语义判别（toxicity / misinformation），引入轻量分类模型（fasttext / sentence-transformers）作为可选实现，关键词作为离线 fallback。"));
children.push(Bullet("对 economy_module 中的「活动→消费类目」映射，使用 embedding 相似度匹配，并允许研究者注入自定义 mapping。"));

children.push(H2("8.2 智能体状态空间一致性"));
children.push(Bullet("state 字段（energy / hunger / social_need / fatigue_debt / self_control / time_pressure / emotion / stress / mobility_intent ...）散落在多个模块中初始化与更新，没有单一来源（SoT）。建议在 Agent 类中显式声明 dataclass 字段并对每次更新执行 _clip 校验。"));
children.push(Bullet("update_state 与 update_needs 同时存在，分别由不同子系统调用，存在覆盖风险。建议合并为 needs_step()，并在 docstring 写明每个变量的物理含义、范围与更新算子。"));

children.push(H2("8.3 复现性"));
children.push(Bullet("CONFIG[\"random_seed\"] 仅用 random.seed / np.random.seed，但许多模块（economy_module、distributed_comm、environment）使用自己的 random.Random() 实例，独立种子未对齐。"));
children.push(Bullet("引入 RandomCenter：集中管理 seed → 多个命名 sub-seeds（economy、environment、scheduler、social ...）。"));
children.push(Bullet("仿真结束时输出 manifest.json，包含 seed、effective_config、git_commit、依赖版本、LLM 统计，作为「实验运行包」交付。"));

// =====================================================================
// 9. 可观测性 & 仪表盘 (P1)
// =====================================================================
children.push(H1("九、可观测性、可视化与仪表盘（P1）"));

children.push(Bullet("output/ 下已有可视化轨迹、社交网络图、状态曲线，但缺少汇总性 run report（一页 HTML 概览：本次实验关键指标、与基线 diff、agent 行为画像）。建议在 run 结束时调用 vis.render_report(run_dir) 生成 report.html。"));
children.push(Bullet("dashboard_server.py 使用 SimpleHTTPRequestHandler + ThreadingHTTPServer 自实现 API，建议在保留零依赖路径的同时，提供基于 FastAPI 的可选实现，便于未来加入鉴权、CORS、流式日志推送。"));
children.push(Bullet("引入结构化日志：每条记录形如 {ts, agent_id, day, stage, level, msg, extra}，并在 dashboard 中支持按 agent / 阶段过滤。"));
children.push(Bullet("将 LLM 调用统计、抓取统计、关键性能计数（tick 时长 P50/P95、LLM 失败率）暴露为 /metrics（Prometheus 文本格式），便于长跑监控。"));

// =====================================================================
// 10. 文档与项目治理 (P1)
// =====================================================================
children.push(H1("十、文档与项目治理（P1）"));

children.push(Bullet("README 已较为完善，但缺少「研究者复现指南」：从 git clone 到生成对照实验报告的端到端步骤；建议在 TUTORIAL.md 中增加 30 分钟可复现的最小实验。"));
children.push(Bullet("backup/ 中存有 generative_city_sim_2601115/16/17/17-2.py 等历史版本——这本应通过 git 历史保存。建议清理 backup/ 并建立 docs/changelog.md。"));
children.push(Bullet("增加 ARCHITECTURE.md：以模块依赖图（mermaid 即可）解释信息流——profile → state → schedule → planning → action → reflection → memory → next-day。"));
children.push(Bullet("AGENTS.md 描述了贡献流程，但提交信息为短小写词（updated / sync / requirement）；建议采用 Conventional Commits（feat: / fix: / refactor: / chore:），并在 PR 模板中要求「实验影响、数据兼容性、是否需 reset」。"));
children.push(Bullet("在 pyproject.toml 中定义 [project] 元数据与可选 entry_points，把 generative_city_sim.py 作为命令行入口暴露 gaworld 命令；后续可发布到内部 PyPI。"));

// =====================================================================
// 11. 安全与合规 (P1)
// =====================================================================
children.push(H1("十一、安全与合规（P1）"));

children.push(Bullet("外部抓取：load_news_sources / fetch_news_excerpt 直接对配置中的 URL 发起请求，需要：用户代理标识、robots.txt 尊重、抓取深度限制；并避免被滥用为 SSRF 入口（特别是 dashboard 后续若开放公网时）。"));
children.push(Bullet("dashboard_server.py 当前没有鉴权，subprocess 启动主仿真意味着任何能访问该端口的进程都能跑命令。在文档中明确「仅 localhost」并在绑定时默认 127.0.0.1（而非 0.0.0.0）。"));
children.push(Bullet("distributed_comm_server 与 external_environment_server 默认 host=0.0.0.0：研究环境内部部署应限定网段或加 token 鉴权。"));
children.push(Bullet("config.py 默认值中 omlx_qwen 出现 api_key=os.environ.get(\"OMLX_API_KEY\", \"omlx-local\") 这种「占位密钥」会引起静态扫描误报，建议显式 None 或通过 SecretStr 包装。"));

// =====================================================================
// 12. 路线图建议 (P0)
// =====================================================================
children.push(H1("十二、改进路线图建议"));

children.push(P("按上手难度与收益排序，建议分四个阶段推进："));

const roadCols = [1500, 2400, 5460];
const roadTable = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: roadCols,
  rows: [
    new TableRow({
      tableHeader: true,
      children: [
        Cell(["阶段"], { fill: "D9E2F3", width: roadCols[0], bold: true }),
        Cell(["主题"], { fill: "D9E2F3", width: roadCols[1], bold: true }),
        Cell(["关键交付物"], { fill: "D9E2F3", width: roadCols[2], bold: true }),
      ],
    }),
    ...[
      ["S1（1–2 周）", "卫生与基础设施", "ruff/black/mypy 接入；CI；pyproject.toml；清理 backup/；统一 logging；atomic write；requirements 固定版本；.env.example。"],
      ["S2（3–4 周）", "结构拆分", "把 generative_city_sim.py 拆为 cli/core/perception/.../io 模块；引入 Agent dataclass；config 改为 pydantic；prompt 模板外置。"],
      ["S3（4–6 周）", "性能与可靠", "ThreadPool 化 agent 步；LLM retry/缓存/计费日志；HTML 抓取替换；vector_db WAL；端到端 smoke 测试 + 覆盖率门槛。"],
      ["S4（持续）", "研究价值放大", "结构化运行 manifest；run report HTML；toxicity/misinformation 模型化；可选 FastAPI dashboard；分布式 relay 鉴权。"],
    ].map(([a, b, c]) => new TableRow({
      children: [
        Cell([a], { width: roadCols[0], bold: true }),
        Cell([b], { width: roadCols[1] }),
        Cell([c], { width: roadCols[2] }),
      ],
    })),
  ],
});
children.push(roadTable);

children.push(H2("12.1 优先级速查"));

const priCols = [1500, 6260, 1600];
const priTable = new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: priCols,
  rows: [
    new TableRow({
      tableHeader: true,
      children: [
        Cell(["优先级"], { fill: "D9E2F3", width: priCols[0], bold: true }),
        Cell(["建议项"], { fill: "D9E2F3", width: priCols[1], bold: true }),
        Cell(["所属章节"], { fill: "D9E2F3", width: priCols[2], bold: true }),
      ],
    }),
    ...[
      ["P0", "拆分主仿真器、引入 Agent 类与 pydantic 配置", "三"],
      ["P0", "替换 requests.models.complexjson、加 retry/缓存、外置 prompt", "四"],
      ["P0", "收口 except Exception，统一 logging、错误矩阵", "六"],
      ["P0", "引入 ruff/black/mypy/pytest CI、补端到端 smoke", "七"],
      ["P1", "并发化 agent 步、HTML 抓取替换、vector_db WAL", "五"],
      ["P1", "关键词改 yaml + 可选语义模型、RandomCenter、运行 manifest", "八"],
      ["P1", "结构化日志、run report HTML、可选 FastAPI dashboard", "九"],
      ["P1", "ARCHITECTURE.md、Conventional Commits、清理 backup/", "十"],
      ["P1", "Dashboard 默认 127.0.0.1、分布式 relay token、抓取合规", "十一"],
    ].map(([a, b, c]) => new TableRow({
      children: [
        Cell([a], { width: priCols[0], bold: true }),
        Cell([b], { width: priCols[1] }),
        Cell([c], { width: priCols[2] }),
      ],
    })),
  ],
});
children.push(priTable);

// =====================================================================
// 13. 结语
// =====================================================================
children.push(H1("十三、结语"));

children.push(P("GAWorld 已经具备了一个有研究价值的生成式社会仿真平台所需的多数核心能力。当前限制更多来自于工程化层面：单文件膨胀、隐式全局配置、薄测试与缺乏 CI、同步阻塞的 LLM 调用、以及关键词驱动的语义判别。"));
children.push(P("建议以「让一次实验可被同事完整复现」为核心目标推进改造："));
children.push(Bullet("可演进性：模块拆分 + 类型化 + CI = 让 6 个月后的改动是安全的。"));
children.push(Bullet("可复现性：固定版本 + 统一 random + 运行 manifest = 让一篇论文中的图表是可重做的。"));
children.push(Bullet("可解释性：结构化日志 + run report + prompt 外置 = 让仿真结果可被解读、审稿。"));
children.push(P("沿 S1→S4 推进，可在不破坏现有功能的前提下，将 GAWorld 从「优秀的研究原型」演进为「可作为长期实验平台的工具」。"));

// =====================================================================
// Build document
// =====================================================================
const doc = new Document({
  creator: "GAWorld 工程改进评估",
  title: "GAWorld 项目改进建议",
  styles: {
    default: { document: { run: { font: FONT, size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: FONT, color: "1F4E79" },
        paragraph: { spacing: { before: 360, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: FONT, color: "2E74B5" },
        paragraph: { spacing: { before: 260, after: 120 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 23, bold: true, font: FONT, color: "404040" },
        paragraph: { spacing: { before: 180, after: 100 }, outlineLevel: 2 } },
    ],
  },
  numbering: {
    config: [
      {
        reference: "bullets",
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: "•",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } },
        }],
      },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 11906, height: 16838 }, // A4
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
      },
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          alignment: AlignmentType.RIGHT,
          children: [new TextRun({ text: "GAWorld 项目改进建议", font: FONT, size: 18, color: "808080" })],
        })],
      }),
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ text: "第 ", font: FONT, size: 18, color: "808080" }),
            new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 18, color: "808080" }),
            new TextRun({ text: " 页 / 共 ", font: FONT, size: 18, color: "808080" }),
            new TextRun({ children: [PageNumber.TOTAL_PAGES], font: FONT, size: 18, color: "808080" }),
            new TextRun({ text: " 页", font: FONT, size: 18, color: "808080" }),
          ],
        })],
      }),
    },
    children,
  }],
});

Packer.toBuffer(doc).then(buf => {
  const out = process.argv[2] || "GAWorld_改进建议.docx";
  fs.writeFileSync(out, buf);
  console.log("wrote", out, buf.length, "bytes");
});
