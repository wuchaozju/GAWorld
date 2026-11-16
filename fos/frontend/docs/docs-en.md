# FOS Documentation

<h2 id="getting-started">Getting Started with FOS</h2>

FOS (Future of Society) is an online social simulation platform that runs in your browser — no download needed. Create simulations with AI-powered agents, watch them interact in a tree-based experiment structure, and analyze the results.

### Create your FOS account

1. Open the FOS homepage and click **Register**.
2. Fill in your email, username, organization, and password. Write down your password — FOS does not support password recovery.
3. Submit and log in.

### Your first FOS simulation

1. On the FOS dashboard, click **Launch Experiment**.
2. Choose a scenario from the library — FOS has 16 supported scenarios across 5 categories (game theory, sociology, discussion, spatial, generative city).
3. Step through the 6-step Experiment Builder wizard (Choose Scenario → Configure → Actions → Agents → Network → Review).
4. Click **Launch** to create and start your simulation.

### Watch FOS agents interact

1. The simulation opens in the **Workspace** tab. On the left (left side) you see the **SimTree** — a vertical tree visualization of your experiment's nodes.
2. On the right (right side) you see the **LogViewer**, showing agent conversations in real time.
3. Click **Advance** on any node to create a child node — the simulation progresses one round and agents respond. You can branch from any node to explore alternative paths.

---

<h2 id="llm-config">Setting Up LLMs in FOS</h2>

FOS needs at least one LLM provider so agents can think and talk. You can also set up a search provider so agents can look up external information.

### Open LLM settings

Go to **Settings → LLM Providers** in the FOS navigation bar, then click **Add provider**.

### Choose how to connect

**Option A — Official API** (needs stable international internet)

Fill in the FOS provider form:
- **Provider**: OpenAI or Gemini
- **API Key**: Get one from [OpenAI](https://auth.openai.com/log-in) or [Google AI Studio](https://aistudio.google.com/api-keys)
- **Base URL**: Usually `https://api.openai.com/v1`
- **Model**: e.g. `gpt-4o-mini` or `gemini-1.5-flash-latest`

![LLM provider configuration in FOS](/tutorial/01-overview.png)

**Option B — API relay** (recommended for mainland China)

Use a relay like [OpenRouter](https://openrouter.ai/). Select **OpenAI-compatible** as provider and paste the relay's API Key, Base URL, and model name.

![API relay configuration in FOS](/tutorial/02-dashboard.png)

### Test and save

Click **Test connectivity** in FOS. If it works, save the provider.

### (Optional) Add a search provider

Go to **Settings → Search Providers** in FOS. Configure Serper, SerpAPI, or Tavily with your API Key and Base URL.

---

<h2 id="creating-simulation">Creating a FOS Simulation</h2>

A simulation is an experiment where AI agents interact under conditions you define. FOS uses a tree-based experiment model: each advance creates a child node, and you can branch from any node to explore alternative paths.

### Start a new simulation

On the FOS dashboard or the top navigation bar, click **Launch Experiment**, or go to **New Simulation** from the dashboard's Desk Lab section.

![Starting a new simulation in FOS](/tutorial/03-new-simulation.png)

### Pick a scenario

FOS includes 18 scenario definitions across 5 categories. 16 are fully supported and ready to use:

| Category | Scenarios |
|---|---|
| **Game Theory** | Prisoner's Dilemma, Battle of the Sexes, Stag Hunt, Public Goods Game, Coordination Game |
| **Sociology** | Social Norm Disruption, Policy Meaning Erosion, Echo Chamber, Resource Scarcity, Xihu Yilianbao Enrollment Diffusion |
| **Discussion** | Open Discussion, Council Chamber |
| **Spatial** | Grid World, Contagion Spread |
| **Generative City** | GAWorld |
| **Custom** | Custom Scenario (build your own) |

The frontend also offers 6 **system templates** with pre-built agent sets: Social Norm Disruption, Policy Diffusion with Meaning Erosion, Polarization & Digital Echo Chambers, Resource Scarcity & Social Contract, Village Governance, and Council Chamber.

### Configure your experiment

1. Give your experiment a name and optionally set time configuration.
2. Adjust scenario-specific parameters that appear based on your chosen scenario.
3. Click **Next** to move through the wizard steps.

---

<h2 id="agents">Configuring FOS Agents</h2>

Agents are the people inside your simulation. FOS gives you three methods to populate your experiment, and each agent type can use its own LLM provider for stratified model distribution.

### Manual configuration

Define agent types yourself — set their label, count, role prompt, user profile, custom properties, and optional LLM provider. Each agent type can have a different provider, allowing you to assign different models to different roles (e.g., GPT-4o for leaders, GPT-4o-mini for followers).

### Demographic generation (AI-powered)

1. Click **Demographic Generation** in the Experiment Builder.
2. Set demographic categories (age, occupation), archetype probabilities, and trait distributions on a 0–100 scale.
3. Enter the total number of agents and select a provider for generation.
4. Click **Generate** — FOS calls the LLM to create realistic agent profiles with names, roles, avatars, and backgrounds.
5. Preview the generated list and save.

![Agent generation interface in FOS](/tutorial/04-agent-generation.png)

### File import

Upload a CSV or JSON file with agent definitions. FOS parses it automatically to populate your experiment.

### System template agents

The 6 system templates include pre-generated agent sets tailored to each scenario. For example, the Policy Diffusion template creates 20 agents with a 3-tier structure (top-level publishers, mid-level communicators, base-level recipients). You can use these as-is or customize them further.

### Create your simulation

Review your agents, make any final tweaks, and click **Launch** to create the simulation and enter the FOS simulation view.

![Simulation view in FOS](/tutorial/05-simulation-view.png)

---

<h2 id="running-analysis">Running & Analyzing in FOS</h2>

This is where you run your experiment and study the results — all inside the FOS simulation interface.

### The simulation interface

The simulation page has 4 tabs accessed via the **TabRail** on the left:

- **Workspace** — The main view. Left panel (left side) shows the **SimTree** (tree of simulation nodes). Right panel (right side) shows the **LogViewer** (agent conversations) or **ComparisonView** (when comparing branches).

![Host panel and agent conversations in FOS](/tutorial/06-host-panel.png)
- **Agents** — A sidebar listing all agents with their profiles and current state.
- **Intervention** — Tools for injecting events or modifying conditions mid-simulation.
- **Analyse** — Analytics and metrics dashboards.

### Tree-based simulation model

FOS simulates in a **tree structure**, not a simple linear sequence:

- **Advance** creates a **child node** from any current node. Each advance runs one round: agents are prompted according to the visibility mode, their responses are processed, and payoffs are calculated.
- **Branch** creates a **sibling fork** from any node, letting you run parallel alternatives from the same starting point.
- You can delete subtrees (except the root) to prune unwanted branches.
- **Auto-advance** runs repeated advances with a configurable delay, great for unattended long runs.

### Four visibility modes

FOS supports 4 modes that control what agents see each round:

| Mode | Behavior |
|---|---|
| **Simultaneous** | All agents prompted concurrently (capped by LLM concurrency limit). No agent sees others' current-round decisions. |
| **Sequential** | Agents prompted one at a time. Each sees the choices of agents who went before them in the current round. |
| **Random** | Agent order is shuffled randomly each round before sequential prompting. |
| **Paired** | Random pairs formed each round; agents within each pair interact. |

![Experiment design in FOS](/tutorial/07-experiment-design.png)

### Filter what you see

Use the **Filter** controls in the LogViewer to narrow down logs by agent, event type, or round range.

### Generate an AI analysis report

Click **Analysis Report** to open the Report modal. FOS generates AI-powered analysis reports with configurable settings:
- **Sections**: Executive Summary, Key Events, Suggestions, Agent Analysis, Multimodal Thumbnails
- **Settings**: max events, sample per round, round range, focus agents, enable/disable LLM refinement
- **Export formats**: JSON and Markdown

![Analytics and reports in FOS](/tutorial/08-analytics.png)

### Export your data

Click **Export** to open the Export modal. Two export scopes are available:
- **All Logs** — Full simulation logs in JSON or CSV format, streamed from the backend.
- **Agent Data** — Agent properties and profiles in JSON or CSV format, processed locally including LLM provider resolution.

![Export reports in FOS](/tutorial/10-export-reports.png)

### Save as a template

Click **Save as Template** to reuse this configuration later. Find it under **My Templates** the next time you create a simulation.

---

<h2 id="advanced-features">Advanced FOS Features</h2>

Once you're comfortable with the basics, these tools open up deeper experiments.

### Social Network Topology

Control how agents are connected — different network shapes change how information spreads. FOS provides 8 topology presets, all using deterministic seeded randomness (same seed always produces the same network):

| Preset | Description | Parameters |
|---|---|---|
| **Full** | Every agent connected to every other | (none) |
| **Random** | Erdős–Rényi random graph | Connection probability |
| **Ring** | Circular ring graph | (none) |
| **Star** | All agents connect to a central hub | (none) |
| **Newman-Watts** | Small-world network | Neighbors per side, shortcut probability |
| **Core-Periphery** | Dense core with sparse periphery | Influencer percentage, connectivity levels |
| **Holme-Kim** | Scale-free with clustering | New connections per node, clustering probability |
| **Waxman** | Distance-based random graph | Max distance, distance effect |
| **SBM** | Stochastic block model | Group size, within-group connectivity, bridge connections |

All presets guarantee no isolated nodes. Open the **Network Editor** from the simulation view to select a preset, customize parameters, preview the network, and save your topology.

![Network topology editor in FOS](/tutorial/09-network-topology.png)

### Global Knowledge Base

Give your agents shared background knowledge they can reference during conversations. The knowledge base uses real semantic search:

1. Open the **Global Knowledge Panel** from the simulation view or during experiment setup.
2. **Add text knowledge** — enter a title and content directly.
3. **Upload documents** — drag and drop PDF, TXT, DOCX, or Markdown files (max 10MB each).
4. Documents are automatically chunked and embedded using **MiniLM** (sentence-transformers).
5. During simulation, agents retrieve relevant knowledge via **RAG** (Retrieval-Augmented Generation) — knowledge base chunks are injected into the agent's prompt context based on semantic similarity.
6. Edit or delete knowledge items anytime — no need to restart your simulation.

The knowledge base supports rich context injection: each entry keeps track of its source type, filename, creator, and creation timestamp.
