"""Dashboard backend for 谣言扩散局 (Rumor Spread), the playground's fourth game.

You write a rumor, hand it to a couple of residents, and watch it move — or
fail to move — through the people they know. What comes out is a diffusion
tree: who heard it when and from whom, who amplified it, who sat on it, and
who talked it back down.

Three things worth knowing before reading the code:

* **The graph is derived, not remembered.** A city bundle stores identities,
  not ties: resident-to-resident edges only grow during a simulation run, and
  what lands in ``output/memory/`` is mostly off-screen ghosts with no city
  attached (agent #13 is a different person in every city). So the graph here
  is rebuilt from the roster — same 小区, same trade, same surname under the
  same roof, same age — with the role vocabulary of
  :mod:`gaworld.social.network`. It costs no model call, it is deterministic,
  and :func:`build_graph` is exposed on its own endpoint so the player can
  see the network *before* spending anything on it.

* **The prompt fights the agreeable default.** Asked neutrally, every
  resident "checks with a friend who works at the bank" — the same
  socially-desirable answer the persuasion game gets when nothing tells the
  model to hold its ground. So the prompt says plainly that most people do
  not verify, and points the choice back at the persona. Without that line
  the action histogram is one bar and the game has nothing to show.

* **The model decides whether to pass it on; the graph decides to whom.**
  Letting the model name recipients invites hallucinated names and a mapping
  layer that can only lose information. Asking it for one decision — forward
  / ask around / debunk / sit on it — keeps the prompt short and puts the
  structure where structure belongs. This is the usual SIR-on-a-network
  split, and it means the tree is a property of the city, not of the model's
  memory for names.

* **Everyone speaks once, except a believer who gets corrected.** One call
  per resident is the honest cost of a diffusion round; the exception exists
  because without it a debunk can never change anyone's mind and 辟谣 becomes
  a dead option. Cost is therefore bounded by ``2 × residents + 1``.

Conventions follow :mod:`gaworld.apps.disaster_api`: a background job with
progress, in-memory state, injectable LLM entry points (``answer_fn=`` /
``summary_fn=``), and nothing ever written back to a city bundle.
"""

from __future__ import annotations

import statistics
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from gaworld.apps.games_api import first_json_object
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.dashboard.rumor_api")

#: Residents in one run. Cost is ``2 × residents + 1`` model calls worst case.
MAX_AGENTS = 14
#: Rounds played when the caller says nothing, and the ceiling.
DEFAULT_ROUNDS = 3
MAX_ROUNDS = 5
#: Ties kept per resident, by weight. Loosely Dunbar's inner circle: without a
#: cap, "everyone in the same 小区" plus "everyone with the same job" makes a
#: hairball in which every rumor reaches everybody on round one.
MAX_TIES = 6
#: Neighbours one forward reaches. A forward is a group chat, not a broadcast.
FANOUT = 4
#: How often one resident can speak (see the module docstring).
MAX_ACTS = 2
#: At or above this, we count the resident as believing the rumor.
BELIEVE_AT = 50

#: What a resident can do with a rumor that reached them.
ACTIONS: tuple[str, ...] = ("转发", "私下求证", "辟谣", "不管")
#: Where an off-vocabulary answer lands; never offered as a choice.
OTHER_ACTION = "其他"

#: Jobs that group people without making them colleagues. Without this,
#: "无业，家庭照料为主" (a quarter of a typical bundle) becomes one big office.
NON_WORK_JOBS: tuple[str, ...] = ("无业，家庭照料为主", "退休", "学生", "")

_MAX_JOBS = 20


# ---------------------------------------------------------------------------
# Rumor bank
# ---------------------------------------------------------------------------

#: Built-in rumors. All civic and locally checkable — the interesting variable
#: is *who* a resident trusts, not how lurid the claim is, and a rumor nobody
#: could plausibly act on produces a flat, boring tree.
RUMOR_BANK: tuple[dict[str, Any], ...] = (
    {
        "id": "water",
        "title": "自来水污染",
        "emoji": "🚰",
        "text": "自来水厂上游出了事，检测到超标物质，上面压着没通报。这两天别喝自来水，做饭也别用。",
    },
    {
        "id": "bank",
        "title": "银行要倒闭",
        "emoji": "🏦",
        "text": "城里那家小银行资金链断了，下周就要停止兑付。有存款的赶紧取出来，晚了排不上号。",
    },
    {
        "id": "grain",
        "title": "粮价要翻倍",
        "emoji": "🌾",
        "text": "邻省已经开始限购大米了，下个月粮油价格要翻一倍。能囤就先囤上两袋。",
    },
    {
        "id": "school",
        "title": "学校要搬",
        "emoji": "🏫",
        "text": "片区小学明年整体搬到城东去，文件都下了只是没公布。这边的学区房要跌。",
    },
    {
        "id": "typhoon",
        "title": "台风瞒报",
        "emoji": "🌀",
        "text": "气象台把台风级别压低了一档，实际是超强台风。别信预报，该走的赶紧走。",
    },
)


def list_rumors() -> list[dict[str, Any]]:
    return [dict(item) for item in RUMOR_BANK]


def rumor_by_id(rumor_id: str) -> dict[str, Any] | None:
    for item in RUMOR_BANK:
        if item["id"] == rumor_id:
            return item
    return None


def resolve_rumor(rumor_id: str, custom: dict[str, Any] | None = None) -> dict[str, Any]:
    """Pick the rumor to spread: one from the bank, or the caller's own."""
    if custom:
        text = str(custom.get("text") or "").strip()
        if not text:
            raise ValueError("自定义谣言要写点内容")
        return {
            "id": "custom",
            "title": str(custom.get("title") or "自定义传闻").strip() or "自定义传闻",
            "emoji": "✍️",
            "text": text,
        }
    found = rumor_by_id(str(rumor_id or ""))
    if found is None:
        raise ValueError(f"没有这条传闻：{rumor_id or '（未选）'}")
    return found


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------

#: Tie kinds, strongest first. ``role`` is the vocabulary of
#: :mod:`gaworld.social.network`, so a tie here reads the same as a tie grown
#: inside a simulation.
_KIN_WEIGHT = 0.9
_NEIGHBOR_WEIGHT = 0.55
_WORK_WEIGHT = 0.5
_CLASS_WEIGHT = 0.5
_PEER_WEIGHT = 0.25
#: Age gap that still counts as "the same generation".
_PEER_AGE_GAP = 3


def _surname(name: str) -> str:
    """First character of a Chinese name. Crude, and good enough as a
    household hint when it is paired with a shared address."""
    text = str(name or "").strip()
    return text[:1]


def _candidate_ties(left: dict[str, Any], right: dict[str, Any]) -> tuple[str, str, float] | None:
    """The strongest plausible tie between two residents, or ``None``."""
    same_home = bool(left["residence"]) and left["residence"] == right["residence"]
    age_gap = abs(int(left["age"] or 0) - int(right["age"] or 0))
    job = str(left["job"] or "")

    if same_home and _surname(left["name"]) and _surname(left["name"]) == _surname(right["name"]):
        return ("relative", "亲属", _KIN_WEIGHT)
    if same_home:
        return ("neighbor", "邻居", _NEIGHBOR_WEIGHT)
    if job == "学生" and right["job"] == "学生" and age_gap <= _PEER_AGE_GAP:
        return ("classmate", "同学", _CLASS_WEIGHT)
    if job and job == right["job"] and job not in NON_WORK_JOBS:
        return ("coworker", "同行", _WORK_WEIGHT)
    if age_gap <= _PEER_AGE_GAP:
        return ("acquaintance", "同龄熟人", _PEER_WEIGHT)
    return None


def build_graph(people: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Derive the tie list for *people*, capped at :data:`MAX_TIES` each.

    Pruning keeps the heaviest ties, then the smallest age gap, then the
    lowest id — deterministic, so the same selection always draws the same
    network and two runs stay comparable.
    """
    by_id = {int(p["id"]): p for p in people}
    ids = sorted(by_id)
    scored: list[tuple[float, int, int, int, str, str]] = []
    for index, left_id in enumerate(ids):
        for right_id in ids[index + 1 :]:
            left, right = by_id[left_id], by_id[right_id]
            tie = _candidate_ties(left, right)
            if tie is None:
                continue
            role, label, weight = tie
            gap = abs(int(left["age"] or 0) - int(right["age"] or 0))
            scored.append((weight, -gap, left_id, right_id, role, label))

    scored.sort(key=lambda row: (-row[0], -row[1], row[2], row[3]))
    degree: dict[int, int] = {}
    edges: list[dict[str, Any]] = []
    for weight, _gap, left_id, right_id, role, label in scored:
        if degree.get(left_id, 0) >= MAX_TIES or degree.get(right_id, 0) >= MAX_TIES:
            continue
        degree[left_id] = degree.get(left_id, 0) + 1
        degree[right_id] = degree.get(right_id, 0) + 1
        edges.append(
            {
                "a": left_id,
                "b": right_id,
                "role": role,
                "label": label,
                "closeness": round(weight, 2),
            }
        )
    edges.sort(key=lambda e: (e["a"], e["b"]))
    return edges


def _adjacency(edges: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    """``{agent_id: [{peer, label, closeness}, ...]}``, closest peer first."""
    out: dict[int, list[dict[str, Any]]] = {}
    for edge in edges:
        out.setdefault(edge["a"], []).append(
            {"peer": edge["b"], "label": edge["label"], "closeness": edge["closeness"]}
        )
        out.setdefault(edge["b"], []).append(
            {"peer": edge["a"], "label": edge["label"], "closeness": edge["closeness"]}
        )
    for peers in out.values():
        peers.sort(key=lambda p: (-p["closeness"], p["peer"]))
    return out


def load_people(city: str, agent_ids: list[int]) -> list[dict[str, Any]]:
    """Roster rows for the picked residents, in the order they were picked."""
    from gaworld.interview.roster import load_population

    by_id = {int(p["id"]): p for p in load_population(city)}
    people = []
    for agent_id in agent_ids:
        person = by_id.get(int(agent_id))
        if person is None:
            raise ValueError(f"城市 {city or '默认世界'} 里没有 #{agent_id} 这个人")
        people.append(person)
    return people


def graph_preview(city: str, agent_ids: list[int]) -> dict[str, Any]:
    """Nodes + ties for a selection, with no model call. Drives the picker."""
    people = load_people(city, agent_ids)
    edges = build_graph(people)
    adjacency = _adjacency(edges)
    return {
        "nodes": [
            {
                "agent_id": int(p["id"]),
                "name": p["name"],
                "age": p["age"],
                "job": p["job"],
                "residence": p["residence"],
                "degree": len(adjacency.get(int(p["id"]), [])),
            }
            for p in people
        ],
        "edges": edges,
        "isolated": sorted(int(p["id"]) for p in people if not adjacency.get(int(p["id"]))),
    }


# ---------------------------------------------------------------------------
# LLM entry points
# ---------------------------------------------------------------------------


def _call_llm(prompt: str, *, task: str, temperature: float) -> str:
    from gaworld.llm.providers import call_llm

    return str(call_llm(prompt, task=task, temperature=temperature, allow_fallback=True))


def _default_reaction_llm(prompt: str) -> str:
    return _call_llm(prompt, task="games.rumor", temperature=0.7)


def _default_summary_llm(prompt: str) -> str:
    return _call_llm(prompt, task="games.rumor.summary", temperature=0.3)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def _closeness_word(closeness: float) -> str:
    if closeness >= 0.8:
        return "很亲近"
    if closeness >= 0.5:
        return "熟"
    return "点头之交"


def _source_line(node: Node, messages: list[dict[str, Any]], nodes: dict[int, Node]) -> str:
    """Where this resident heard it — the single most important prompt line."""
    first = messages[0]
    sender_id = first.get("sender")
    if sender_id is None:
        return "这条消息是你自己在小区群里刷到的，不知道最早谁发的。"
    sender = nodes[sender_id]
    kind = {
        "rumor": "转给你的",
        "question": "私下来问你这事是不是真的",
        "debunk": "特地来跟你说这是假的",
    }.get(first.get("kind", "rumor"), "转给你的")
    return (
        f"是{sender.name}（{first.get('label', '熟人')}，{_closeness_word(first.get('closeness', 0.5))}）"
        f"{kind}。"
    )


def _social_proof(spreading: int, debunking: int) -> str:
    if not spreading and not debunking:
        return ""
    bits = []
    if spreading:
        bits.append(f"{spreading} 个人在传这条")
    if debunking:
        bits.append(f"{debunking} 个人说这是假的")
    return "在你认识的人里，已经有" + "、".join(bits) + "。"


def _reaction_prompt(
    node: Node,
    rumor: dict[str, Any],
    source_line: str,
    proof_line: str,
    correcting: bool,
) -> str:
    actions = " / ".join(ACTIONS)
    history = ""
    if correcting:
        history = (
            f"\n你之前听到这条的时候信了 {node.belief}%，还{node.action}了。现在有人来告诉你这是假的。\n"
        )
    return (
        f"{node.persona_text}\n\n"
        f"【你听到的消息】{rumor['text']}\n"
        f"{source_line}{proof_line}\n"
        f"{history}\n"
        "请按你自己的判断来：你有多信这条？你会怎么处理？"
        "考虑你自己的见识、消息渠道、跟告诉你的人有多熟、这件事跟你有多大关系。\n"
        "**不是每个人都会先去核实。** 有人在群里看到顺手就转出去了，尤其当这事关系到自家的钱、"
        "孩子、饭碗，或者身边人都在传的时候；有人看一眼就划过去，懒得管；也有人是真会去查。"
        "请严格按你这个人的性格和习惯选，不要因为『谨慎求证』听起来更得体就选它——"
        "城里多数人并不谨慎。\n"
        f"从这四种做法里选**一个**：{actions}。"
        "（转发＝发到群里或告诉几个熟人；私下求证＝只去问最信得过的那个人；"
        "辟谣＝主动告诉别人这是假的；不管＝看到了但不做声）\n"
        "只输出一个 JSON 对象，不要任何解释：\n"
        '{"belief": 0-100 的整数（你有多信）, "action": "上面四种中的一个", '
        '"say": "你会说出口的一句话，第一人称"}'
    )


def _summary_prompt(rumor: dict[str, Any], run: dict[str, Any]) -> str:
    stats = run["stats"]
    voices = []
    for node in run["nodes"][:6]:
        if node.get("say"):
            voices.append(
                f"- {node['name']}（{node.get('job') or '—'}，信 {node['belief']}%）：{node['say']}"
            )
    return (
        "你是一名社会学观察者，下面是一条传闻在一座城的熟人网络里扩散后的记录。\n"
        "请写一段 150 字以内的简报：它是怎么扩散的，在哪里被挡住了，谁放大了它，"
        "什么样的人更容易信。要具体，不要空话，不要罗列要点。\n\n"
        f"传闻：{rumor['title']}——{rumor['text']}\n"
        f"涉及 {stats['total']} 人，最终 {stats['reached']} 人听说，{stats['believers']} 人相信，"
        f"{stats['debunkers']} 人辟谣，{stats['silent']} 人没往下传。\n"
        f"平均相信程度：{stats['avg_belief']}%。\n"
        f"几个人的原话：\n" + "\n".join(voices)
    )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _coerce_action(value: Any) -> str:
    text = str(value or "").strip()
    if text in ACTIONS:
        return text
    for action in ACTIONS:
        if action in text or text in action:
            return action
    return OTHER_ACTION


def parse_reaction(raw: str) -> dict[str, Any]:
    """Read one resident's JSON reply, tolerating prose around the object.

    A reply we cannot read degrades to ``其他`` with no belief and no
    onward spread — a rumor never propagates through a parse failure.
    """
    text = str(raw or "").strip()
    payload = first_json_object(text)
    if not payload:
        return {"belief": 0, "action": OTHER_ACTION, "say": text[:120]}
    try:
        belief = int(float(payload.get("belief", 0)))
    except (TypeError, ValueError):
        belief = 0
    return {
        "belief": max(0, min(100, belief)),
        "action": _coerce_action(payload.get("action")),
        "say": str(payload.get("say") or "").strip()[:200],
    }


# ---------------------------------------------------------------------------
# Job plumbing — same shape as arena_api / disaster_api.
# ---------------------------------------------------------------------------

_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()


def _new_job(kind: str) -> str:
    job_id = f"{kind}-{uuid.uuid4().hex[:8]}"
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "kind": kind,
            "status": "running",
            "progress": 0.0,
            "message": "启动中…",
            "started_at": time.time(),
            "finished_at": None,
            "result": None,
            "error": None,
        }
        finished = [
            (record["started_at"], key) for key, record in _JOBS.items() if record["status"] != "running"
        ]
        while len(_JOBS) > _MAX_JOBS and finished:
            finished.sort()
            _, oldest = finished.pop(0)
            _JOBS.pop(oldest, None)
    return job_id


def _update_job(job_id: str, **fields: Any) -> None:
    with _JOBS_LOCK:
        record = _JOBS.get(job_id)
        if record is not None:
            record.update(fields)


def _run_in_background(job_id: str, work: Callable[..., Any]) -> None:
    def runner() -> None:
        try:
            result = work(lambda p, m: _update_job(job_id, progress=p, message=m))
            _update_job(job_id, status="done", progress=1.0, finished_at=time.time(), result=result)
        except Exception as exc:  # pragma: no cover - surfaced via the API
            _update_job(
                job_id,
                status="failed",
                finished_at=time.time(),
                error=f"{type(exc).__name__}: {exc}",
            )
            _LOG.exception("rumor job %s failed", job_id)

    thread = threading.Thread(target=runner, name=f"rumor-{job_id}", daemon=True)
    thread.start()


def job_status(job_id: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        record = _JOBS.get(job_id)
        return dict(record) if record is not None else None


def list_runs() -> list[dict[str, Any]]:
    """Finished runs still in memory, newest first."""
    with _JOBS_LOCK:
        records = [dict(r) for r in _JOBS.values()]
    rows = []
    for record in records:
        result = record.get("result") or {}
        if record["status"] != "done" or not result:
            continue
        stats = result.get("stats") or {}
        rows.append(
            {
                "job_id": record["id"],
                "run_id": result.get("run_id"),
                "city": result.get("city"),
                "rumor": (result.get("rumor") or {}).get("title"),
                "emoji": (result.get("rumor") or {}).get("emoji"),
                "total": stats.get("total"),
                "reached": stats.get("reached"),
                "believers": stats.get("believers"),
                "created_at": result.get("created_at"),
            }
        )
    rows.sort(key=lambda r: -(r["created_at"] or 0))
    return rows


def reset_jobs() -> None:
    """Drop every job. Used by tests; production code never calls it."""
    with _JOBS_LOCK:
        _JOBS.clear()


# ---------------------------------------------------------------------------
# The game
# ---------------------------------------------------------------------------


@dataclass
class Node:
    """One resident in the run, plus what the rumor did to them."""

    agent_id: int
    name: str
    age: int = 0
    job: str = ""
    residence: str = ""
    persona_text: str = ""
    heard_round: int | None = None
    heard_from: int | None = None
    belief: int | None = None
    action: str = ""
    say: str = ""
    acts: int = 0
    spoke_rounds: list[int] = field(default_factory=list)

    @property
    def believes(self) -> bool:
        return (self.belief or 0) >= BELIEVE_AT

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "age": self.age,
            "job": self.job,
            "residence": self.residence,
            "heard_round": self.heard_round,
            "heard_from": self.heard_from,
            "belief": self.belief,
            "action": self.action,
            "say": self.say,
            "believes": self.believes,
            "spoke_rounds": list(self.spoke_rounds),
        }


def _nodes_from_people(city: str, people: list[dict[str, Any]]) -> dict[int, Node]:
    from gaworld.apps.games_api import persona_block
    from gaworld.interview.roster import profile_block

    nodes: dict[int, Node] = {}
    for person in people:
        agent_id = int(person["id"])
        persona = {
            "agent_id": agent_id,
            "name": person["name"],
            "age": person["age"],
            "gender": person["gender"],
            "job": person["job"],
            "profile_md": profile_block(city, agent_id),
        }
        nodes[agent_id] = Node(
            agent_id=agent_id,
            name=str(person["name"]),
            age=int(person["age"] or 0),
            job=str(person["job"] or ""),
            residence=str(person["residence"] or ""),
            persona_text=persona_block(persona),
        )
    return nodes


def _pick_seeds(seeds: list[int] | None, nodes: dict[int, Node], adjacency: dict[int, list]) -> list[int]:
    """Who hears it first.

    Default: the best-connected resident, plus the best-connected one who is
    *not* already their contact. Two adjacent seeds spend the first round
    telling each other, and the second cluster never lights up — which is the
    one thing this game exists to show.
    """
    chosen = [int(s) for s in (seeds or []) if int(s) in nodes]
    if chosen:
        return chosen
    ranked = sorted(nodes, key=lambda aid: (-len(adjacency.get(aid, [])), aid))
    if not ranked:
        return []
    first = ranked[0]
    neighbours = {p["peer"] for p in adjacency.get(first, [])}
    far = [aid for aid in ranked[1:] if aid not in neighbours]
    second = far[0] if far else (ranked[1] if len(ranked) > 1 else None)
    return [first] if second is None else [first, second]


def run_rumor(
    *,
    city: str,
    agent_ids: list[int],
    rumor_id: str = "",
    custom: dict[str, Any] | None = None,
    seeds: list[int] | None = None,
    rounds: int = DEFAULT_ROUNDS,
    nodes: dict[int, Node] | None = None,
    edges: list[dict[str, Any]] | None = None,
    answer_fn: Callable[[str], str] | None = None,
    summary_fn: Callable[[str], str] | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """Spread one rumor through the derived network and report the tree."""
    progress = progress or (lambda p, m: None)
    rumor = resolve_rumor(rumor_id, custom)
    round_count = max(1, min(int(rounds or DEFAULT_ROUNDS), MAX_ROUNDS))

    if nodes is None:
        people = load_people(city, [int(i) for i in (agent_ids or [])][:MAX_AGENTS])
        if not people:
            raise ValueError("先选几个居民")
        nodes = _nodes_from_people(city, people)
        edges = build_graph(people)
    if edges is None:
        edges = []
    if not nodes:
        raise ValueError("先选几个居民")

    adjacency = _adjacency(edges)
    answer = answer_fn or _default_reaction_llm
    seed_ids = _pick_seeds(seeds, nodes, adjacency)

    transmissions: list[dict[str, Any]] = []
    per_round: list[dict[str, Any]] = []
    spreading = 0  # people currently passing it on — the social-proof numerator
    debunking = 0
    # The seeds "find" it themselves: no sender, no tie, round 0.
    inbox: dict[int, list[dict[str, Any]]] = {aid: [{"sender": None, "kind": "rumor"}] for aid in seed_ids}
    budget = len(nodes) * MAX_ACTS
    spent = 0

    for round_index in range(round_count):
        if not inbox:
            break
        next_inbox: dict[int, list[dict[str, Any]]] = {}
        spoke: list[int] = []
        for agent_id in sorted(inbox):
            node = nodes[agent_id]
            messages = inbox[agent_id]
            if node.heard_round is None:
                node.heard_round = round_index
                node.heard_from = messages[0].get("sender")
            correcting = node.acts > 0
            # A second turn is only for the case that makes 辟谣 worth playing:
            # someone who believed it is told it is false.
            if correcting and not (node.believes and any(m.get("kind") == "debunk" for m in messages)):
                continue
            if node.acts >= MAX_ACTS or spent >= budget:
                continue

            spent += 1
            progress(min(0.92, spent / max(1, budget)), f"第 {round_index + 1} 轮 · {node.name}")
            prompt = _reaction_prompt(
                node,
                rumor,
                _source_line(node, messages, nodes),
                _social_proof(spreading, debunking),
                correcting,
            )
            try:
                raw = answer(prompt)
            except Exception as exc:  # pragma: no cover - provider failure
                _LOG.warning("rumor reaction failed for #%s: %s", agent_id, exc)
                raw = ""
            reaction = parse_reaction(raw)

            was_spreading = node.action == "转发"
            was_debunking = node.action == "辟谣"
            node.belief = reaction["belief"]
            node.action = reaction["action"]
            node.say = reaction["say"]
            node.acts += 1
            node.spoke_rounds.append(round_index)
            spoke.append(agent_id)

            if node.action == "转发" and not was_spreading:
                spreading += 1
            if node.action == "辟谣" and not was_debunking:
                debunking += 1
            if was_spreading and node.action != "转发":
                spreading -= 1

            for target in _targets(node, adjacency, nodes):
                transmissions.append(
                    {
                        "from": agent_id,
                        "to": target["peer"],
                        "round": round_index,
                        "kind": target["kind"],
                        "label": target["label"],
                    }
                )
                next_inbox.setdefault(target["peer"], []).append(
                    {
                        "sender": agent_id,
                        "kind": target["kind"],
                        "label": target["label"],
                        "closeness": target["closeness"],
                    }
                )

        per_round.append(_round_stats(round_index, nodes, spoke))
        inbox = next_inbox

    run = {
        "run_id": uuid.uuid4().hex[:8],
        "city": str(city or ""),
        "rumor": dict(rumor),
        "seeds": seed_ids,
        "nodes": [nodes[aid].to_dict() for aid in sorted(nodes)],
        "edges": list(edges),
        "transmissions": transmissions,
        "rounds": per_round,
        "stats": _overall_stats(nodes, transmissions),
        "summary": "",
        "created_at": time.time(),
    }

    progress(0.95, "正在写传播简报…")
    try:
        digest = (summary_fn or _default_summary_llm)(_summary_prompt(rumor, run))
        run["summary"] = str(digest).strip()
    except Exception as exc:  # pragma: no cover - provider failure
        _LOG.warning("rumor summary failed: %s", exc)
        run["summary"] = ""
    return run


def _targets(
    node: Node, adjacency: dict[int, list[dict[str, Any]]], nodes: dict[int, Node]
) -> list[dict[str, Any]]:
    """Who this resident's decision reaches. The model picks the verb; the
    graph picks the people — see the module docstring."""
    peers = adjacency.get(node.agent_id, [])
    if node.action == "转发":
        fresh = [p for p in peers if nodes[p["peer"]].heard_round is None]
        return [dict(p, kind="rumor") for p in fresh[:FANOUT]]
    if node.action == "私下求证":
        # The closest person who could still be asked. Preferring someone who
        # has not heard it keeps the question from being a wasted turn — and
        # it is how a rumor reaches somebody nobody ever "told".
        fresh = [p for p in peers if nodes[p["peer"]].heard_round is None]
        target = fresh[:1] or peers[:1]
        return [dict(p, kind="question") for p in target]
    if node.action == "辟谣":
        return [dict(p, kind="debunk") for p in peers]
    return []


def _round_stats(round_index: int, nodes: dict[int, Node], spoke: list[int]) -> dict[str, Any]:
    reached = [n for n in nodes.values() if n.heard_round is not None and n.heard_round <= round_index]
    beliefs = [n.belief for n in reached if n.belief is not None]
    return {
        "round": round_index,
        "spoke": list(spoke),
        "newly_reached": sum(1 for n in nodes.values() if n.heard_round == round_index),
        "reached": len(reached),
        "believers": sum(1 for n in reached if n.believes),
        "debunkers": sum(1 for n in reached if n.action == "辟谣"),
        "avg_belief": round(statistics.mean(beliefs), 1) if beliefs else 0.0,
    }


def _overall_stats(nodes: dict[int, Node], transmissions: list[dict[str, Any]]) -> dict[str, Any]:
    reached = [n for n in nodes.values() if n.heard_round is not None]
    beliefs = [n.belief for n in reached if n.belief is not None]
    fanout: dict[int, int] = {}
    for item in transmissions:
        if item["kind"] == "rumor":
            fanout[item["from"]] = fanout.get(item["from"], 0) + 1
    top = sorted(fanout.items(), key=lambda kv: (-kv[1], kv[0]))
    actions: dict[str, int] = {}
    for node in reached:
        if node.action:
            actions[node.action] = actions.get(node.action, 0) + 1
    return {
        "total": len(nodes),
        "reached": len(reached),
        "believers": sum(1 for n in reached if n.believes),
        "debunkers": sum(1 for n in reached if n.action == "辟谣"),
        "silent": sum(1 for n in reached if n.action in ("不管", OTHER_ACTION)),
        "avg_belief": round(statistics.mean(beliefs), 1) if beliefs else 0.0,
        "actions": actions,
        # Whoever put it in front of the most new people.
        "superspreader": (
            {"agent_id": top[0][0], "name": nodes[top[0][0]].name, "n": top[0][1]} if top else None
        ),
        # Heard it, did not believe it, did not pass it on.
        "firewalls": sorted(n.agent_id for n in reached if not n.believes and n.action in ("不管", "辟谣")),
    }


def start_run(payload: dict[str, Any]) -> str:
    """Validate the request, then spread the rumor in the background."""
    city = str(payload.get("city") or "")
    agent_ids = [int(i) for i in (payload.get("agent_ids") or [])]
    if len(agent_ids) < 2:
        raise ValueError("至少选两个人，一个人传不开")
    custom = payload.get("custom") if isinstance(payload.get("custom"), dict) else None
    # Fail fast on an unknown rumor: better a 400 now than a dead job.
    resolve_rumor(str(payload.get("rumor_id") or ""), custom)

    job_id = _new_job("rumor")
    _run_in_background(
        job_id,
        lambda progress: run_rumor(
            city=city,
            agent_ids=agent_ids,
            rumor_id=str(payload.get("rumor_id") or ""),
            custom=custom,
            seeds=[int(s) for s in (payload.get("seeds") or [])],
            rounds=int(payload.get("rounds") or DEFAULT_ROUNDS),
            progress=progress,
        ),
    )
    return job_id


# ---------------------------------------------------------------------------
# HTTP delegation — reached via games_api's /api/games/rumor/ branch.
# ---------------------------------------------------------------------------


def _ids(query: dict[str, Any], key: str) -> list[int]:
    raw = query.get(key)
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    out = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if part:
            try:
                out.append(int(part))
            except ValueError:
                continue
    return out


def _one(query: dict[str, Any], key: str) -> str:
    value = query.get(key)
    if isinstance(value, list):
        return value[0] if value else ""
    return str(value or "")


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    query = query or {}
    try:
        if path == "/api/games/rumor/catalogue":
            return {
                "rumors": list_rumors(),
                "max_agents": MAX_AGENTS,
                "max_rounds": MAX_ROUNDS,
                "default_rounds": DEFAULT_ROUNDS,
                "actions": list(ACTIONS),
            }, 200
        if path == "/api/games/rumor/graph":
            return graph_preview(_one(query, "city"), _ids(query, "agent_ids")[:MAX_AGENTS]), 200
        if path == "/api/games/rumor/runs":
            return {"runs": list_runs()}, 200
        if path.startswith("/api/games/rumor/jobs/"):
            record = job_status(path.rsplit("/", 1)[-1])
            if record is None:
                return {"error": "Unknown job"}, 404
            return record, 200
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("rumor GET %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown rumor endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    try:
        if path == "/api/games/rumor/run":
            return {"job_id": start_run(payload)}, 200
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("rumor POST %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown rumor endpoint"}, 404


__all__ = [
    "ACTIONS",
    "BELIEVE_AT",
    "DEFAULT_ROUNDS",
    "FANOUT",
    "MAX_AGENTS",
    "MAX_ROUNDS",
    "MAX_TIES",
    "OTHER_ACTION",
    "RUMOR_BANK",
    "Node",
    "build_graph",
    "graph_preview",
    "handle_get",
    "handle_post",
    "job_status",
    "list_rumors",
    "list_runs",
    "load_people",
    "parse_reaction",
    "reset_jobs",
    "resolve_rumor",
    "rumor_by_id",
    "run_rumor",
    "start_run",
]
