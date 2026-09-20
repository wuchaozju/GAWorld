# GAWorld Website Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and publish a bilingual GAWorld project website that turns research credibility into GitHub visits and successful first runs.

**Architecture:** Create an isolated Sites/Vinext frontend under `website/` so the existing Python simulator and static tools remain unchanged. A single client page renders typed bilingual content, lightweight CSS-based simulation visuals, local language preference, and resilient command-copy behavior; repository-grounded links and commands remain static.

**Tech Stack:** Sites starter, Vinext, React, TypeScript, CSS, Vitest/Testing Library, Cloudflare Worker-compatible ESM.

---

## File Map

- `website/app/layout.tsx` — site metadata, fonts, Open Graph metadata, and root document language.
- `website/app/page.tsx` — single-page section composition and client interactions.
- `website/app/content.ts` — typed Chinese and English copy plus repository-grounded URLs and commands.
- `website/app/globals.css` — visual system, responsive layout, animation, focus, and reduced-motion rules.
- `website/app/page.test.tsx` — localization, navigation, CTA, and clipboard resilience tests.
- `website/public/og.png` — validated, bespoke social preview matching the final page.
- `website/.openai/hosting.json` — Sites deployment configuration created by the initializer.

### Task 1: Initialize the isolated Sites application

**Files:**
- Create: `website/`
- Verify: `website/app/page.tsx`
- Verify: `website/app/layout.tsx`
- Verify: `website/app/globals.css`
- Verify: `website/.openai/hosting.json`

- [ ] **Step 1: Initialize the Sites starter**

Run the Sites plugin initializer with `/Users/cw/dev/GAWorld/website` as the target. Retain the installation session until it completes and do not run another initializer.

- [ ] **Step 2: Start the development preview**

Run: `npm run dev`

Working directory: `/Users/cw/dev/GAWorld/website`

Expected: the server prints one healthy Local URL and the starter loading screen renders there.

- [ ] **Step 3: Verify the generated project surface**

Run: `rg --files app .openai public | sort`

Expected: `app/page.tsx`, `app/layout.tsx`, `app/globals.css`, and `.openai/hosting.json` exist.

- [ ] **Step 4: Commit the isolated starter**

```bash
git add website
git commit -m "add gaworld website starter"
```

### Task 2: Add typed bilingual project content

**Files:**
- Create: `website/app/content.ts`
- Create: `website/app/content.test.ts`

- [ ] **Step 1: Write failing content parity tests**

```ts
import { describe, expect, it } from "vitest";
import { CONTENT, QUICK_START, REPOSITORY_URL } from "./content";

describe("GAWorld content", () => {
  it("keeps Chinese and English section keys aligned", () => {
    expect(Object.keys(CONTENT.zh)).toEqual(Object.keys(CONTENT.en));
  });

  it("uses the canonical repository and documented commands", () => {
    expect(REPOSITORY_URL).toBe("https://github.com/wuchaozju/GAWorld");
    expect(QUICK_START).toEqual([
      "pip install -r requirements.txt",
      "python generative_city_sim.py run",
    ]);
  });
});
```

- [ ] **Step 2: Run the test and verify the expected failure**

Run: `npm test -- app/content.test.ts --run`

Expected: FAIL because `app/content.ts` does not exist.

- [ ] **Step 3: Implement the content model**

Create `content.ts` with:

```ts
export const REPOSITORY_URL = "https://github.com/wuchaozju/GAWorld";
export const QUICK_START = [
  "pip install -r requirements.txt",
  "python generative_city_sim.py run",
] as const;

export type Locale = "zh" | "en";
export type Capability = { title: string; research: string; developer: string };
export type PageCopy = {
  nav: { capabilities: string; architecture: string; quickStart: string; github: string };
  hero: { eyebrow: string; title: string; body: string; github: string; run: string };
  signals: string[];
  loop: { title: string; body: string; steps: string[] };
  capabilities: { title: string; body: string; items: Capability[] };
  scenarios: { title: string; items: { title: string; body: string }[] };
  quickStart: { title: string; body: string; copy: string; copied: string; manual: string };
  architecture: { title: string; body: string; modules: { title: string; body: string }[] };
  openSource: { eyebrow: string; title: string; body: string; github: string; docs: string; dashboard: string };
  footer: string;
};

export const CONTENT: Record<Locale, PageCopy> = {
  zh: {
    nav: { capabilities: "核心能力", architecture: "系统架构", quickStart: "快速开始", github: "GitHub" },
    hero: { eyebrow: "生成式城市社会实验沙盒", title: "让一座城市成为可重放、可干预、可比较的社会实验。", body: "GAWorld 将长期记忆、社会影响、环境事件、政策冲击、闭环经济与 LLM 决策组合成可检查的多智能体仿真工作流。", github: "在 GitHub 查看", run: "一分钟运行" },
    signals: ["长期智能体记忆", "社会网络演化", "政策与环境冲击", "闭环经济", "地图化行动", "可回放轨迹"],
    loop: { title: "从感知到记忆的持续循环", body: "每个智能体在环境与社会关系中行动，并让经历持续改变之后的选择。", steps: ["感知", "规划", "行动", "反思", "记忆更新"] },
    capabilities: { title: "为研究可控，为开发可用", body: "同一套模块既支撑反事实实验，也提供可扩展的工程边界。", items: [
      { title: "记忆与行为一致性", research: "研究跨日经历如何改变意图、习惯与关系。", developer: "检查情景记忆、长期摘要、习惯与意图产物。" },
      { title: "社会与政策干预", research: "比较事件、推荐暴露与政策冲击的反事实结果。", developer: "通过可配置事件和干预模块复现实验。" },
      { title: "空间与经济系统", research: "观察通勤、拥挤、消费、税收与宏观周期的联动。", developer: "组合城市地图、位置系统和资金守恒经济模块。" },
    ] },
    scenarios: { title: "把复杂社会问题变成可运行实验", items: [
      { title: "城市治理", body: "比较交通限制、公共服务与突发事件下的群体响应。" },
      { title: "社会传播", body: "研究情绪、风险、观点与关系网络中的扩散。" },
      { title: "行为一致性", body: "评估长期记忆、习惯和人格状态对决策的影响。" },
      { title: "复杂系统教学", body: "用可检查轨迹展示微观行为如何形成宏观结果。" },
    ] },
    quickStart: { title: "一分钟启动你的第一座城市", body: "安装依赖，然后运行默认仿真。", copy: "复制", copied: "已复制", manual: "请手动选择并复制命令" },
    architecture: { title: "一座城市，多个可组合系统", body: "智能体通过环境感知、社会关系和经济约束行动，再把结果写回记忆。", modules: [
      { title: "Agent Core", body: "身份、状态与并发执行" }, { title: "Memory", body: "经历、习惯、意图与总结" }, { title: "Environment", body: "天气、事件、位置与异常" }, { title: "Social", body: "关系、影响与群体传播" }, { title: "Economy", body: "收入、消费、税收、信用与周期" }, { title: "Policy", body: "干预、暴露与反事实指标" },
    ] },
    openSource: { eyebrow: "OPEN SOURCE", title: "从代码开始理解这座城市", body: "阅读架构，运行默认仿真，再用自己的智能体、事件和政策扩展 GAWorld。", github: "打开 GitHub", docs: "阅读项目文档", dashboard: "启动本地 Dashboard" },
    footer: "GAWorld · Generative multi-agent simulation for urban social behavior experiments.",
  },
  en: {
    nav: { capabilities: "Capabilities", architecture: "Architecture", quickStart: "Quick start", github: "GitHub" },
    hero: { eyebrow: "A generative urban social experiment sandbox", title: "Turn a city into a replayable, intervenable, comparable social experiment.", body: "GAWorld combines long-term memory, social influence, environmental events, policy shocks, a closed-loop economy, and LLM decisions in an inspectable multi-agent workflow.", github: "View on GitHub", run: "Run in one minute" },
    signals: ["Long-term memory", "Evolving social graph", "Policy and event shocks", "Closed-loop economy", "Map-based action", "Replayable traces"],
    loop: { title: "A continuous loop from perception to memory", body: "Agents act inside an environment and social graph, then carry each experience into later choices.", steps: ["Perceive", "Plan", "Act", "Reflect", "Update memory"] },
    capabilities: { title: "Controlled for research. Practical for builders.", body: "The same modules support counterfactual experiments and clear extension points.", items: [
      { title: "Memory and consistency", research: "Study how experiences reshape intentions, habits, and relationships across days.", developer: "Inspect episodic memory, long-term summaries, habits, and intentions." },
      { title: "Social and policy intervention", research: "Compare counterfactual outcomes under events, exposure, and policy shocks.", developer: "Reproduce experiments through configurable event and intervention modules." },
      { title: "Spatial and economic systems", research: "Observe interactions among commuting, crowding, spending, taxation, and macro cycles.", developer: "Compose the city map, location system, and money-conserving economy." },
    ] },
    scenarios: { title: "Turn complex social questions into runnable experiments", items: [
      { title: "Urban governance", body: "Compare group responses to mobility restrictions, services, and emergencies." },
      { title: "Social propagation", body: "Study the spread of emotion, risk, opinion, and influence through relationships." },
      { title: "Behavioral consistency", body: "Evaluate how memory, habits, and personal state shape decisions." },
      { title: "Complex-systems education", body: "Use inspectable traces to show how micro behavior produces macro outcomes." },
    ] },
    quickStart: { title: "Launch your first city in one minute", body: "Install the dependencies, then run the default simulation.", copy: "Copy", copied: "Copied", manual: "Select and copy the command manually" },
    architecture: { title: "One city, multiple composable systems", body: "Agents act through environmental perception, social ties, and economic constraints, then write outcomes back to memory.", modules: [
      { title: "Agent Core", body: "Identity, state, and concurrent execution" }, { title: "Memory", body: "Experience, habits, intentions, and summaries" }, { title: "Environment", body: "Weather, events, locations, and anomalies" }, { title: "Social", body: "Relationships, influence, and propagation" }, { title: "Economy", body: "Income, spending, tax, credit, and cycles" }, { title: "Policy", body: "Intervention, exposure, and counterfactual metrics" },
    ] },
    openSource: { eyebrow: "OPEN SOURCE", title: "Understand the city from its code", body: "Read the architecture, run the default simulation, then extend GAWorld with your own agents, events, and policies.", github: "Open GitHub", docs: "Read project docs", dashboard: "Launch local Dashboard" },
    footer: "GAWorld · Generative multi-agent simulation for urban social behavior experiments.",
  },
};
```

- [ ] **Step 4: Run content tests**

Run: `npm test -- app/content.test.ts --run`

Expected: PASS (2 tests).

- [ ] **Step 5: Commit bilingual content**

```bash
git add website/app/content.ts website/app/content.test.ts
git commit -m "add bilingual gaworld content"
```

### Task 3: Build the accessible single-page experience

**Files:**
- Replace: `website/app/page.tsx`
- Replace: `website/app/globals.css`
- Create: `website/app/page.test.tsx`
- Delete: `website/app/_sites-preview/`

- [ ] **Step 1: Write failing interaction tests**

Test that the page initially renders the browser-preferred locale, switches all primary CTA text when the locale button is pressed, persists `gaworld-locale`, exposes `#capabilities`, `#architecture`, and `#quick-start` landmarks, and falls back to the manual-copy message when `navigator.clipboard.writeText` rejects.

```tsx
it("switches locale and persists the choice", async () => {
  render(<Home />);
  await userEvent.click(screen.getByRole("button", { name: /English/i }));
  expect(screen.getByRole("link", { name: "View on GitHub" })).toBeVisible();
  expect(localStorage.getItem("gaworld-locale")).toBe("en");
});

it("keeps commands usable when clipboard access fails", async () => {
  vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("denied"));
  render(<Home />);
  await userEvent.click(screen.getAllByRole("button", { name: "复制" })[0]);
  expect(screen.getByText("请手动选择并复制命令")).toBeVisible();
});
```

- [ ] **Step 2: Run tests and verify failure**

Run: `npm test -- app/page.test.tsx --run`

Expected: FAIL because the starter does not provide the GAWorld interactions.

- [ ] **Step 3: Implement the page composition**

Implement `page.tsx` as a client component with `locale`, `copyStatus`, and the following semantic structure: skip link; header with anchor navigation, GitHub link, and locale toggle; main containing hero, credibility strip, core loop, capabilities, scenarios, quick start, architecture, and open-source CTA; footer. Map repeated content from `CONTENT[locale]`. Use `aria-live="polite"` for copy feedback and `<code>` for every command.

The locale initialization order is saved preference, then `navigator.language`, then Chinese. The clipboard handler catches failures and sets the `manual` message without removing the selectable command.

- [ ] **Step 4: Implement the visual and responsive system**

Replace `globals.css` with design tokens for ink/navy surfaces, cyan and amber accents, readable foreground colors, max-width containers, responsive grids, visible `:focus-visible`, and a CSS-only hero city network. Define all ambient animation inside `@media (prefers-reduced-motion: no-preference)` and simplify the architecture to one column below 720px.

- [ ] **Step 5: Remove starter-only assets and dependency**

Delete `app/_sites-preview` and remove `react-loading-skeleton` if no remaining file imports it. Refresh the existing lockfile with the starter's package manager.

- [ ] **Step 6: Run interaction tests**

Run: `npm test -- app/page.test.tsx --run`

Expected: PASS for locale persistence, CTA translation, section landmarks, and clipboard fallback.

- [ ] **Step 7: Commit the finished page**

```bash
git add website/app website/package.json website/package-lock.json
git commit -m "build gaworld project website"
```

### Task 4: Add site metadata and social preview

**Files:**
- Modify: `website/app/layout.tsx`
- Create: `website/public/og.png`

- [ ] **Step 1: Replace starter metadata**

Set the title to `GAWorld — Generative Urban Social Simulation` and describe GAWorld as a replayable, intervenable multi-agent simulator. Add Open Graph and X card metadata with an absolute image URL derived from the incoming request host. Do not retain the starter `codex-preview` marker.

- [ ] **Step 2: Generate exactly one bespoke social card**

Create a 1200×630 landscape image using the final ink-blue, cyan, and amber visual language. It must contain the exact text `GAWorld` and `Generative Urban Social Simulation`, with an abstract city-agent network and no invented metrics, logos, or claims.

- [ ] **Step 3: Inspect and wire the social card**

Inspect the returned image at original detail. If either required text string is incorrect, retry once. Save a valid result to `website/public/og.png`; if neither result is valid, omit all `og:image` and X image fields.

- [ ] **Step 4: Commit metadata**

```bash
git add website/app/layout.tsx website/public/og.png
git commit -m "add gaworld site metadata"
```

### Task 5: Validate and publish

**Files:**
- Verify: `website/.openai/hosting.json`
- Verify: `website/app/page.tsx`
- Verify: `website/app/globals.css`

- [ ] **Step 1: Run the complete test suite**

Run: `npm test -- --run`

Expected: all content and interaction tests pass.

- [ ] **Step 2: Run the production build**

Run: `npm run build`

Expected: exit code 0 with Cloudflare Worker-compatible output and no TypeScript errors.

- [ ] **Step 3: Check required content and forbidden starter markers**

Run: `rg -n "GAWorld|generative_city_sim.py|wuchaozju/GAWorld" app && ! rg -n "codex-preview|_sites-preview" app`

Expected: all required project strings are present and the forbidden marker scan returns no matches.

- [ ] **Step 4: Publish with Sites**

Invoke the `sites-hosting` workflow from `/Users/cw/dev/GAWorld/website`, keep the development preview alive until deployment finishes, and capture the deployed URL.

- [ ] **Step 5: Stop the local preview and report the result**

Stop the retained development session only after hosting succeeds. Return the deployed Sites URL as the primary deliverable and include the GitHub repository URL as the secondary link.

- [ ] **Step 6: Commit any deployment-owned configuration changes**

```bash
git add website/.openai/hosting.json
git commit -m "configure gaworld site hosting"
```
