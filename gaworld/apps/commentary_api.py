"""Dashboard backend for 新闻评论 (News Commentary), the playground's ninth game.

You hand the game a piece of news — either a URL that the server fetches, or a
short text you paste in. It then asks a chosen group of residents to react, in
their own voice: a short comment, a stance, and how strongly they hold it. The
output is a board of every resident's take on the same news, plus a short
overall summary.

You can also attach up to :data:`MAX_RELATED` related news items. The first
entry is the *main* news every resident is scored against; the rest are
folded into the prompt as background context only. They never produce their
own stance / strength / short-comment: a resident with one stance and five
related items still ends up with one short take on the main news.

Five things worth knowing before reading the code:

* **The same main news for everyone.** Unlike the rumor game, the news does
  not travel; every resident reacts to the headline + body the player handed
  in. The prompt tells them where it came from (URL or paste) so they read
  it the way a real reader would, not as if a friend forwarded it.
* **One call per resident, no rounds.** A reaction is small and parallelizable,
  so there is no propagation round; cost is ``residents + 1`` model calls. The
  ``+1`` is the summary that ties the thread together. Related items ride
  along inside the same prompt and add no calls.
* **The action vocabulary is small and stable.** ``stance`` is one of
  支持 / 反对 / 中立 / 质疑 — four buckets that survive a Chinese-news
  comment section. ``strength`` is 0-100 and reads as how strongly the resident
  holds that stance. ``comment`` is the actual thing they would post. Numbers
  without a stance are noise; a stance without a comment is a thumbs-up emoji
  in prose.
* **Fetching a URL is best-effort.** A URL that times out, returns 4xx/5xx, or
  just doesn't parse degrades to an empty body; the prompt still runs and the
  resident is told what happened so the player gets an honest error instead of
  a silent empty board. The fetched article body is cached per run, so the
  summary call sees the same text the residents did.
* **Everything stays in memory.** Like every other playground game, the run
  lives in a :class:`JobStore` and the city bundle is never written back.

Conventions follow :mod:`gaworld.apps.rumor_api`: a background job with
progress, in-memory state, injectable LLM entry points (``comment_fn=`` /
``summary_fn=``), and the roster / persona block come from
:mod:`gaworld.interview.roster` and :mod:`gaworld.apps.games_api`.
"""

from __future__ import annotations

import re
import statistics
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from gaworld.apps.game_jobs import JobStore
from gaworld.apps.games_api import first_json_object
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.dashboard.commentary_api")

#: Residents per run. Cost is ``residents + 1`` model calls worst case.
MAX_AGENTS = 12
#: Related news items the player may attach to a single run. They never cost
#: an extra model call — they ride along in the prompt as background context
#: — so the cost driver is the resident count.
MAX_RELATED = 5
#: How much of the news body goes into each prompt. Long enough that the
#: resident has something real to react to, short enough that the prompt does
#: not blow past the model's context window once twelve personas are in it.
NEWS_CHARS = 1500
#: How much of each related item fits in the prompt. The shorter of the
#: budgets: a single related item should not eat the budget that the main
#: news actually needs.
RELATED_CHARS = 280
#: How much of the profile goes into the persona block. The smaller of the
#: playground budgets, because the news body has to fit alongside it.
PERSONA_CHARS = 900

#: A stance the model is asked to pick. The vocabulary is intentionally small:
#: every Chinese comment section collapses to these four buckets, and a longer
#: list invites the model to invent a label that nothing else reads.
STANCES: tuple[str, ...] = ("支持", "反对", "中立", "质疑")
#: Where an off-vocabulary answer lands; never offered as a choice.
OTHER_STANCE = "其他"

_URL_RE = re.compile(r"(?i)\bhttps?://[^\s<>\"]+")


# ---------------------------------------------------------------------------
# News input
# ---------------------------------------------------------------------------


@dataclass
class NewsItem:
    """What the player handed in: a title, a body, and where it came from."""

    title: str
    body: str
    source: str  # "url" | "paste"
    url: str = ""
    fetch_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "body": self.body,
            "source": self.source,
            "url": self.url,
            "fetch_error": self.fetch_error,
        }


def _looks_like_url(text: str) -> bool:
    """Cheap URL sniff: a ``http(s)://`` token, no whitespace in the middle."""
    if not text:
        return False
    return bool(_URL_RE.search(text.strip()))


def _truncate(text: str, limit: int) -> str:
    """Trim *text* to *limit* characters on a word boundary when possible."""
    if not text:
        return ""
    if len(text) <= limit:
        return text.strip()
    head = text[:limit]
    if " " in head:
        head = head.rsplit(" ", 1)[0]
    return head.strip()


def _resolve_one_news(item: dict[str, Any], *, fallback: bool = False) -> NewsItem:
    """Resolve one entry of the player's input into a :class:`NewsItem`.

    *fallback* lets URL-fetch failures fall back to a pasted body when the
    caller has handed one in alongside the URL — that is how a URL with a
    pasted excerpt becomes useful instead of an empty board.
    """
    if not isinstance(item, dict):
        raise ValueError("新闻条目格式不对")
    url = str(item.get("url") or "").strip()
    body_in = str(item.get("body") or "").strip()
    title_in = str(item.get("title") or "").strip()

    if url:
        if not _looks_like_url(url):
            raise ValueError("url 看起来不像网址，请检查")
        # Lazy import: web_scrape pulls in requests; only paid when a URL is
        # handed in.
        from gaworld.io.web_scrape import fetch_news_excerpt

        fetched_body, fetched_title = fetch_news_excerpt(url, return_title=True)
        # ``fetch_news_excerpt`` returns ("", "") on any error; we still need to
        # tell the player what happened, and we still need *some* text so the
        # prompt is not just the persona preamble.
        fetch_error = "" if fetched_body else "网址抓取失败，可能是链接已失效、被反爬或网络不通"
        body = fetched_body or body_in or "(原文未能获取)"
        title = title_in or fetched_title or url
        return NewsItem(
            title=_truncate(title, 200),
            body=_truncate(body, 6000),
            source="url",
            url=url,
            fetch_error=fetch_error,
        )

    if not body_in:
        raise ValueError("新闻条目需要正文或网址")
    return NewsItem(title=title_in, body=_truncate(body_in, 6000), source="paste")


def resolve_news(payload: dict[str, Any]) -> tuple[NewsItem, list[NewsItem]]:
    """Turn the player's input into a main :class:`NewsItem` plus related ones.

    Two request shapes are accepted:

    * ``{url, body, title, related: [{...}, ...]}`` — single primary news,
      plus up to :data:`MAX_RELATED` related entries. The first one is the
      *main* news the residents are scored against; the rest are folded into
      the prompt as background context, never as scoring targets.
    * ``{news: [{url, body, title}, ...]}`` — array form where the first
      element is the main news. Backwards compatible with single news: a
      single-element array behaves like the legacy single news.

    Returns ``(main, related)``. ``related`` is empty for the legacy shape
    that only hands in one news.
    """
    if not isinstance(payload, dict):
        raise ValueError("请求格式不对")

    # Array shape: ``news: [...]``. The first element is the main news; the
    # rest are related background.
    array = payload.get("news")
    if isinstance(array, list) and array:
        if not array[0] or not isinstance(array[0], dict):
            raise ValueError("第一条新闻格式不对")
        main = _resolve_one_news(array[0])
        related_raw = [item for item in array[1:] if item]
        related = [_resolve_one_news(item) for item in related_raw[:MAX_RELATED]]
        return main, related

    # Single shape: build a one-entry array and feed it through the same
    # pipeline so legacy callers (one URL / one body) keep working.
    legacy = {
        "url": payload.get("url"),
        "body": payload.get("body"),
        "title": payload.get("title"),
    }
    related_raw = payload.get("related")
    if not isinstance(related_raw, list):
        related_raw = []
    related = [_resolve_one_news(item) for item in related_raw[:MAX_RELATED] if item]
    return _resolve_one_news(legacy), related


# ---------------------------------------------------------------------------
# Persona
# ---------------------------------------------------------------------------


@dataclass
class Commentator:
    """One resident in the run, plus what they said about the news."""

    agent_id: int
    name: str
    age: int = 0
    job: str = ""
    residence: str = ""
    persona_text: str = ""
    comment: str = ""
    stance: str = ""
    strength: int = 0
    triggered: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "age": self.age,
            "job": self.job,
            "residence": self.residence,
            "comment": self.comment,
            "stance": self.stance,
            "strength": self.strength,
            "triggered": self.triggered,
            "error": self.error,
        }


def _nodes_from_people(city: str, people: list[dict[str, Any]]) -> dict[int, Commentator]:
    from gaworld.apps.games_api import persona_block
    from gaworld.interview.roster import profile_block

    nodes: dict[int, Commentator] = {}
    for person in people:
        agent_id = int(person["id"])
        profile = profile_block(city, agent_id)
        persona = {
            "agent_id": agent_id,
            "name": person["name"],
            "age": person["age"],
            "gender": person["gender"],
            "job": person["job"],
            "profile_md": profile,
        }
        nodes[agent_id] = Commentator(
            agent_id=agent_id,
            name=str(person["name"]),
            age=int(person.get("age") or 0),
            job=str(person.get("job") or ""),
            residence=str(person.get("residence") or ""),
            persona_text=persona_block(persona),
        )
    return nodes


def _load_people(city: str, agent_ids: list[int]) -> list[dict[str, Any]]:
    from gaworld.interview.roster import load_population

    by_id = {int(p["id"]): p for p in load_population(city)}
    people = []
    for agent_id in agent_ids:
        person = by_id.get(int(agent_id))
        if person is None:
            raise ValueError(f"城市 {city or '默认世界'} 里没有 #{agent_id} 这个人")
        people.append(person)
    return people


# ---------------------------------------------------------------------------
# LLM entry points
# ---------------------------------------------------------------------------


def _call_llm(prompt: str, *, task: str, temperature: float) -> str:
    from gaworld.llm.providers import call_llm

    return str(call_llm(prompt, task=task, temperature=temperature, allow_fallback=True))


def _default_comment_llm(prompt: str) -> str:
    return _call_llm(prompt, task="games.commentary", temperature=0.7)


def _default_summary_llm(prompt: str) -> str:
    return _call_llm(prompt, task="games.commentary.summary", temperature=0.3)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def _news_source_line(news: NewsItem) -> str:
    if news.source == "url":
        if news.fetch_error:
            return f"这条新闻来自一条网址（{news.url}），但网页内容抓取失败。你只能看到题目，{news.fetch_error}。"
        return f"这条新闻来自一条网址（{news.url}）。你是从文章里读到它的，没有上下文之外的私聊。"
    return "这条新闻是别人直接贴给你的，没有出处，你只能根据正文判断。"


def _related_block(related: list[NewsItem]) -> str:
    """Render the related-news block that rides along in the prompt.

    Kept short on purpose: a related item is supposed to colour the read, not
    become a second article. Each entry gets a couple of hundred characters
    maximum, and the block caps at three items — if the player hands in more
    than three, only the first three appear in the prompt.
    """
    if not related:
        return ""
    rows = []
    for item in related[:3]:
        title = (item.title or "(无题)").strip() or "(无题)"
        snippet = (item.body or "").strip()[:RELATED_CHARS].replace("\n", " ")
        meta = item.url if item.source == "url" else "粘贴文本"
        line = f"- 《{title}》({meta})"
        if snippet:
            line += f"：{snippet}…"
        rows.append(line)
    header = "【相关阅读，仅作背景】\n" + "\n".join(rows)
    return header + "\n\n"


def _comment_prompt(node: Commentator, news: NewsItem, related: list[NewsItem]) -> str:
    stances = " / ".join(STANCES)
    body = (news.body or "").strip()[:NEWS_CHARS]
    return (
        f"{node.persona_text}\n\n"
        f"{_related_block(related)}"
        f"【新闻】{news.title}\n"
        f"{body}\n\n"
        f"{_news_source_line(news)}\n\n"
        "请按你这个人的身份、性格、利害关系来反应，"
        "就像在评论区写一条短评或者在群里和朋友聊这条新闻一样。"
        "**只对上面这条主新闻表态；下面的「相关阅读」只是帮你了解背景，"
        "不要把它当成另一条新闻分别评论。**\n"
        "不要罗列要点、不要总结全文、不要复述对方观点、不要扮演助手。"
        "立场允许和多数人不同，也允许承认你没太看懂。\n"
        f"只输出一个 JSON 对象，不要任何解释：\n"
        '{"stance": "下面四种中的一个", "strength": 0-100 的整数（你有多坚定，0=没感觉，100=坚定表态）, '
        '"comment": "你会写出来的中文短评，30-90 字，第一人称口语"}'
    )


def _summary_prompt(news: NewsItem, run: dict[str, Any]) -> str:
    stats = run["stats"]
    voices = []
    for node in run["nodes"][:6]:
        snippet = (node.get("comment") or "").strip()
        if not snippet:
            continue
        voices.append(f"- {node['name']}（{node.get('job') or '—'}，{node['stance']}）：{snippet[:60]}")
    title = news.title or "(无题)"
    return (
        "你是一名社会观察者，下面是一群居民对同一条新闻的评论记录。\n"
        "请写一段 150 字以内的总览：这群人里哪种观点占主导、哪种被忽略，"
        "什么样的人更容易被这件事触动，他们的反应之间有没有张力。要具体，不要空话，不要罗列要点。\n\n"
        f"新闻：{title}\n"
        f"涉及 {stats['total']} 人；立场分布：{stats['stance_counts']}；"
        f"平均表态强度 {stats['avg_strength']}。\n"
        f"几条原话：\n" + "\n".join(voices)
    )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _coerce_stance(value: Any) -> str:
    text = str(value or "").strip()
    if text in STANCES:
        return text
    for stance in STANCES:
        if stance in text or text in stance:
            return stance
    return OTHER_STANCE


def parse_comment(raw: str) -> dict[str, Any]:
    """Read one resident's JSON reply, tolerating prose around the object.

    A reply we cannot read degrades to ``其他`` with strength 0 and an empty
    comment — a silent commentator is honest about being silent, not loud
    nonsense.
    """
    text = str(raw or "").strip()
    payload = first_json_object(text)
    if not payload:
        return {"stance": OTHER_STANCE, "strength": 0, "comment": ""}
    try:
        strength = int(float(payload.get("strength", 0)))
    except (TypeError, ValueError):
        strength = 0
    return {
        "stance": _coerce_stance(payload.get("stance")),
        "strength": max(0, min(100, strength)),
        "comment": str(payload.get("comment") or "").strip()[:240],
    }


# ---------------------------------------------------------------------------
# Jobs — one store per game (see gaworld.apps.game_jobs).
# ---------------------------------------------------------------------------

_JOBS = JobStore("commentary")


def job_status(job_id: str) -> dict[str, Any] | None:
    return _JOBS.status(job_id)


def reset_jobs() -> None:
    """Drop every job. Used by tests; production code never calls it."""
    _JOBS.reset()


def list_runs() -> list[dict[str, Any]]:
    """Finished runs still in memory, newest first."""
    rows = []
    for record in _JOBS.results():
        result = record["result"] or {}
        stats = result.get("stats") or {}
        news = result.get("news") or {}
        related = result.get("related") or []
        rows.append(
            {
                "job_id": record["job_id"],
                "run_id": result.get("run_id"),
                "city": result.get("city"),
                "title": news.get("title"),
                "source": news.get("source"),
                "url": news.get("url"),
                "related_count": len(related),
                "total": stats.get("total"),
                "stance_counts": stats.get("stance_counts"),
                "created_at": result.get("created_at"),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# The game
# ---------------------------------------------------------------------------


def _stance_breakdown(nodes: list[Commentator]) -> dict[str, int]:
    counts = {stance: 0 for stance in STANCES}
    counts[OTHER_STANCE] = 0
    for node in nodes:
        counts[node.stance if node.stance in counts else OTHER_STANCE] += 1
    return counts


def _overall_stats(nodes: dict[int, Commentator]) -> dict[str, Any]:
    rows = list(nodes.values())
    strengths = [n.strength for n in rows if n.strength]
    # `spoke` is the residents who produced a real take (stance on-vocabulary
    # *and* a comment). The fallback path lands a resident with an empty
    # comment and stance ``其他``; counting them would inflate the board.
    spoke = sum(1 for n in rows if n.triggered)
    return {
        "total": len(rows),
        "spoke": spoke,
        "stance_counts": _stance_breakdown(rows),
        "avg_strength": round(statistics.mean(strengths), 1) if strengths else 0.0,
        "strongest": max(
            (
                {"agent_id": n.agent_id, "name": n.name, "strength": n.strength, "stance": n.stance}
                for n in rows
                if n.strength
            ),
            key=lambda row: (row["strength"], -row["agent_id"]),
            default=None,
        ),
    }


def run_commentary(
    *,
    city: str,
    agent_ids: list[int],
    news: NewsItem,
    related: list[NewsItem] | None = None,
    nodes: dict[int, Commentator] | None = None,
    comment_fn: Callable[[str], str] | None = None,
    summary_fn: Callable[[str], str] | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """Hand one piece of news to a group of residents and record their takes.

    *related* is the list of "background" news items that ride along in the
    prompt but never cost an extra model call and never produce a separate
    stance / score. The main *news* is what the residents are scored against.
    """
    progress = progress or (lambda p, m: None)
    related = list(related or [])[:MAX_RELATED]

    if nodes is None:
        people = _load_people(city, [int(i) for i in (agent_ids or [])][:MAX_AGENTS])
        if not people:
            raise ValueError("先选几个居民")
        nodes = _nodes_from_people(city, people)
    if not nodes:
        raise ValueError("先选几个居民")

    comment = comment_fn or _default_comment_llm
    sorted_ids = sorted(nodes)
    budget = len(sorted_ids) + 1
    spent = 0

    for agent_id in sorted_ids:
        node = nodes[agent_id]
        spent += 1
        progress(min(0.85, spent / max(1, budget)), f"读取意见 · {node.name}")
        try:
            raw = comment(_comment_prompt(node, news, related))
        except Exception as exc:  # pragma: no cover - provider failure
            _LOG.warning("commentary call failed for #%s: %s", agent_id, exc)
            node.error = f"{type(exc).__name__}: {exc}"
            raw = ""
        parsed = parse_comment(raw)
        node.stance = parsed["stance"]
        node.strength = parsed["strength"]
        node.comment = parsed["comment"]
        # `triggered` is "this is a real take": the resident picked one of
        # the four stances, said how strongly, and wrote a short comment.
        # Without all three, the slot is a fallback (parse failure or empty
        # fields), and `spoke` would over-count the board.
        node.triggered = (
            node.stance in STANCES
            and node.strength > 0
            and bool(node.comment)
        )

    run: dict[str, Any] = {
        "run_id": uuid.uuid4().hex[:8],
        "city": str(city or ""),
        "news": news.to_dict(),
        "related": [item.to_dict() for item in related],
        "nodes": [nodes[aid].to_dict() for aid in sorted_ids],
        "stats": _overall_stats(nodes),
        "summary": "",
        "created_at": time.time(),
    }

    progress(0.92, "正在写总览…")
    try:
        digest = (summary_fn or _default_summary_llm)(_summary_prompt(news, run))
        run["summary"] = str(digest).strip()
    except Exception as exc:  # pragma: no cover - provider failure
        _LOG.warning("commentary summary failed: %s", exc)
        run["summary"] = ""
    return run


def start_run(payload: dict[str, Any]) -> str:
    """Validate the request, then fan the news out in the background."""
    city = str(payload.get("city") or "")
    agent_ids = [int(i) for i in (payload.get("agent_ids") or [])]
    if len(agent_ids) < 1:
        raise ValueError("至少选一个居民")
    main, related = resolve_news(payload)
    return _JOBS.run(
        lambda progress: run_commentary(
            city=city,
            agent_ids=agent_ids,
            news=main,
            related=related,
            progress=progress,
        )
    )


# ---------------------------------------------------------------------------
# HTTP delegation — reached via games_api's /api/games/commentary/ branch.
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
        if path == "/api/games/commentary/catalogue":
            return {
                "stances": list(STANCES),
                "max_agents": MAX_AGENTS,
            }, 200
        if path == "/api/games/commentary/runs":
            return {"runs": list_runs()}, 200
        if path.startswith("/api/games/commentary/jobs/"):
            record = job_status(path.rsplit("/", 1)[-1])
            if record is None:
                return {"error": "Unknown job"}, 404
            return record, 200
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("commentary GET %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    try:
        if path == "/api/games/commentary/run":
            return {"job_id": start_run(payload)}, 202
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("commentary POST %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown endpoint"}, 404


__all__ = [
    "Commentator",
    "MAX_AGENTS",
    "MAX_RELATED",
    "NEWS_CHARS",
    "NewsItem",
    "OTHER_STANCE",
    "PERSONA_CHARS",
    "RELATED_CHARS",
    "STANCES",
    "handle_get",
    "handle_post",
    "job_status",
    "list_runs",
    "parse_comment",
    "reset_jobs",
    "resolve_news",
    "run_commentary",
    "start_run",
]
