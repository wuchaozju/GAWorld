"""Bind the interview engine to the city the current process has loaded.

This is the only module in the package that touches the simulator. It builds
real residents (profile, memory, goals, RAG) and real cohorts, and it makes
the model calls. Everything else — prompts, parsing, tallies, the document —
stays free of that dependency and therefore testable without a model.

**Scope note.** "The current process" is literal: a process resolves exactly
one city, the one its config selects, because ``build_agent`` and the memory
store read module-level paths. Cross-city interviews are therefore run as one
child process per city (see :mod:`gaworld.interview.__main__`), not by
mutating config under a thread pool — which would race the memory store's
process-global SQLite connection and silently mix two cities' memories.

**Persona note.** The persona block here is richer than the single-agent
``interview_agent`` prompt, which introduces the resident by name alone. For
one interview that is enough — the reader knows who they asked. For a survey
it is not: if the prompt does not carry what makes residents *differ*, their
answers converge, and a converged survey measures the model rather than the
population.

Nothing written here reaches the agent's stored memory. Recall does nudge the
in-memory agent's emotional state as a side effect of remembering, but that
object is discarded when the child process exits, and no memory record, diary
entry or state file is written. Surveying the population never changes it.
"""

from __future__ import annotations

from typing import Any

from gaworld.interview.schema import Question, Respondent
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.interview.local")

_STATE_LABELS = {
    "emotion": "情绪",
    "stress": "压力",
    "econ_security": "经济安全感",
    "city_identity": "城市认同",
}


class CityInterviewer:
    """Answers questions as residents (and cohorts) of the configured city.

    Construction is lazy and shared: the CSV, the city map and the population
    are read once for the whole round rather than once per respondent, which
    for 80 respondents is the difference between one file read and eighty.
    """

    def __init__(self, *, provider: str = "") -> None:
        self.provider = provider or ""
        self._df: Any = None
        self._city_map: Any = None
        self._news: tuple[list[Any], list[Any]] | None = None
        self._population: list[dict[str, Any]] | None = None
        self._background: str = ""

    # -- lazy shared inputs ------------------------------------------------

    def _sim(self) -> Any:
        # Imported inside the method: importing the simulator costs seconds
        # and pulls in the whole plugin tree, which a roster-only caller (and
        # every unit test of this package) must not pay for.
        import generative_city_sim as sim

        return sim

    def _frame(self) -> Any:
        if self._df is None:
            import pandas as pd

            sim = self._sim()
            self._df = pd.read_csv(sim.CSV_PATH)
            self._city_map = sim.load_city_map(sim.MAP_PATH)
            self._background = str(sim.CONFIG.get("background") or "").strip()
        return self._df

    def _news_sources(self) -> tuple[list[Any], list[Any]]:
        if self._news is None:
            sim = self._sim()
            if getattr(sim, "NEWS_ENABLED", False):
                self._news = (
                    sim.load_news_sources(sim.NEWS_SOURCES_PATH),
                    sim.load_news_cache(sim.NEWS_CACHE_PATH),
                )
            else:
                self._news = ([], [])
        return self._news

    def population(self) -> list[dict[str, Any]]:
        """This city's residents as plain dicts, for cohort statistics."""
        if self._population is None:
            from gaworld.interview.roster import load_population

            self._population = load_population(self._selected_city())
        return self._population

    def _selected_city(self) -> str:
        sim = self._sim()
        return str(sim.CONFIG.get("city") or "")

    # -- persona -----------------------------------------------------------

    def _agent_persona(self, respondent: Respondent, questions: list[Question]) -> str:
        sim = self._sim()
        df = self._frame()
        agent = sim.build_agent(int(respondent.ref), df, city_map=self._city_map)

        if getattr(sim, "STATEFUL", False):
            agent["memory"] = sim.load_agent_memory(agent["id"])
            sim.seed_vector_db_from_memory(agent)
        else:
            agent["memory"] = []
        agent["goals"] = (
            sim.load_agent_goals(agent["id"], sim.CONFIG.get("memory_dir", "output/memory"))
            if (getattr(sim, "STATEFUL", False) and getattr(sim, "GOALS_ENABLED", False))
            else {}
        )
        sources, cache = self._news_sources()
        sim._bootstrap_agent_external_rag(agent, news_cache=cache, news_sources=sources)

        from gaworld.sim._memory_recall import evoke_memory

        texts = [question.text for question in questions]
        recall = evoke_memory(agent, "interview", "群体采访", texts)
        state = agent.get("state") or {}
        state_line = "、".join(
            f"{label}{float(state.get(key, 0.5)):.2f}" for key, label in _STATE_LABELS.items()
        )
        lines = [
            f"你是{agent.get('name') or respondent.label}，{agent.get('age', '')}岁，"
            f"{agent.get('gender') or ''}，{agent.get('hukou') or ''}户籍，"
            f"住在{agent.get('residence') or agent.get('living') or ''}。",
        ]
        for label, key in (
            ("职业与工作节奏", "job"),
            ("性格与情绪特征", "personality"),
            ("日常生活", "daily_life"),
            ("价值观与公共事务态度", "values"),
        ):
            value = str(agent.get(key) or "").strip()
            if value:
                lines.append(f"{label}：{value}")
        if self._background:
            lines.append(f"你所在的地方：{self._background}")
        lines.append(f"你现在的状态：{state_line}")
        lines.append(f"你的近期经验：{recall.get('hint') or '暂无重要经验'}")
        lines.append(f"你的目标与追求：{sim._goals_hint(agent)}")
        recollection = str(recall.get("recollection") or "").strip()
        if recollection:
            lines.append(f"这些问题勾起的回忆：{recollection}")
        return "\n".join(lines)

    def _cohort_persona(self, respondent: Respondent) -> str:
        from gaworld.group.cohort import Cohort, cohort_summary, refresh_cohort_statistics

        people = {int(person["id"]): person for person in self.population()}
        members = [mid for mid in respondent.members if mid in people]
        if not members:
            raise ValueError(f"群体 {respondent.ref} 在当前城市里找不到成员")
        axes = tuple(key for key in respondent.demographics if key != "city")
        cohort = Cohort(
            id=respondent.ref,
            key=tuple(str(respondent.demographics[axis]) for axis in axes),
            axes=axes,
            members=members,
        )
        refresh_cohort_statistics(cohort, people)
        names = "、".join(str(people[mid]["name"]) for mid in members[:6])
        lines = [
            "你要代表一个**人群**发言，而不是某一个人。",
            f"这个人群：{cohort.label()}",
            f"规模：{cohort.size} 人（例如 {names} 等）",
            f"这群人当前的状态（均值与离散度）：{cohort_summary(cohort)}",
        ]
        if self._background:
            lines.append(f"他们所在的地方：{self._background}")
        lines.append(
            "注意：这是一个**有内部差异**的人群，不要当成一个「平均人」来回答。"
            "说清大多数人怎么想，以及其中一部分人的不同看法。"
        )
        return "\n".join(lines)

    def persona(self, respondent: Respondent, questions: list[Question]) -> str:
        """Persona block for one respondent — the callable the runner wants."""
        if respondent.kind == "cohort":
            return self._cohort_persona(respondent)
        return self._agent_persona(respondent, questions)

    # -- the model call ----------------------------------------------------

    def ask(
        self,
        respondent: Respondent,
        question: Question,
        prompt: str,
        images: list[dict[str, str]] | None = None,
    ) -> str:
        from gaworld.llm.providers import call_llm

        # ``agent_id`` feeds per-agent model routing, which exists so one
        # resident can be pinned to a specific backend. A cohort has no agent
        # id, so it routes by task alone.
        agent_id = int(respondent.ref) if respondent.kind == "agent" else None
        return call_llm(
            prompt,
            task="interview",
            agent_id=agent_id,
            provider=self.provider or None,
            images=images or None,
        )

    def summarize(self, prompt: str) -> str:
        from gaworld.llm.providers import call_llm

        return call_llm(prompt, task="interview_summary", provider=self.provider or None)

    def supports_images(self) -> bool:
        from gaworld.llm.providers import provider_supports_images

        return provider_supports_images(task="interview", provider=self.provider or None)


__all__ = ["CityInterviewer"]
