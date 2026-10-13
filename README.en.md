<p align="center"><img src="docs/assets/github-cover.svg" width="100%" alt="GAWorld — Generative agents, culture and everyday life" /></p>

<p align="center">
<a href="https://s2014628.github.io/gaworld-bench/world/">项目主页 / Website</a> ·
<a href="https://s2014628.github.io/gaworld-bench/">GAWorld Bench</a> ·
<a href="docs/FEATURES.md">能力目录 / Features</a> ·
<a href="README.md">中文</a>
</p>

<p align="center">
<img src="https://img.shields.io/badge/Python-3.11%2B-376556?style=flat-square" alt="Python 3.11+" />
<img src="https://img.shields.io/badge/Install-pip%20from%20GitHub-a34533?style=flat-square" alt="Install with pip from GitHub" />
<a href="https://github.com/wuchaozju/GAWorld/graphs/contributors"><img src="https://img.shields.io/github/contributors/wuchaozju/GAWorld?color=376556&amp;style=flat-square" alt="GitHub contributors" /></a>
</p>

# GAWorld · A world of people

**Memory, relationships and everyday culture, inside a world you can study.**

GAWorld is a generative multi-agent platform for social simulation. Resident portraits, personality, family obligations and past experiences provide the context for decisions. Cities, economies, weather and social networks give those decisions consequences. Researchers can inspect traces, interview residents and compare policies or events across parallel worlds.

Cultural context is a design commitment; fidelity remains a question to test.

## Contributors · The people behind the world

<p align="center">
<a href="https://github.com/wuchaozju"><img src="https://avatars.githubusercontent.com/u/597007?v=4&amp;s=128" width="64" height="64" alt="wuchaozju" /></a>
<a href="https://github.com/s2014628"><img src="https://avatars.githubusercontent.com/u/71760715?v=4&amp;s=128" width="64" height="64" alt="s2014628" /></a>
<a href="https://github.com/justinmiller1104"><img src="https://avatars.githubusercontent.com/u/30886201?v=4&amp;s=128" width="64" height="64" alt="justinmiller1104" /></a>
<a href="https://github.com/G-luckily"><img src="https://avatars.githubusercontent.com/u/189572350?v=4&amp;s=128" width="64" height="64" alt="G-luckily" /></a>
<a href="https://github.com/Luciddreamzz"><img src="https://avatars.githubusercontent.com/u/102663609?v=4&amp;s=128" width="64" height="64" alt="Luciddreamzz" /></a>
</p>

<p align="center"><a href="https://github.com/wuchaozju">wuchaozju</a> · <a href="https://github.com/s2014628">s2014628</a> · <a href="https://github.com/justinmiller1104">justinmiller1104</a> · <a href="https://github.com/G-luckily">G-luckily</a> · <a href="https://github.com/Luciddreamzz">Luciddreamzz</a></p>

Thank you for the code, reviews and questions. These accounts come from the repository's real GitHub contribution history; no individual project roles are inferred.
[All contributors](https://github.com/wuchaozju/GAWorld/graphs/contributors) · [Collaboration workflow](CONTRIBUTING.md) · [Issues](https://github.com/wuchaozju/GAWorld/issues)

## Install with one pip command

Requires **Python 3.11+** and **Git**. A virtual environment is recommended.

```bash
python -m pip install "git+https://github.com/wuchaozju/GAWorld.git@main"
gaworld dashboard
```

Open **http://127.0.0.1:8766**. The first launch prepares a writable workspace at `~/.local/share/gaworld/workspaces/default`, including the console, default city and runtime source. Existing workspaces and resident data are preserved.

To choose a workspace:

```bash
gaworld init ./my-world
cd my-world
gaworld dashboard
```

Configure your own model endpoint and API key under **Settings → Models**, test connectivity, then start a simulation. Cloud model calls may incur provider charges. Installation and browsing the console do not require a shared key.

Distribution is currently through GitHub, not PyPI. Existing workspaces retain their runtime version; initialize a new directory after upgrading the package, then migrate your data separately.

## People, places and possibilities

| Perspective | Capabilities | Guide |
| --- | --- | --- |
| **People with context** | Resident portraits, Big Five personality, episodic memory, long-term goals and household obligations | [Complete guide](docs/PROJECT_GUIDE.en.md) |
| **Places that live** | Cities from place names; geography, movement, weather, work and an auditable economy | [Cities](docs/CITY_TUTORIAL.md) |
| **Worlds you can enter** | Population creation, crowd interviews, social games, shared and distributed participation | [Interviews](docs/GROUP_INTERVIEW_TUTORIAL.md) · [Games](docs/PLAYGROUND_TUTORIAL.md) |
| **Questions you can test** | Parallel worlds, interventions, paired outcomes and uncertainty analysis | [Research workbench](docs/RESEARCH_WORKBENCH_TUTORIAL.md) · [Parallel worlds](docs/PARALLEL_WORLDS_TUTORIAL.md) |

## GAWorld Bench · Two questions, two axes

**Functional validity** asks whether tasks and mechanisms work. **Human validity** compares responses and behavior against matched human references. [Explore the benchmark](https://s2014628.github.io/gaworld-bench/).

The axes are reported separately. Current A35/A37 native Q&A uses one agent per item and does not establish full multi-agent collaboration or long-horizon city validity. Historical FOS mechanism and multi-role protocols retain their own denominators and interpretation.

## Develop and extend

```bash
git clone https://github.com/wuchaozju/GAWorld.git
cd GAWorld
python -m pip install -e ".[dev]"
python -m pytest --suite core
```

[Plugin authoring](docs/PLUGIN_AUTHORING.md) · [Development workflow](CONTRIBUTING.md) · [Deployment](docs/SERVER_DEPLOYMENT.md)

## Documentation and boundaries

[Complete English guide](docs/PROJECT_GUIDE.en.md) · [中文完整指南](docs/PROJECT_GUIDE.zh-CN.md) · [Capability catalog](docs/FEATURES.md)

The full guides preserve the existing commands, configuration and experimental notes. Simulation outputs are research artifacts produced by models and configurations, not validated predictions of real populations. Existing package metadata declares `Proprietary`; this update does not change licensing.
