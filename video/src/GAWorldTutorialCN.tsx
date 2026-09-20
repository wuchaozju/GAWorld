import React from 'react';
import {
  AbsoluteFill,
  Audio,
  Easing,
  Img,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

declare const process: {env: Record<string, string | undefined>};

const FPS = 30;
export const TUTORIAL_DURATION_IN_FRAMES = 7200;
const SCENE_DURATION = 720;
const VOICEOVER_ENABLED = process.env.REMOTION_ENABLE_VOICEOVER === '1';

const palette = {
  ink: '#081118',
  paper: '#f6f1e7',
  muted: '#b6c4c9',
  faint: '#73858d',
  teal: '#28c7a4',
  cyan: '#62c8f2',
  amber: '#ffb84d',
  coral: '#ff7a66',
  green: '#8fd16a',
  violet: '#b8a4ff',
  line: 'rgba(219, 235, 239, 0.18)',
  panel: 'rgba(8, 19, 27, 0.76)',
};

const titleFont = '"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Avenir Next", sans-serif';
const monoFont = '"SFMono-Regular", "Menlo", "Consolas", monospace';

const sceneTitle: React.CSSProperties = {
  margin: 0,
  color: palette.paper,
  fontFamily: titleFont,
  fontWeight: 780,
  fontSize: 64,
  lineHeight: 1.14,
  letterSpacing: 0,
};

const bodyText: React.CSSProperties = {
  color: palette.muted,
  fontFamily: titleFont,
  fontSize: 25,
  lineHeight: 1.48,
  letterSpacing: 0,
};

type SceneDef = {
  id: string;
  kicker: string;
  title: string;
  summary: string;
  accent: string;
  bullets: string[];
  code?: string[];
  diagram?: 'city' | 'loop' | 'memory' | 'routing' | 'compare' | 'outputs' | 'structure';
  image?: string;
  narration: string;
  audio: string;
};

export const tutorialScenes: SceneDef[] = [
  {
    id: 'opening',
    kicker: '01 / 项目定位',
    title: 'GAWorld 是一个可复现的城市社会行为实验场',
    summary:
      '它不是只让一组 Agent 聊天，而是把人物画像、城市地图、环境扰动、长期记忆、经济状态和 LLM 决策放进同一个可回放循环。',
    accent: palette.teal,
    bullets: [
      '研究对象：城市居民在政策、事件和社交影响下的行为变化',
      '核心目标：同一批 Agent、同一随机种子、不同条件下做对照实验',
      '主要产物：日志、记忆、轨迹、指标 CSV、可视化和访谈回答',
    ],
    image: 'gaworld-graphical-abstract.png',
    narration:
      '大家好，这段视频面向 GAWorld 的开发社区。GAWorld 的定位不是简单地跑一群智能体聊天，而是把城市居民、地图空间、社会关系、环境事件、长期记忆和模型推理，组织成一个可以复现、可以对照、可以回放的社会实验场。你可以用同一批 Agent 和同一个随机种子，比较有政策事件和没有政策事件时，城市行为系统到底发生了什么变化。',
    audio: 'voiceover/GAWorldTutorialCN/01-opening.mp3',
  },
  {
    id: 'data',
    kicker: '02 / 数据启动',
    title: 'Agent 从结构化状态、人物画像和城市地图共同启动',
    summary:
      '初始世界不是凭空生成：CSV 提供状态种子，Markdown 提供人物背景，citymap 提供位置图结构，环境配置控制外部扰动。',
    accent: palette.green,
    bullets: [
      'data/hangzhou_agents_state_init.csv：年龄、职业、健康、情绪、资金等初始状态',
      'data/hangzhou_profiles_with_names.md：人物背景、偏好、关系线索和生活叙事',
      'data/citymap.md：地点、类别、邻接关系、交通和活动空间',
      'data/environment_config.json：外部环境服务可读取的动态配置',
    ],
    code: [
      'python scripts/generate_citymap.py --description "east china city"',
      'python generative_city_sim.py create-agent-from-social --file source.txt',
    ],
    diagram: 'city',
    narration:
      '第一层是数据启动。GAWorld 的 Agent 不是在运行时随便捏出来的，而是由多个数据源共同构成。CSV 文件提供可计算的初始状态，比如年龄、职业、健康、情绪和资金。Markdown profile 提供人物叙事、偏好和关系线索。citymap 文件提供地点节点、类别和移动空间。开发者可以替换这些数据，也可以通过脚本从新的城市描述生成地图，或者从社交内容创建新的 Agent。',
    audio: 'voiceover/GAWorldTutorialCN/02-data.mp3',
  },
  {
    id: 'loop',
    kicker: '03 / 主循环',
    title: '每天的行为由感知、计划、行动、反思连续推进',
    summary:
      '主入口仍是 generative_city_sim.py。它负责编排天数、时间步、Agent 调度、LLM 调用、动作执行、记忆写入和输出生成。',
    accent: palette.cyan,
    bullets: [
      'perceive：读当前位置、事件、社交上下文和个人状态',
      'plan：生成当天日程、短期意图和可能的临时调整',
      'act：执行移动、消费、工作、社交、休息等动作',
      'reflect：更新 episode、长期总结、关系变化和习惯倾向',
    ],
    code: ['python generative_city_sim.py run', 'python generative_city_sim.py reset'],
    diagram: 'loop',
    narration:
      '第二层是主仿真循环。入口仍然是 generative_city_sim.py，它负责 CLI、天数推进、时间步调度和输出落盘。每个 Agent 在一天里会经历感知、计划、行动和反思。感知阶段读取位置、事件、社交上下文和状态。计划阶段生成日程和意图。行动阶段执行移动、消费、工作、社交或者休息。反思阶段把经历写进 episode 记忆，并影响未来的习惯和关系。',
    audio: 'voiceover/GAWorldTutorialCN/03-loop.mp3',
  },
  {
    id: 'memory',
    kicker: '04 / 记忆与真实感',
    title: '长期记忆、习惯、意图和关系让 Agent 跨天保持一致',
    summary:
      'memory_store.py 与 human_realism.py 让 Agent 不只是一次性回答，而是持续积累经历、检索上下文，并形成可观察的行为惯性。',
    accent: palette.violet,
    bullets: [
      'episode memory：保存每天发生过的关键经历',
      'long-term summary：压缩长期状态，避免上下文无限膨胀',
      'RAG recall：按 Agent 和时间检索外部补充信息',
      'habit / intention：让日程偏好和目标在多天内延续',
    ],
    code: [
      'python generative_city_sim.py rag-add --agent-id 31 --text "... "',
      'python generative_city_sim.py interview --agent-id 31 --question "为什么这样行动？"',
    ],
    diagram: 'memory',
    narration:
      'GAWorld 重要的一点是跨天一致性。memory_store.py 负责记忆持久化和向量检索，human_realism.py 负责习惯、意图、关系和人物真实感。Agent 每天产生 episode memory，系统再把长期经历压缩成 summary，避免上下文无限增长。当你添加外部 RAG 信息，或者采访某个 Agent 时，系统会把这些记忆重新带回推理上下文，因此 Agent 的回答和后续行动会受到过去经历影响。',
    audio: 'voiceover/GAWorldTutorialCN/04-memory.mp3',
  },
  {
    id: 'city',
    kicker: '05 / 城市空间与经济',
    title: '位置系统和经济系统把动作落到真实约束上',
    summary:
      'city_map_system.py 处理地点类别、路线、通勤、天气和高峰时段。economy_module.py 处理收入、税费、消费、投资、冲击和宏观周期。',
    accent: palette.amber,
    bullets: [
      '地点解析：从活动关键词映射到教育、医疗、商业、休闲、交通等类别',
      '交通成本：步行、公交、地铁、出租、私家车受距离和高峰影响',
      '个人经济：收入、个税、社保、消费结构、储蓄和投资账户',
      '宏观扰动：经济周期、通胀、裁员、加薪、医疗事件等冲击',
    ],
    diagram: 'city',
    narration:
      '第三个核心功能是把行为落到城市约束上。city_map_system.py 不再依赖硬编码地点，而是通过地点类别解析活动，比如教育、医疗、商业和休闲。移动会计算交通方式、时间成本、天气影响和高峰时段。economy_module.py 则模拟个人收入、税费、消费结构、储蓄、投资和宏观经济周期。这样，Agent 的选择不只是语言上的选择，也会影响钱、时间、位置和后续状态。',
    audio: 'voiceover/GAWorldTutorialCN/05-city-economy.mp3',
  },
  {
    id: 'dynamic',
    kicker: '06 / 动态行为与环境事件',
    title: '计划会被即时需求、社交偶遇和外部事件打断',
    summary:
      'dynamic_behavior.py 与 environment.py 让城市不是静态背景。饥饿、疲劳、消息、偶遇、天气、交通、新闻和紧急事件都可能改变行为。',
    accent: palette.coral,
    bullets: [
      'InterruptEngine：根据承诺度判断是否打断当前日程',
      'SpontaneityEngine：根据情绪和时段生成即兴活动',
      'SocialChainResolver：同地点 Agent 可能聊天、邀请或行为感染',
      'EnvironmentResponsePipeline：天气、交通、商业、新闻和应急事件触发连锁反应',
    ],
    diagram: 'loop',
    narration:
      '动态行为模块解决的是计划过于僵硬的问题。dynamic_behavior.py 会在每个时间步评估是否发生中断。比如饥饿、疲劳、时间压力、未读消息、社交偶遇，或者天气和交通事件，都可能让 Agent 改变原计划。关键设计是承诺度：考试、手术、正式会议很难被打断，个人休闲更容易被打断。这让行为既有计划性，也保留城市生活里的临场变化。',
    audio: 'voiceover/GAWorldTutorialCN/06-dynamic.mp3',
  },
  {
    id: 'llm',
    kicker: '07 / LLM 路由',
    title: '模型调用被统一封装，支持多 Provider、重试和 fallback',
    summary:
      'llm_providers.py 和配置中的 routing 负责把不同任务路由到 Ollama、OpenAI 兼容或 Anthropic 兼容接口。',
    accent: palette.cyan,
    bullets: [
      'call_llm(task=...)：主仿真器的统一模型调用入口',
      'routing.default / routing.fallback：主模型失败后自动尝试备用模型',
      '结构化日志：记录 provider、任务名、Agent、prompt 大小、耗时和结果',
      '测试建议：新功能必须 mock call_llm，避免真实网络 IO',
    ],
    code: ['from llm_providers import call_llm', 'CONFIG["llm"]["routing"]["default"] = "openai_gpt"'],
    diagram: 'routing',
    narration:
      '模型调用集中在 llm_providers.py。仿真器不应该到处直接访问某个厂商 API，而是通过 call_llm 传入任务名、Agent、prompt 和路由配置。配置里可以选择 Ollama、本地模型、OpenAI 兼容接口，或者 Anthropic 兼容接口。路由还支持 fallback，某个 provider 失败时自动尝试备用模型。做测试时，原则是 mock call_llm，不让单元测试依赖真实网络。',
    audio: 'voiceover/GAWorldTutorialCN/07-llm.mp3',
  },
  {
    id: 'compare',
    kicker: '08 / 事件对照实验',
    title: 'compare-event 是面向研究和演示最重要的接口',
    summary:
      '它会构造 baseline 和 with-event 两条分支，在相同 Agent、相同 seed 下比较状态、行为、干预指标和输出摘要。',
    accent: palette.amber,
    bullets: [
      'baseline：无事件分支，作为反事实参照',
      'with-event：注入指定时间、名称和描述的事件',
      'comparison_metrics.csv：baseline、event、delta 明细',
      'comparison_summary.md：适合直接进入报告或社区讨论',
    ],
    code: [
      'python generative_city_sim.py compare-event \\',
      '  --event-name "临时交通限行" --event-day 2 --event-time 09:00 \\',
      '  --sim-days 3 --llm-provider openai_gpt --seed 42',
    ],
    diagram: 'compare',
    narration:
      '如果只推荐一个入口，我会推荐 compare-event。它会自动创建无事件 baseline 和有事件分支，使用同一批 Agent 和同一个随机种子运行，然后汇总差异。输出里包含 comparison metrics 和 summary。这里不仅比较常规状态，也可以比较 PolicySim 风格指标，比如立场分数、风险、跨观点曝光和干预 reward。这个接口非常适合做政策情景、交通事件、公共议题传播和平台干预的演示。',
    audio: 'voiceover/GAWorldTutorialCN/08-compare.mp3',
  },
  {
    id: 'tools',
    kicker: '09 / 本地工具与输出',
    title: 'CLI、Dashboard、访谈和可视化让实验可以被检查',
    summary:
      'site/dashboard 提供本地前端，gaworld/apps 提供服务端入口，output 目录保存可复核的运行证据。',
    accent: palette.green,
    bullets: [
      'dashboard：编辑配置、profile、运行控制、记忆查看和访谈',
      'interview：对单个 Agent 提问，检查行动背后的记忆和动机',
      'serve-viz：查看轨迹回放页面和状态变化',
      'output：logs、memory、state、intervention、comparisons、plots',
    ],
    code: [
      'python generative_city_sim.py dashboard --port 8766',
      'python generative_city_sim.py serve-viz --port 8000',
    ],
    image: 'agent-state-over-time.png',
    diagram: 'outputs',
    narration:
      '实验跑完之后，最重要的是能检查证据。GAWorld 提供 CLI、Dashboard、访谈和轨迹回放。Dashboard 可以修改配置、编辑人物 profile、启动和停止仿真、查看记忆并进行访谈。output 目录保存日志、记忆、状态历史、干预指标、对照实验结果和图表。开发社区在调试新机制时，应该优先看这些可复核产物，而不是只看终端最后一行是否成功。',
    audio: 'voiceover/GAWorldTutorialCN/09-tools.mp3',
  },
  {
    id: 'structure',
    kicker: '10 / 代码结构与贡献路径',
    title: '新代码优先进入 gaworld/，根目录保持兼容入口',
    summary:
      '项目正在从历史单文件模拟器迁移到 package 结构。跨模块能力放入 gaworld/，旧入口继续服务已有脚本和研究流程。',
    accent: palette.violet,
    bullets: [
      'gaworld/settings：配置拆分、默认值和 overrides 合并',
      'gaworld/core：typed Agent adapter 与 runner 工具',
      'gaworld/io：HTTP guard、网页提取和外部输入',
      'gaworld/work：真实任务市场、队列、worker 和适配器',
      'tests/：新增功能必须覆盖，LLM 调用用 mock fixture',
    ],
    code: ['ruff check .', 'ruff format --check .', 'pytest tests', 'mypy gaworld'],
    diagram: 'structure',
    narration:
      '最后是贡献路径。这个项目仍保留 generative_city_sim.py 作为稳定入口，但新的跨模块代码应该优先进入 gaworld 目录。settings 管配置，core 放 typed Agent 和 runner，io 放网络和网页提取，work 放真实任务队列和适配器。新功能必须配测试，尤其要 mock LLM 调用，避免 CI 依赖外部 API。一个好的贡献通常从一个小实验开始：加机制，写测试，跑对照，检查 output，再把接口和文档补齐。',
    audio: 'voiceover/GAWorldTutorialCN/10-structure.mp3',
  },
];

const fade = (frame: number, start: number, end: number) =>
  interpolate(frame, [start, end], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic),
  });

const moveY = (frame: number, start: number, distance: number) =>
  interpolate(frame, [start, start + 24], [distance, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic),
  });

const Background: React.FC = () => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const drift = (frame * 0.22) % 92;

  return (
    <AbsoluteFill
      style={{
        background:
          'radial-gradient(circle at 18% 18%, rgba(40,199,164,0.2), transparent 28%), radial-gradient(circle at 82% 18%, rgba(255,184,77,0.13), transparent 24%), radial-gradient(circle at 60% 86%, rgba(98,200,242,0.15), transparent 28%), linear-gradient(180deg, #0c1820 0%, #081118 64%, #050b10 100%)',
      }}
    >
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        <defs>
          <pattern id="cn-grid" width="92" height="92" patternUnits="userSpaceOnUse" patternTransform={`translate(${drift} ${drift * 0.48})`}>
            <path d="M 92 0 L 0 0 0 92" fill="none" stroke="rgba(180,220,228,0.1)" strokeWidth="1" />
          </pattern>
        </defs>
        <rect width={width} height={height} fill="url(#cn-grid)" />
        <path
          d={`M ${width * 0.04} ${height * 0.75} C ${width * 0.28} ${height * 0.48}, ${width * 0.48} ${
            height * 0.92
          }, ${width * 0.72} ${height * 0.6} S ${width * 0.92} ${height * 0.22}, ${width * 0.97} ${height * 0.38}`}
          fill="none"
          stroke="rgba(40,199,164,0.22)"
          strokeWidth="3"
        />
      </svg>
    </AbsoluteFill>
  );
};

const Shell: React.FC<{children: React.ReactNode}> = ({children}) => (
  <AbsoluteFill style={{padding: '64px 82px 62px'}}>{children}</AbsoluteFill>
);

const Kicker: React.FC<{children: React.ReactNode; color: string}> = ({children, color}) => (
  <div
    style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 12,
      padding: '10px 16px',
      border: `1px solid ${palette.line}`,
      borderRadius: 8,
      background: 'rgba(7, 16, 22, 0.66)',
      color,
      fontFamily: titleFont,
      fontSize: 20,
      fontWeight: 760,
    }}
  >
    <span style={{width: 10, height: 10, borderRadius: 10, backgroundColor: color, boxShadow: `0 0 18px ${color}`}} />
    {children}
  </div>
);

const Panel: React.FC<{children: React.ReactNode; delay?: number; style?: React.CSSProperties}> = ({children, delay = 0, style}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({frame: frame - delay, fps, config: {damping: 220}, durationInFrames: 28});

  return (
    <div
      style={{
        border: `1px solid ${palette.line}`,
        borderRadius: 10,
        background: palette.panel,
        boxShadow: '0 24px 70px rgba(0,0,0,0.28)',
        opacity: enter,
        transform: `translateY(${interpolate(enter, [0, 1], [32, 0])}px)`,
        ...style,
      }}
    >
      {children}
    </div>
  );
};

const BulletList: React.FC<{items: string[]; accent: string}> = ({items, accent}) => {
  const frame = useCurrentFrame();

  return (
    <div style={{display: 'grid', gap: 13}}>
      {items.map((item, index) => (
        <div
          key={item}
          style={{
            display: 'grid',
            gridTemplateColumns: '32px 1fr',
            gap: 14,
            alignItems: 'start',
            opacity: fade(frame, 34 + index * 7, 48 + index * 7),
            transform: `translateY(${moveY(frame, 34 + index * 7, 18)}px)`,
          }}
        >
          <span
            style={{
              width: 20,
              height: 20,
              marginTop: 7,
              borderRadius: 6,
              background: accent,
              boxShadow: `0 0 18px ${accent}66`,
            }}
          />
          <span style={{...bodyText, fontSize: 24, color: palette.paper}}>{item}</span>
        </div>
      ))}
    </div>
  );
};

const CodeBlock: React.FC<{lines: string[]; delay?: number}> = ({lines, delay = 58}) => {
  const frame = useCurrentFrame();
  const text = lines.join('\n');
  const reveal = Math.floor(
    interpolate(frame, [delay, delay + 70], [0, text.length], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    }),
  );

  return (
    <Panel style={{padding: 22, background: 'rgba(4, 10, 15, 0.92)'}} delay={delay - 8}>
      <div style={{display: 'flex', gap: 9, marginBottom: 18}}>
        {[palette.coral, palette.amber, palette.green].map((color) => (
          <span key={color} style={{width: 13, height: 13, borderRadius: 13, background: color}} />
        ))}
      </div>
      <pre
        style={{
          margin: 0,
          whiteSpace: 'pre-wrap',
          color: '#d8fff1',
          fontFamily: monoFont,
          fontSize: 22,
          lineHeight: 1.5,
        }}
      >
        {text.slice(0, reveal)}
        {reveal < text.length ? <span style={{opacity: frame % 18 < 9 ? 1 : 0}}>▌</span> : null}
      </pre>
    </Panel>
  );
};

const Diagram: React.FC<{type?: SceneDef['diagram']; accent: string; image?: string}> = ({type, accent, image}) => {
  if (image) {
    return (
      <Panel delay={12} style={{padding: 20}}>
        <Img src={staticFile(image)} style={{width: '100%', height: 312, objectFit: 'cover', borderRadius: 8}} />
      </Panel>
    );
  }

  if (type === 'loop') {
    return <LoopDiagram accent={accent} />;
  }
  if (type === 'routing') {
    return <RoutingDiagram accent={accent} />;
  }
  if (type === 'compare') {
    return <CompareDiagram accent={accent} />;
  }
  if (type === 'structure') {
    return <StructureDiagram accent={accent} />;
  }
  if (type === 'outputs') {
    return <OutputsDiagram accent={accent} />;
  }
  if (type === 'memory') {
    return <MemoryDiagram accent={accent} />;
  }
  return <CityDiagram accent={accent} />;
};

const MiniNode: React.FC<{label: string; color: string; delay: number}> = ({label, color, delay}) => {
  const frame = useCurrentFrame();
  const opacity = fade(frame, delay, delay + 16);
  return (
    <div
      style={{
        padding: '17px 18px',
        borderRadius: 8,
        border: `1px solid ${palette.line}`,
        background: 'rgba(255,255,255,0.045)',
        color: palette.paper,
        fontFamily: titleFont,
        fontSize: 22,
        fontWeight: 720,
        opacity,
        transform: `translateY(${moveY(frame, delay, 18)}px)`,
      }}
    >
      <span style={{display: 'inline-block', width: 10, height: 10, borderRadius: 10, background: color, marginRight: 10}} />
      {label}
    </div>
  );
};

const LoopDiagram: React.FC<{accent: string}> = ({accent}) => (
  <Panel delay={12} style={{padding: 26}}>
    <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16}}>
      {['感知 context', '计划 schedule', '行动 action', '反思 memory'].map((label, index) => (
        <MiniNode key={label} label={label} color={[accent, palette.cyan, palette.amber, palette.coral][index]} delay={18 + index * 8} />
      ))}
    </div>
    <div style={{...bodyText, marginTop: 24, fontSize: 22}}>每个时间步写入状态；每天结束时压缩记忆，并影响下一天的 routine。</div>
  </Panel>
);

const CityDiagram: React.FC<{accent: string}> = ({accent}) => (
  <Panel delay={12} style={{padding: 26}}>
    <div style={{display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14}}>
      {['居住区', '学校', '医院', '商圈', '公园', '交通枢纽'].map((label, index) => (
        <MiniNode key={label} label={label} color={index % 2 === 0 ? accent : palette.cyan} delay={18 + index * 5} />
      ))}
    </div>
    <div style={{...bodyText, marginTop: 22, fontSize: 22}}>地点不是背景图，而是会参与路线、成本、活动匹配和社交偶遇。</div>
  </Panel>
);

const MemoryDiagram: React.FC<{accent: string}> = ({accent}) => (
  <Panel delay={12} style={{padding: 26}}>
    {['episode log', 'long-term summary', 'RAG recall', 'habit + intention', 'relationship drift'].map((label, index) => (
      <MiniNode key={label} label={label} color={index === 0 ? accent : [palette.teal, palette.cyan, palette.amber, palette.coral][index - 1]} delay={16 + index * 8} />
    ))}
  </Panel>
);

const RoutingDiagram: React.FC<{accent: string}> = ({accent}) => (
  <Panel delay={12} style={{padding: 26}}>
    {['task name', 'routing.default', 'provider call', 'retry + fallback', 'structured log'].map((label, index) => (
      <MiniNode key={label} label={label} color={index === 2 ? accent : palette.cyan} delay={16 + index * 8} />
    ))}
  </Panel>
);

const CompareDiagram: React.FC<{accent: string}> = ({accent}) => (
  <Panel delay={12} style={{padding: 26}}>
    <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16}}>
      <MiniNode label="without_event" color={palette.cyan} delay={18} />
      <MiniNode label="with_event" color={accent} delay={28} />
    </div>
    <div style={{height: 1, background: palette.line, margin: '22px 0'}} />
    {['comparison_metrics.csv', 'comparison_summary.md', 'intervention_metrics.csv'].map((label, index) => (
      <MiniNode key={label} label={label} color={index === 1 ? palette.green : palette.violet} delay={42 + index * 8} />
    ))}
  </Panel>
);

const OutputsDiagram: React.FC<{accent: string}> = ({accent}) => (
  <Panel delay={12} style={{padding: 26}}>
    {['output/logs', 'output/memory', 'output/state', 'output/intervention', 'output/comparisons'].map((label, index) => (
      <MiniNode key={label} label={label} color={index === 0 ? accent : palette.teal} delay={16 + index * 7} />
    ))}
  </Panel>
);

const StructureDiagram: React.FC<{accent: string}> = ({accent}) => (
  <Panel delay={12} style={{padding: 26}}>
    {['generative_city_sim.py', 'gaworld/settings', 'gaworld/core', 'gaworld/io', 'gaworld/work', 'tests'].map((label, index) => (
      <MiniNode key={label} label={label} color={index === 0 ? palette.amber : index === 5 ? accent : palette.cyan} delay={16 + index * 6} />
    ))}
  </Panel>
);

const Scene: React.FC<{scene: SceneDef; index: number}> = ({scene, index}) => {
  const frame = useCurrentFrame();
  const progress = Math.min(1, Math.max(0, frame / SCENE_DURATION));
  const chapter = `${String(index + 1).padStart(2, '0')} / ${tutorialScenes.length}`;

  return (
    <Shell>
      <div
        style={{
          position: 'absolute',
          top: 28,
          right: 82,
          color: palette.faint,
          fontFamily: monoFont,
          fontSize: 20,
        }}
      >
        {chapter}
      </div>
      <div style={{display: 'grid', gridTemplateColumns: '1.06fr 0.94fr', gap: 34, height: 816}}>
        <div>
          <div style={{opacity: fade(frame, 0, 18), transform: `translateY(${moveY(frame, 0, 28)}px)`}}>
            <Kicker color={scene.accent}>{scene.kicker}</Kicker>
            <h1 style={{...sceneTitle, marginTop: 24, maxWidth: 900}}>{scene.title}</h1>
            <div style={{...bodyText, marginTop: 22, maxWidth: 890}}>{scene.summary}</div>
          </div>
          <Panel delay={22} style={{marginTop: 28, padding: 24}}>
            <BulletList items={scene.bullets} accent={scene.accent} />
          </Panel>
        </div>
        <div style={{display: 'grid', gridTemplateRows: scene.code ? 'auto 1fr' : '1fr', gap: 20, alignContent: 'start'}}>
          <Diagram type={scene.diagram} accent={scene.accent} image={scene.image} />
          {scene.code ? <CodeBlock lines={scene.code} /> : null}
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          left: 82,
          right: 82,
          bottom: 24,
          display: 'grid',
          gridTemplateColumns: '1fr 160px',
          gap: 24,
          alignItems: 'end',
        }}
      >
        <div
          style={{
            borderLeft: `4px solid ${scene.accent}`,
            paddingLeft: 18,
            color: palette.paper,
            fontFamily: titleFont,
            fontSize: 24,
            lineHeight: 1.44,
            opacity: fade(frame, 18, 38),
          }}
        >
          {scene.narration}
        </div>
        <div style={{height: 8, borderRadius: 8, background: 'rgba(255,255,255,0.1)', overflow: 'hidden'}}>
          <div style={{height: '100%', width: `${progress * 100}%`, background: scene.accent}} />
        </div>
      </div>
    </Shell>
  );
};

const Voiceover: React.FC = () => {
  if (!VOICEOVER_ENABLED) {
    return null;
  }

  return (
    <>
      {tutorialScenes.map((scene, index) => (
        <Sequence key={scene.id} from={index * SCENE_DURATION}>
          <Audio src={staticFile(scene.audio)} volume={0.96} />
        </Sequence>
      ))}
    </>
  );
};

export const GAWorldTutorialCN: React.FC = () => {
  return (
    <AbsoluteFill style={{backgroundColor: palette.ink}}>
      <Background />
      <Voiceover />
      {tutorialScenes.map((scene, index) => (
        <Sequence key={scene.id} from={index * SCENE_DURATION} durationInFrames={SCENE_DURATION} premountFor={30}>
          <Scene scene={scene} index={index} />
        </Sequence>
      ))}
      <div
        style={{
          position: 'absolute',
          left: 82,
          top: 26,
          color: palette.faint,
          fontFamily: monoFont,
          fontSize: 18,
        }}
      >
        {Math.round(TUTORIAL_DURATION_IN_FRAMES / FPS)}s · AI voiceover ready
      </div>
    </AbsoluteFill>
  );
};
