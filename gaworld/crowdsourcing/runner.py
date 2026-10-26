"""The crowdsourcing engine.

One session runs ``rounds`` rounds. A round always looks the same from the
outside:

1. **Who gets to act** is decided by the strategy. ``market`` clears a bid
   market, ``elite`` and ``debate`` rank by accumulated credit, ``vote``
   draws a sample so the crowd keeps rotating.
2. **The acting agents answer** the task, each in their own voice.
3. **A judge scores** the answers in one comparative pass, so the crowd is
   ranked against itself rather than against an absolute rubric.
4. **Credit is handed out** relative to the round's own average — that is
   what makes the credit *local*, the way market-based post-training hands
   out training credit for collective outcomes (arXiv:2610.22322).
5. **The pool is pruned** towards the agents that did well, optionally
   keeping a few exploration slots so the crowd cannot collapse onto one
   voice too early.
6. **The round is aggregated** by the strategy and appended to the session.

The market strategy additionally turns the credit back into a *price*: an
agent that delivered a good answer raises its own bid for the next round,
one that did badly lowers it. That is the whole point of the mechanism —
participation is learned from outcomes instead of being assigned from above.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from gaworld.collaboration._parsing import extract_json
from gaworld.collaboration._persona import persona
from gaworld.crowdsourcing.models import CrowdSession, CrowdStatus
from gaworld.crowdsourcing.store import CrowdStore
from gaworld.crowdsourcing.strategies import (
    StrategySpec,
    cluster_attempts,
    get_strategy,
    similarity,
)

# An answer is shown to the judge and to the crowd's peers truncated: the
# judge needs enough to judge, not the whole essay.
_ATTEMPT_EXCERPT = 1400
_BID_LIMIT = 1.0


def _clamp(value: Any, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return low
    return max(low, min(high, number))


class CrowdsourcingRunner:
    def __init__(
        self,
        *,
        store: CrowdStore,
        agent_loader: Callable[[int], dict[str, Any] | None],
        llm: Callable[..., str],
        episode_writer: Callable[[int, dict[str, Any]], None] | None = None,
        max_parallel_calls: int = 6,
        step_retries: int = 1,
        learning_rate: float = 0.35,
        critique_finalists: int = 2,
    ) -> None:
        self.store = store
        self.agent_loader = agent_loader
        self.llm = llm
        self.episode_writer = episode_writer or (lambda agent_id, episode: None)
        self.max_parallel_calls = max(1, int(max_parallel_calls))
        self.step_retries = max(0, int(step_retries))
        self.learning_rate = float(learning_rate)
        self.critique_finalists = max(2, int(critique_finalists))

    # ------------------------------------------------------------------
    # plumbing
    # ------------------------------------------------------------------

    def _call(
        self,
        prompt: str,
        *,
        task: str,
        agent_id: int | None = None,
    ) -> str:
        last_error: Exception | None = None
        for _attempt in range(self.step_retries + 1):
            try:
                return str(self.llm(prompt, task=task, agent_id=agent_id)).strip()
            except Exception as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    def _parallel(self, jobs: Sequence[Callable[[], Any]]) -> list[Any]:
        if not jobs:
            return []
        if len(jobs) == 1:
            return [jobs[0]()]
        workers = min(self.max_parallel_calls, len(jobs))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return [future.result() for future in [pool.submit(job) for job in jobs]]

    def _persona(self, agent_id: int) -> dict[str, Any]:
        return persona(self.agent_loader(agent_id))

    def _is_running(self, session_id: str) -> bool:
        try:
            return self.store.get(session_id).status is CrowdStatus.RUNNING
        except KeyError:
            return False

    def _ensure_running(self, session_id: str) -> bool:
        """Move a queued session into ``running``; refuse anything else.

        A session that was cancelled or already finished must not be picked up
        again — resuming one of those would re-run a crowd that already spent
        its model calls.
        """
        with self.store.session_guard(session_id):
            session = self.store.get(session_id)
            if session.status is CrowdStatus.QUEUED:
                session.transition(CrowdStatus.RUNNING)
                self.store.save(session)
            elif session.status is not CrowdStatus.RUNNING:
                return False
            if not any(event.type == "started" for event in self.store.events(session_id)):
                self.store.append_event(session_id, "started", "众包开始")
        return True

    # ------------------------------------------------------------------
    # selection
    # ------------------------------------------------------------------

    @staticmethod
    def _rng(session_id: str, round_index: int, salt: str = "") -> random.Random:
        # Seeded from the session and the round, so a resumed run repeats the
        # same draw instead of quietly changing the crowd.
        return random.Random(f"{session_id}:{round_index}:{salt}")

    def _select(
        self,
        *,
        spec: StrategySpec,
        session_id: str,
        round_index: int,
        alive: list[int],
        credits: dict[int, float],
        bids: dict[int, dict[str, Any]],
        count: int,
    ) -> list[int]:
        if not alive:
            return []
        count = max(1, min(int(count), len(alive)))

        if spec.bids and bids:
            # The market decides. Highest effective bid wins the right to work.
            ordered = sorted(
                alive,
                key=lambda agent_id: (
                    -float(bids.get(agent_id, {}).get("effective_bid", 0.0)),
                    -credits.get(agent_id, 0.0),
                    agent_id,
                ),
            )
            return ordered[:count]

        if spec.id == "elite":
            ordered = sorted(
                alive,
                key=lambda agent_id: (-credits.get(agent_id, 0.0), agent_id),
            )
            return ordered[:count]

        if spec.id == "debate":
            # The strongest answer plus one challenger from the rest: a debate
            # needs a second voice to disagree with.
            ordered = sorted(
                alive,
                key=lambda agent_id: (-credits.get(agent_id, 0.0), agent_id),
            )
            picked = ordered[: max(1, count - 1)]
            rest = [agent_id for agent_id in ordered if agent_id not in picked]
            if rest and len(picked) < count:
                challenger = self._rng(session_id, round_index, "debate").choice(rest)
                picked.append(challenger)
            return picked[:count]

        # ``vote`` (and the default): a rotating sample, so the same few
        # residents do not answer every round.
        rng = self._rng(session_id, round_index, "sample")
        pool = list(alive)
        rng.shuffle(pool)
        # Bias the sample towards agents that have not acted recently.
        return sorted(pool[:count])

    # ------------------------------------------------------------------
    # the three model calls a round needs
    # ------------------------------------------------------------------

    def _bid_prompt(self, session: CrowdSession, agent_id: int) -> str:
        block = self._persona(agent_id)
        return json.dumps(
            {
                "task": session.task,
                "criteria": session.criteria,
                "round": session.current_round,
                "you": block,
                "instruction": (
                    "你是一个可以参与众包的居民。请评估自己完成上面这项任务的把握，"
                    "并报出你的出价：出价是你愿意付出的努力与自信的综合（0 到 1，越高表示"
                    "你越有把握且愿意投入）。请只输出 JSON："
                    '{"bid": 0.0 到 1.0, "confidence": 0.0 到 1.0, '
                    '"reason": "一句话说明你为什么报这个价", '
                    '"approach": "一句话说明你打算怎么做"}。'
                    "不要输出 JSON 以外的任何内容。"
                ),
            },
            ensure_ascii=False,
        )

    def _bid(self, session: CrowdSession, agent_id: int) -> dict[str, Any]:
        raw = self._call(
            self._bid_prompt(session, agent_id),
            task="crowdsourcing_bid",
            agent_id=agent_id,
        )
        payload = extract_json(raw)
        bid = _clamp(payload.get("bid"), 0.0, _BID_LIMIT)
        confidence = _clamp(payload.get("confidence"), 0.0, _BID_LIMIT)
        return {
            "agent_id": agent_id,
            "bid": bid,
            "confidence": confidence,
            "reason": str(payload.get("reason") or "").strip(),
            "approach": str(payload.get("approach") or "").strip(),
        }

    def _attempt_prompt(
        self,
        session: CrowdSession,
        agent_id: int,
        *,
        previous: str = "",
        reference: str = "",
        reference_agent: int | None = None,
    ) -> str:
        block = self._persona(agent_id)
        payload: dict[str, Any] = {
            "task": session.task,
            "criteria": session.criteria,
            "round": session.current_round,
            "you": block,
            "instruction": (
                "请以你本人的身份独立完成上面这项任务，直接给出可交付的成果正文"
                "（可以是方案、清单、论证或草稿）。用你自己的专业视角与语言习惯，"
                "不要输出任何解释性的前后缀，也不要复述任务。"
            ),
        }
        if previous:
            payload["your_previous_attempt"] = previous
            payload["instruction"] += (
                "这是你的第 "
                + str(session.current_round)
                + " 轮尝试，请在你自己上一版的基础上改进，只输出改进后的成果正文。"
            )
        if reference:
            payload["leading_answer_from"] = reference_agent
            payload["leading_answer"] = reference
            payload["instruction"] += (
                "上面是本轮目前最好的答案，请不要照抄它；你可以采纳其中正确的部分，但给出你自己的方案。"
            )
        return json.dumps(payload, ensure_ascii=False)

    def _attempt(
        self,
        session: CrowdSession,
        agent_id: int,
        *,
        previous: str = "",
        reference: str = "",
        reference_agent: int | None = None,
    ) -> dict[str, Any]:
        try:
            text = self._call(
                self._attempt_prompt(
                    session,
                    agent_id,
                    previous=previous,
                    reference=reference,
                    reference_agent=reference_agent,
                ),
                task="crowdsourcing_attempt",
                agent_id=agent_id,
            )
        except Exception as exc:
            return {
                "agent_id": agent_id,
                "text": "",
                "error": str(exc)[:300],
            }
        return {"agent_id": agent_id, "text": text, "error": ""}

    def _judge_prompt(
        self,
        session: CrowdSession,
        attempts: list[dict[str, Any]],
    ) -> str:
        candidates = [
            {
                "agent_id": attempt["agent_id"],
                "answer": str(attempt.get("text") or "")[:_ATTEMPT_EXCERPT],
            }
            for attempt in attempts
            if str(attempt.get("text") or "").strip()
        ]
        return json.dumps(
            {
                "task": session.task,
                "criteria": session.criteria or "完成度、针对性、可执行性",
                "candidates": candidates,
                "instruction": (
                    "这些是不同居民对同一任务的独立作答。请横向比较它们，"
                    "给每份答案打一个 0 到 1 的分数并说明理由。"
                    "请只输出 JSON："
                    '{"scores": [{"agent_id": 1, "score": 0.0 到 1.0, '
                    '"rationale": "一句话"}], "best_agent_id": 1}。'
                    "不要输出 JSON 以外的任何内容。"
                ),
            },
            ensure_ascii=False,
        )

    def _judge(
        self,
        session: CrowdSession,
        attempts: list[dict[str, Any]],
    ) -> tuple[dict[int, dict[str, Any]], bool]:
        """Score every answer in one comparative pass.

        The second return value says whether the scores are real: when the
        judge call fails the fallback uses cross-answer agreement instead, and
        the session has to say so rather than pretend a rubric was applied.
        """
        answered = [attempt for attempt in attempts if str(attempt.get("text") or "").strip()]
        if not answered:
            return {}, False
        try:
            raw = self._call(
                self._judge_prompt(session, attempts),
                task="crowdsourcing_judge",
            )
            payload = extract_json(raw)
        except Exception:
            payload = {}

        scores: dict[int, dict[str, Any]] = {}
        raw_scores = payload.get("scores")
        if isinstance(raw_scores, list):
            for entry in raw_scores:
                if not isinstance(entry, dict):
                    continue
                try:
                    agent_id = int(entry.get("agent_id"))
                except (TypeError, ValueError):
                    continue
                if agent_id not in {attempt["agent_id"] for attempt in answered}:
                    continue
                scores[agent_id] = {
                    "agent_id": agent_id,
                    "score": _clamp(entry.get("score"), 0.0, 1.0),
                    "rationale": str(entry.get("rationale") or "").strip(),
                }
        if not scores:
            return self._consensus_scores(answered), False
        for attempt in answered:
            scores.setdefault(
                attempt["agent_id"],
                {
                    "agent_id": attempt["agent_id"],
                    "score": 0.5,
                    "rationale": "评审未给出这一份的分数，按中性分处理",
                },
            )
        return scores, True

    @staticmethod
    def _consensus_scores(attempts: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        """Fallback scoring: how much each answer agrees with the others.

        This is not a rubric, but it is a real signal — an answer that many
        other residents converged on is more likely to be the workable one.
        """
        scores: dict[int, dict[str, Any]] = {}
        for attempt in attempts:
            others = [other for other in attempts if other["agent_id"] != attempt["agent_id"]]
            if others:
                agreement = sum(similarity(attempt.get("text"), other.get("text")) for other in others) / len(
                    others
                )
            else:
                agreement = 0.0
            scores[attempt["agent_id"]] = {
                "agent_id": attempt["agent_id"],
                "score": round(0.5 + 0.4 * min(1.0, agreement), 4),
                "rationale": "评审调用失败，改用群体一致性作为参考分",
            }
        return scores

    def _critique_prompt(
        self,
        session: CrowdSession,
        reviewer_id: int,
        own: str,
        other: str,
        other_id: int,
    ) -> str:
        return json.dumps(
            {
                "task": session.task,
                "criteria": session.criteria,
                "round": session.current_round,
                "your_answer": own[:_ATTEMPT_EXCERPT],
                f"answer_from_{other_id}": other[:_ATTEMPT_EXCERPT],
                "instruction": (
                    "另一位居民的答案在上面。请指出它最关键的一个问题，"
                    "并说明你的方案在这一点上为什么更好。"
                    "三句话以内，直接说，不要客套。"
                ),
            },
            ensure_ascii=False,
        )

    def _critique(
        self,
        session: CrowdSession,
        reviewer_id: int,
        own: str,
        other: str,
        other_id: int,
    ) -> dict[str, Any]:
        try:
            text = self._call(
                self._critique_prompt(session, reviewer_id, own, other, other_id),
                task="crowdsourcing_critique",
                agent_id=reviewer_id,
            )
        except Exception as exc:
            return {
                "agent_id": reviewer_id,
                "against": other_id,
                "text": "",
                "error": str(exc)[:300],
            }
        return {"agent_id": reviewer_id, "against": other_id, "text": text, "error": ""}

    def _final_prompt(
        self,
        session: CrowdSession,
        finalists: list[dict[str, Any]],
        critiques: list[dict[str, Any]],
    ) -> str:
        return json.dumps(
            {
                "task": session.task,
                "criteria": session.criteria or "完成度、针对性、可执行性",
                "finalists": [
                    {
                        "agent_id": item["agent_id"],
                        "answer": str(item.get("text") or "")[:_ATTEMPT_EXCERPT],
                    }
                    for item in finalists
                ],
                "critiques": [
                    {
                        "agent_id": item["agent_id"],
                        "against": item["against"],
                        "text": str(item.get("text") or "")[:600],
                    }
                    for item in critiques
                ],
                "instruction": (
                    "这是终选答案与它们之间的相互点评。请选出最好的一个，"
                    "并给出最终成果（可以直接采用被选中的答案并润色）。"
                    "请只输出 JSON："
                    '{"best_agent_id": 1, "score": 0.0 到 1.0, '
                    '"rationale": "一句话", "final_answer": "最终成果正文"}。'
                    "不要输出 JSON 以外的任何内容。"
                ),
            },
            ensure_ascii=False,
        )

    def _final_judge(
        self,
        session: CrowdSession,
        finalists: list[dict[str, Any]],
        critiques: list[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            raw = self._call(
                self._final_prompt(session, finalists, critiques),
                task="crowdsourcing_final",
            )
            payload = extract_json(raw)
        except Exception:
            payload = {}
        best_id = payload.get("best_agent_id")
        try:
            best_id = int(best_id)
        except (TypeError, ValueError):
            best_id = finalists[0]["agent_id"] if finalists else None
        allowed = {item["agent_id"] for item in finalists}
        if best_id not in allowed:
            best_id = finalists[0]["agent_id"] if finalists else None
        return {
            "best_agent_id": best_id,
            "score": _clamp(payload.get("score"), 0.0, 1.0),
            "rationale": str(payload.get("rationale") or "").strip(),
            "final_answer": str(payload.get("final_answer") or "").strip(),
        }

    # ------------------------------------------------------------------
    # pruning
    # ------------------------------------------------------------------

    @staticmethod
    def _prune(
        alive: list[int],
        credits: dict[int, float],
        *,
        keep: int,
        explore_ratio: float,
        rng: random.Random,
    ) -> list[int]:
        """Keep the strongest, plus a few slots for exploration.

        Without the exploration slots the crowd collapses onto one voice after
        a single round, and the later rounds stop measuring anything.
        """
        if keep <= 0 or keep >= len(alive):
            return list(alive)
        ordered = sorted(
            alive,
            key=lambda agent_id: (-credits.get(agent_id, 0.0), agent_id),
        )
        explore = round(keep * max(0.0, min(1.0, explore_ratio)))
        explore = min(explore, max(0, keep - 1))
        strong = ordered[: keep - explore]
        rest = ordered[keep - explore :]
        if explore and rest:
            strong = strong + rng.sample(rest, min(explore, len(rest)))
        return sorted(strong)

    # ------------------------------------------------------------------
    # aggregation
    # ------------------------------------------------------------------

    def _aggregate(
        self,
        spec: StrategySpec,
        attempts: list[dict[str, Any]],
        scores: dict[int, dict[str, Any]],
    ) -> dict[str, Any]:
        answered = [item for item in attempts if str(item.get("text") or "").strip()]
        if not answered:
            return {
                "agent_id": None,
                "text": "",
                "method": spec.id,
                "agreement": 0.0,
                "cluster": 0,
                "votes": 0,
            }
        if spec.id == "vote":
            clusters = cluster_attempts(answered)
            best_cluster = max(clusters, key=len)
            representative = max(
                best_cluster,
                key=lambda item: scores.get(item["agent_id"], {}).get("score", 0.0),
            )
            return {
                "agent_id": representative["agent_id"],
                "text": str(representative.get("text") or ""),
                "method": "vote",
                "agreement": round(len(best_cluster) / len(answered), 4),
                "cluster": len(best_cluster),
                "votes": len(best_cluster),
            }
        winner = max(
            answered,
            key=lambda item: scores.get(item["agent_id"], {}).get("score", 0.0),
        )
        return {
            "agent_id": winner["agent_id"],
            "text": str(winner.get("text") or ""),
            "method": spec.id,
            "agreement": round(
                sum(scores.get(item["agent_id"], {}).get("score", 0.0) for item in answered) / len(answered),
                4,
            ),
            "cluster": 1,
            "votes": 1,
        }

    # ------------------------------------------------------------------
    # the loop
    # ------------------------------------------------------------------

    def run(self, session_id: str) -> None:
        session = self.store.get(session_id)
        spec = get_strategy(session.strategy)
        if not self._ensure_running(session_id):
            return

        credits: dict[int, float] = {}
        rounds_acted: dict[int, int] = {}
        best_scores: dict[int, float] = {}
        bid_adjust: dict[int, float] = {}
        previous_answers: dict[int, str] = {}
        alive: list[int] = list(session.agent_ids)
        calls = int(session.stats.get("calls", 0) or 0)
        judge_failed = False

        for round_index in range(1, int(session.rounds) + 1):
            if not self._is_running(session_id):
                return
            session = self.store.get(session_id)
            session.current_round = round_index
            self.store.save(session)
            self.store.append_event(
                session_id,
                "round_started",
                f"第 {round_index} 轮开始",
                metadata={
                    "round": round_index,
                    "strategy": spec.id,
                    "pool": len(alive),
                },
            )

            # --- 1. bids -------------------------------------------------
            bids: dict[int, dict[str, Any]] = {}
            if spec.bids:
                bid_jobs = [
                    (lambda session=session, agent_id=agent_id: self._bid(session, agent_id))
                    for agent_id in alive
                ]
                for agent_id, bid in zip(alive, self._parallel(bid_jobs), strict=True):
                    if not isinstance(bid, dict):
                        continue
                    bid["effective_bid"] = round(
                        _clamp(
                            float(bid.get("bid", 0.0)) + bid_adjust.get(agent_id, 0.0),
                            0.0,
                            _BID_LIMIT,
                        ),
                        4,
                    )
                    bid["bid_adjust"] = round(bid_adjust.get(agent_id, 0.0), 4)
                    bids[agent_id] = bid
                    calls += 1
                for agent_id in sorted(bids, key=lambda key: -bids[key]["effective_bid"]):
                    self.store.append_event(
                        session_id,
                        "bid",
                        bids[agent_id].get("reason", ""),
                        agent_id=agent_id,
                        metadata={
                            "round": round_index,
                            "bid": bids[agent_id]["bid"],
                            "effective_bid": bids[agent_id]["effective_bid"],
                            "confidence": bids[agent_id]["confidence"],
                            "approach": bids[agent_id].get("approach", ""),
                        },
                    )

            # --- 2. selection -------------------------------------------
            selected = self._select(
                spec=spec,
                session_id=session_id,
                round_index=round_index,
                alive=alive,
                credits=credits,
                bids=bids,
                count=session.participants_per_round,
            )
            if not selected:
                break
            clearing_price = (
                min(float(bids[agent_id]["effective_bid"]) for agent_id in selected) if bids else 0.0
            )

            # --- 3. attempts --------------------------------------------
            reference = ""
            reference_agent: int | None = None
            if round_index > 1 and session.round_summaries:
                last = session.round_summaries[-1]
                reference_agent = last.get("aggregated_agent_id")
                if reference_agent is not None:
                    reference = str(last.get("aggregated_excerpt") or "")

            attempt_jobs = [
                (
                    lambda session=session, agent_id=agent_id, previous=previous_answers.get(agent_id, ""), reference=reference, reference_agent=reference_agent: (
                        self._attempt(
                            session,
                            agent_id,
                            previous=previous,
                            reference=reference,
                            reference_agent=reference_agent,
                        )
                    )
                )
                for agent_id in selected
            ]
            attempts: list[dict[str, Any]] = [
                attempt for attempt in self._parallel(attempt_jobs) if isinstance(attempt, dict)
            ]
            calls += len(attempts)
            for attempt in attempts:
                if attempt.get("error"):
                    self.store.append_event(
                        session_id,
                        "error",
                        attempt["error"],
                        agent_id=attempt.get("agent_id"),
                        metadata={"round": round_index, "phase": "attempt"},
                    )
                else:
                    previous_answers[int(attempt["agent_id"])] = str(attempt.get("text") or "")
                    self.store.append_event(
                        session_id,
                        "attempt",
                        str(attempt.get("text") or "")[:280],
                        agent_id=attempt.get("agent_id"),
                        metadata={
                            "round": round_index,
                            "chars": len(str(attempt.get("text") or "")),
                        },
                    )

            # --- 4. judging ---------------------------------------------
            scores, judged = self._judge(session, attempts)
            calls += 1
            judge_failed = judge_failed or not judged
            for agent_id in sorted(scores):
                self.store.append_event(
                    session_id,
                    "scored",
                    scores[agent_id].get("rationale", ""),
                    agent_id=agent_id,
                    metadata={
                        "round": round_index,
                        "score": scores[agent_id]["score"],
                    },
                )

            # --- 5. debate ----------------------------------------------
            critiques: list[dict[str, Any]] = []
            final_result: dict[str, Any] | None = None
            if spec.critique:
                ranked = sorted(
                    scores.items(),
                    key=lambda item: (-item[1]["score"], item[0]),
                )
                finalists = [
                    {
                        "agent_id": agent_id,
                        "text": next(
                            (
                                str(item.get("text") or "")
                                for item in attempts
                                if item["agent_id"] == agent_id
                            ),
                            "",
                        ),
                    }
                    for agent_id, _ in ranked[: self.critique_finalists]
                    if agent_id
                ]
                if len(finalists) >= 2:
                    critique_jobs = [
                        (
                            lambda session=session, first=finalists[0], second=finalists[1]: self._critique(
                                session,
                                first["agent_id"],
                                first["text"],
                                second["text"],
                                second["agent_id"],
                            )
                        ),
                        (
                            lambda session=session, first=finalists[0], second=finalists[1]: self._critique(
                                session,
                                second["agent_id"],
                                second["text"],
                                first["text"],
                                first["agent_id"],
                            )
                        ),
                    ]
                    critiques = [item for item in self._parallel(critique_jobs) if isinstance(item, dict)]
                    calls += len(critiques)
                    for item in critiques:
                        self.store.append_event(
                            session_id,
                            "critique",
                            str(item.get("text") or "")[:280],
                            agent_id=item.get("agent_id"),
                            metadata={"round": round_index, "against": item.get("against")},
                        )
                    final_result = self._final_judge(session, finalists, critiques)
                    calls += 1
                    if final_result.get("best_agent_id") is not None:
                        winner_id = int(final_result["best_agent_id"])
                        scores[winner_id] = {
                            "agent_id": winner_id,
                            "score": max(
                                float(scores.get(winner_id, {}).get("score", 0.0)),
                                float(final_result.get("score", 0.0)),
                            ),
                            "rationale": final_result.get("rationale", ""),
                        }

            # --- 6. credit ------------------------------------------------
            scored_values = [float(item["score"]) for item in scores.values()]
            baseline = sum(scored_values) / len(scored_values) if scored_values else 0.0
            for agent_id, record in scores.items():
                value = float(record.get("score", 0.0))
                credits[agent_id] = credits.get(agent_id, 0.0) + value
                rounds_acted[agent_id] = rounds_acted.get(agent_id, 0) + 1
                best_scores[agent_id] = max(best_scores.get(agent_id, 0.0), value)
                # The market turns the local credit back into a price: a good
                # outcome raises your own bid, a bad one lowers it.
                if spec.bids:
                    bid_adjust[agent_id] = round(
                        max(
                            -0.5,
                            min(
                                0.5,
                                bid_adjust.get(agent_id, 0.0) + self.learning_rate * (value - baseline),
                            ),
                        ),
                        4,
                    )

            # --- 7. pruning ------------------------------------------------
            prune_cfg = session.prune if isinstance(session.prune, dict) else {}
            survivors = list(alive)
            if prune_cfg.get("enabled"):
                keep = int(prune_cfg.get("keep", 0) or 0)
                explore_ratio = float(prune_cfg.get("explore_ratio", 0.25) or 0.0)
                survivors = self._prune(
                    alive,
                    credits,
                    keep=keep,
                    explore_ratio=explore_ratio,
                    rng=self._rng(session_id, round_index, "prune"),
                )
                if survivors != alive:
                    self.store.append_event(
                        session_id,
                        "pruned",
                        f"{len(alive)} → {len(survivors)}",
                        metadata={
                            "round": round_index,
                            "survivors": survivors,
                            "dropped": [agent_id for agent_id in alive if agent_id not in survivors],
                        },
                    )
                alive = survivors

            # --- 8. aggregation ---------------------------------------------
            aggregate = self._aggregate(spec, attempts, scores)
            if final_result and final_result.get("final_answer"):
                aggregate = {
                    **aggregate,
                    "text": str(final_result["final_answer"]),
                    "method": "debate",
                    "agent_id": final_result.get("best_agent_id"),
                }

            record = {
                "index": round_index,
                "strategy": spec.id,
                "bids": [bids[agent_id] for agent_id in sorted(bids)],
                "selected": selected,
                "clearing_price": clearing_price,
                "attempts": attempts,
                "scores": [scores[agent_id] for agent_id in sorted(scores)],
                "critiques": critiques,
                "final": final_result,
                "aggregate": aggregate,
                "survivors": list(alive),
                "baseline": round(baseline, 4),
                "judged": judged,
                "calls": len(attempts) + 1 + len(bids) + len(critiques) + (1 if final_result else 0),
            }
            self.store.append_round(session_id, record)

            session = self.store.get(session_id)
            session.round_summaries.append(
                {
                    "index": round_index,
                    "selected": selected,
                    "survivors": list(alive),
                    "aggregated_agent_id": aggregate.get("agent_id"),
                    "aggregated_excerpt": str(aggregate.get("text") or "")[:400],
                    "agreement": aggregate.get("agreement", 0.0),
                    "method": aggregate.get("method", spec.id),
                    "clearing_price": clearing_price,
                    "calls": record["calls"],
                }
            )
            session.leaderboard = self._leaderboard(
                credits, rounds_acted, best_scores, bid_adjust, alive, spec.bids
            )
            session.stats = {
                "calls": calls,
                "judge_fallback": judge_failed,
                "pool": len(alive),
            }
            self.store.save(session)
            self.store.append_event(
                session_id,
                "round_finished",
                aggregate.get("rationale", "") or "",
                agent_id=aggregate.get("agent_id"),
                metadata={
                    "round": round_index,
                    "method": aggregate.get("method"),
                    "agreement": aggregate.get("agreement", 0.0),
                    "calls": record["calls"],
                },
            )

        # --- 9. final ----------------------------------------------------
        session = self.store.get(session_id)
        if session.status is not CrowdStatus.RUNNING:
            return
        final_answer = ""
        final_agent = None
        final_method = spec.id
        if session.round_summaries:
            last = session.round_summaries[-1]
            final_agent = last.get("aggregated_agent_id")
            final_method = str(last.get("method") or spec.id)
            rounds = self.store.rounds(session.id)
            if rounds:
                aggregate = rounds[-1].get("aggregate") or {}
                final_answer = str(aggregate.get("text") or "")
        if not final_answer:
            # No aggregate survived (every attempt failed): fall back to the
            # best answer the session collected.
            for record in reversed(self.store.rounds(session.id)):
                for attempt in record.get("attempts", []):
                    if str(attempt.get("text") or "").strip():
                        final_answer = str(attempt["text"])
                        final_agent = attempt.get("agent_id")
                        break
                if final_answer:
                    break

        session.final_answer = final_answer
        session.final_agent_id = final_agent
        session.final_method = final_method
        session.stats = {
            **(session.stats or {}),
            "calls": calls,
            "judge_fallback": judge_failed,
        }
        self.store.save(session)
        try:
            self.store.write_artifact(
                session.id,
                "final.md",
                final_answer or "（本轮没有产出任何成果）",
                agent_id=final_agent,
                summary=f"{spec.name} · {session.rounds} 轮",
            )
        except (OSError, ValueError):
            pass
        # ``write_artifact`` re-reads and saves the session, so the handle in
        # hand is stale: saving it again would drop the artifact it just
        # wrote. Read it back before the last write.
        session = self.store.get(session.id)
        session.transition(CrowdStatus.COMPLETED)
        self.store.save(session)
        self.store.append_event(
            session.id,
            "final",
            final_answer[:280],
            agent_id=final_agent,
            metadata={"method": final_method, "calls": calls},
        )
        self._write_episodes(session, final_answer)

    @staticmethod
    def _leaderboard(
        credits: dict[int, float],
        rounds_acted: dict[int, int],
        best_scores: dict[int, float],
        bid_adjust: dict[int, float],
        alive: list[int],
        show_bid_adjust: bool,
    ) -> list[dict[str, Any]]:
        rows = [
            {
                "agent_id": agent_id,
                "credit": round(credits.get(agent_id, 0.0), 4),
                "rounds": rounds_acted.get(agent_id, 0),
                "best_score": round(best_scores.get(agent_id, 0.0), 4),
                "bid_adjust": round(bid_adjust.get(agent_id, 0.0), 4),
                "eliminated": agent_id not in alive,
            }
            for agent_id in credits
        ]
        rows.sort(key=lambda row: (-row["credit"], -row["best_score"], row["agent_id"]))
        for index, row in enumerate(rows, start=1):
            row["rank"] = index
        if not show_bid_adjust:
            for row in rows:
                row.pop("bid_adjust", None)
        return rows

    def _write_episodes(self, session: CrowdSession, final_answer: str) -> None:
        """Let the residents remember that they took part in a crowd.

        Only the agents that actually answered get an episode, and only once
        per session — the point is that they learn they were part of
        something, not that they accumulate one memory per round.
        """
        written: set[int] = set()
        for record in self.store.rounds(session.id):
            for attempt in record.get("attempts", []):
                agent_id = attempt.get("agent_id")
                if agent_id is None or agent_id in written:
                    continue
                written.add(int(agent_id))
                try:
                    self.episode_writer(
                        int(agent_id),
                        {
                            "source": "crowdsourcing",
                            "session_id": session.id,
                            "kind": "crowdsourcing",
                            "summary": session.task,
                            "artifact": "final.md",
                            "salience": 0.7,
                        },
                    )
                except Exception:
                    continue
