"""OpenAPI 3.1 description of the dashboard API, served at ``GET /api/openapi.json``.

Scope: every route the dashboard (default port 8766) answers under ``/api/`` —
the programmatic surface (interventions, the record stream, benchmarks, …) and
the console panels' own routes alike. The separate Twin, relay and external
environment servers are described in docs/API_REFERENCE.md only.

Kept as Python rather than a JSON file so shared shapes are written once. Each
operation gets, derived here rather than written by hand:

* ``operationId`` — ``<method>_<path segments>``, e.g. ``get_agents_agent_id_state``;
  ``gaworld.client`` calls any operation by it;
* path parameters from the ``{name}`` segments of the template;
* ``x-gaworld-access`` — the level ``gaworld.accounts.policy`` asks for once
  accounts are on, and ``x-gaworld-quota`` on requests that spend model calls.

The document is also the dashboard's method table: a path it lists under other
methods only is answered ``405`` with an ``Allow`` header (:func:`allowed_methods`).
``tests/test_openapi.py`` checks both directions — every listed route is
routed, and every route literal in the server code and the console is listed —
so it cannot silently drift from the server.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from gaworld.accounts import policy

ERROR = {"$ref": "#/components/schemas/Error"}
JOB = {"$ref": "#/components/schemas/Job"}
JOB_STARTED = {"$ref": "#/components/schemas/JobStarted"}

STR: dict[str, Any] = {"type": "string"}
INT: dict[str, Any] = {"type": "integer"}
NUM: dict[str, Any] = {"type": "number"}
BOOL: dict[str, Any] = {"type": "boolean"}
OBJ: dict[str, Any] = {"type": "object"}
INT_LIST: dict[str, Any] = {"type": "array", "items": INT}
STR_LIST: dict[str, Any] = {"type": "array", "items": STR}


def _d(schema: dict[str, Any], description: str) -> dict[str, Any]:
    return {**schema, "description": description}


def _arr(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


def _obj(required: tuple[str, ...] = (), /, **props: dict[str, Any]) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        schema["required"] = list(required)
    return schema


def _json(schema: dict[str, Any] | None = None, description: str = "OK") -> dict[str, Any]:
    return {"description": description,
            "content": {"application/json": {"schema": schema or {"type": "object"}}}}


def _err(description: str) -> dict[str, Any]:
    return _json(ERROR, description)


def _q(name: str, description: str, schema: dict | None = None, required: bool = False) -> dict:
    return {"name": name, "in": "query", "required": required, "description": description,
            "schema": schema or {"type": "string"}}


def _op(tag: str, summary: str, *, query: tuple | list = (), body: dict | None = None, ok: dict | None = None,
        status: str = "200", errors: dict[str, str] | None = None, description: str = "",
        response: dict | None = None, form: bool = False) -> dict[str, Any]:
    """One operation. ``ok`` is the success body's schema; ``response`` replaces
    the whole success response (non-JSON bodies); ``errors`` maps status → text."""
    op: dict[str, Any] = {"tags": [tag], "summary": summary}
    if description:
        op["description"] = description
    if query:
        op["parameters"] = list(query)
    if body is not None:
        media = "application/x-www-form-urlencoded" if form else "application/json"
        op["requestBody"] = {"required": bool(body.get("required")), "content": {media: {"schema": body}}}
    op["responses"] = {status: response or _json(ok)}
    for code, text in (errors or {}).items():
        op["responses"][code] = _err(text)
    return op


def _started(tag: str, summary: str, body: dict, **kw: Any) -> dict[str, Any]:
    """A request that opens a background job: ``202`` + ``{job_id}``."""
    errors = {"400": "Invalid request", **kw.pop("errors", {})}
    return _op(tag, summary, body=body, ok=JOB_STARTED, status="202", errors=errors, **kw)


def _job(tag: str) -> dict[str, Any]:
    return {"get": _op(tag, "Poll a background job", ok=JOB, errors={"404": "Unknown job"})}


CITY_Q = _q("city", "City slug or name (omitted: the running world)")
AGENT_ID_Q = _q("agent_id", "Resident id", INT)

INTERVENTION_REQUEST = _obj(
    ("id", "name", "status"),
    id=STR, name=STR, kwargs=OBJ, queued_at=NUM,
    status={"type": "string", "enum": ["pending", "applied", "failed"]},
    applied_at=_obj(day=INT, time=STR), result={}, error=STR,
)

ORGANIZATION_COMMAND = _obj(
    ("command_id", "type", "organization_id", "status"),
    command_id=STR, type=STR, organization_id=STR, payload=OBJ, actor=OBJ, created_at=STR,
    status={"type": "string", "enum": ["pending", "applied", "rejected"]},
    result={"type": ["object", "null"]},
)


def _organizations() -> dict[str, Any]:
    def command(command_type: str, required: tuple[str, ...], **properties: dict[str, Any]) -> dict[str, Any]:
        return {**_obj(("type", "organization_id", *required), type={"const": command_type},
                       organization_id=STR, command_id=STR, **properties), "additionalProperties": False}

    cents = {"type": "integer", "minimum": 0, "description": "Money in integer cents; no overdraft"}
    source = {"type": "string", "enum": ["government", "firms"]}
    governance = {**_obj(mode={"type": "string", "enum": ["off", "leader", "member_vote"]},
                        threshold={"type": "string", "enum": ["quorum_majority", "electorate_majority", "simple_majority"]},
                        voting_days={"type": "integer", "minimum": 1, "maximum": 365}), "additionalProperties": False}
    submitted = {"oneOf": [
        command("create", ("name", "kind", "leader_id"), name=STR,
                kind={"type": "string", "enum": ["community", "company"]}, goal=STR, leader_id=INT,
                member_ids=INT_LIST, initial_balance_cents=cents, funding_source=source, rule=STR,
                rule_params=OBJ, decision_interval=INT, seed=INT, governance=governance),
        command("add_member", ("agent_id",), agent_id=INT, role=STR, reason=STR),
        command("remove_member", ("agent_id",), agent_id=INT, reason=STR),
        command("handover", ("leader_id",), leader_id=INT),
        command("fund", ("amount_cents",), amount_cents=cents, source=source),
        command("apply_aid", ("agent_id", "amount_cents"), agent_id=INT, amount_cents=cents,
                reason=STR, request_id=STR),
        command("publish_job", ("occupation", "vacancies", "monthly_salary_cents"), job_id=STR,
                occupation=STR, vacancies=INT, monthly_salary_cents=cents, min_income_skill=NUM, location=STR),
        command("apply_job", ("agent_id", "job_id"), agent_id=INT, job_id=STR, reason=STR, request_id=STR),
        command("set_rule", ("rule",), rule=STR, rule_params=OBJ),
        command("set_governance", ("governance",), governance=governance),
        command("propose_rule", ("agent_id", "rule"), agent_id=INT, proposal_id=STR, rule=STR,
                rule_params={**_obj(max_award_cents=cents), "additionalProperties": False}, title=STR, reason=STR),
        command("cast_vote", ("agent_id", "proposal_id", "choice"), agent_id=INT, proposal_id=STR,
                choice={"type": "string", "enum": ["yes", "no", "abstain"]}, reason=STR),
        command("leader_decide", ("agent_id", "proposal_id", "choice"), agent_id=INT, proposal_id=STR,
                choice={"type": "string", "enum": ["yes", "no"]}, reason=STR),
        {**command("update_profile", (), name=STR, goal=STR),
         "anyOf": [{"required": ["name"]}, {"required": ["goal"]}]},
        command("close", (), reason=STR),
    ]}
    return {
        "/api/organizations/exports/metrics": {"get": _op(
            "organizations", "Download a completed organization metrics JSON archive",
            query=(_q("generation_id", "Generation; omitted = current. Legacy history requires an explicit day", STR),
                   _q("day", "Completed day; omitted = that generation's last completed day", {"type": "integer", "minimum": 1, "maximum": 1000000000})),
            ok=_obj(("filename", "content_type", "content", "sha256", "generation_id", "day", "scope"),
                    filename=STR, content_type=STR, content=STR, sha256=STR, generation_id=STR, day=INT, scope=STR),
            errors={"400": "Invalid or unsupported query", "404": "No completed archive", "409": "Corrupt metadata or archive"},
            description="Read-only in the active world. Save content as the provided filename; the envelope is not a metrics file. "
                        "The content preserves original UTF-8 bytes and SHA-256. Reads only generation/day archives, never a stale latest file.")},
        "/api/organizations": {"get": _op(
            "organizations", "Persisted organizations in the active world",
            query=(_q("generation_id", "Prior generation; omitted = current", STR),),
            ok=_obj(organizations=_arr(OBJ), enabled=BOOL, governance_enabled=BOOL, can_write=BOOL, execution=STR, meta=OBJ))},
        "/api/organizations/{organization_id}": {"get": _op(
            "organizations", "Account, members, jobs, applications and rule versions",
            query=(_q("generation_id", "Prior generation; omitted = current", STR),),
            errors={"404": "Unknown organization"})},
        "/api/organizations/{organization_id}/history": {"get": _op(
            "organizations", "Applied decisions and transactions, newest first",
            query=(_q("limit", "Maximum rows, 1–1000 (default 100)", INT), _q("generation_id", "Prior generation; omitted = current", STR)), ok=_obj(history=_arr(OBJ)),
            errors={"400": "Invalid limit", "404": "Unknown organization"})},
        "/api/organizations/commands": {
            "get": _op("organizations", "Pending, applied and rejected commands",
                       ok=_obj(commands=_arr(ORGANIZATION_COMMAND))),
            "post": _op("organizations", "Queue a validated organization command", body=submitted,
                        ok=ORGANIZATION_COMMAND, status="202", errors={"400": "Invalid command", "403": "World owner required"},
                        description="202 records submission only. The world's simulator applies the command at its next "
                                    "day boundary with organizations enabled; poll by command_id. Client paths and "
                                    "world overrides are rejected; the active world comes from its cookie. Governance is opt-in: "
                                    "proposals freeze eligible members, votes resolve at the closing boundary, and approved rules "
                                    "execute no earlier than the following day. agent_id is an owner/admin proxy submission, not resident authentication."),
        },
        "/api/organizations/commands/{command_id}": {"get": _op(
            "organizations", "Poll a command's actual execution status", ok=ORGANIZATION_COMMAND,
            errors={"404": "Unknown organization command"})},
    }

BENCH_JOB = _obj(
    id=STR,
    kind={"type": "string", "enum": ["bench", "rubric"]},
    status={"type": "string", "enum": ["running", "done", "failed"]},
    command=STR, started_at=NUM,
    finished_at={"type": ["number", "null"]},
    returncode={"type": ["integer", "null"]},
    scorecard={"type": ["object", "null"], "description": "This job's own scorecard, kept after later runs"},
    log_tail=STR,
)

AGENT_FIELDS = {
    "name": STR, "gender": STR, "age": INT, "hukou": STR, "residence": STR, "job": STR, "personality": STR,
    "daily_life": STR, "values": STR, "education_income": STR, "social_network": STR,
    "state": _d(OBJ, "Initial nine-dimension state"),
}


# -- core: meta, accounts, worlds, cluster, play ------------------------------------


def _core() -> dict[str, Any]:
    return {
        "/api/health": {
            "get": _op("meta", "Public readiness without user data", errors={"503": "Accounts unavailable"},
                       ok=_obj(ok=BOOL, service=STR, accounts=BOOL, accounts_required=BOOL)),
            "head": _op("meta", "Readiness headers only", errors={"503": "Accounts unavailable"}),
        },
        "/api/openapi.json": {"get": _op("meta", "This document")},
        # accounts (gaworld/apps/accounts_api.py)
        "/api/auth/me": {"get": _op(
            "auth", "Who is signed in", ok=_obj(mode={"type": "string", "enum": ["single", "accounts"]}, user=OBJ),
            description="`mode: single` when the account database does not exist (no sign-in at all).")},
        "/api/auth/users": {"get": _op("auth", "All accounts (admin)", ok=_obj(users=_arr(OBJ)))},
        "/api/auth/invites": {
            "get": _op("auth", "Invite codes (admin)", ok=_obj(invites=_arr(OBJ))),
            "post": _op("auth", "Create invite codes (admin)", body=_obj(
                count=_d(INT, "How many (default 1)"), label=_d(STR, "Class / group label"),
                expires_days=_d(NUM, "Default 14"), can_create_city=BOOL), ok=_obj(codes=STR_LIST)),
        },
        "/api/auth/invites/{invite_id}/revoke": {"post": _op("auth", "Revoke an invite (admin)",
                                                             ok=_obj(revoked=BOOL))},
        "/api/auth/audit": {"get": _op("auth", "Audit log (admin)", ok=_obj(audit=_arr(OBJ)))},
        "/api/auth/usage": {"get": _op("auth", "Model calls per user, today and in total (admin)",
                                       ok=_obj(users=_arr(OBJ), quota=INT))},
        "/api/auth/login": {"post": _op(
            "auth", "Sign in; sets the `gaworld_session` cookie",
            body=_obj(("nickname", "password"), nickname=STR, password=STR), ok=_obj(user=OBJ),
            errors={"401": "Wrong nickname or password"})},
        "/api/auth/register": {"post": _op(
            "auth", "Register with an invite code; sets the session cookie",
            body=_obj(("code", "nickname", "password"), code=STR, nickname=STR, password=STR), ok=_obj(user=OBJ))},
        "/api/auth/reset": {"post": _op(
            "auth", "Set a new password with a reset code; sets the session cookie",
            body=_obj(("code", "password"), code=STR, password=STR), ok=_obj(user=OBJ))},
        "/api/auth/logout": {"post": _op("auth", "Sign out; clears the session cookie", ok=_obj(ok=BOOL))},
        "/api/auth/password": {"post": _op(
            "auth", "Change one's own password (signs every other session out)",
            body=_obj(("old", "new"), old=STR, new=STR), ok=_obj(user=OBJ))},
        "/api/auth/users/{user_id}/reset": {"post": _op("auth", "Issue a password reset code (admin)",
                                                        ok=_obj(code=STR))},
        "/api/auth/users/{user_id}/city": {"post": _op(
            "auth", "Allow / forbid creating cities (admin)", body=_obj(allow=BOOL), ok=_obj(user=OBJ))},
        # worlds (gaworld/apps/worlds_api.py)
        "/api/worlds": {"get": _op(
            "worlds", "Worlds this user may see, and the active one",
            ok=_obj(mode=STR, current=OBJ, worlds=_arr(OBJ), default_writable=BOOL),
            description="The active world is the `gaworld_world` cookie; every other route reads and "
                        "writes that world's files. `{\"mode\": \"single\"}` without accounts.")},
        "/api/worlds/create": {"post": _op(
            "worlds", "Create a world from a city's residents; makes it the active world",
            body=_obj(name=STR, city=_d(STR, "City slug (empty: the default city)")), ok=_obj(world=OBJ))},
        "/api/worlds/select": {"post": _op(
            "worlds", "Switch the active world (sets the `gaworld_world` cookie)",
            body=_obj(id=_d(STR, "World id; empty for the shared default world")), ok=_obj(ok=BOOL, id=STR),
            errors={"404": "No such world, or not visible to this user"})},
        "/api/worlds/settings": {
            "get": _op("worlds", "Run limits (admin)", ok=_obj(limits=OBJ)),
            "post": _op("worlds", "Change run limits (admin)", body=_obj(
                max_concurrent_runs=INT, max_runs_per_user=INT,
                daily_llm_calls_per_user=_d(INT, "0 = no quota")), ok=_obj(limits=OBJ)),
        },
        "/api/worlds/broadcast": {"post": _op(
            "worlds", "Give every resident of the chosen worlds the same life event (admin)",
            body=_obj(("title",), title=STR, description=STR, severity=NUM,
                      world_ids=_d(STR_LIST, "`\"\"` is the shared default world")))},
        "/api/worlds/{world_id}/trail": {"get": _op("worlds", "A world's play / run trail")},
        "/api/worlds/{world_id}/visibility": {"post": _op(
            "worlds", "Change who may see a world (owner)",
            body=_obj(("visibility",), visibility={"type": "string", "enum": ["private", "class", "open"]}),
            ok=_obj(world=OBJ))},
        "/api/worlds/{world_id}/stop": {"post": _op("worlds", "Stop a world's simulation (owner)",
                                                    ok=_obj(world=OBJ))},
        "/api/worlds/{world_id}/delete": {"post": _op("worlds", "Delete a stopped world (owner)",
                                                      ok=_obj(ok=BOOL))},
        # distributed worlds (gaworld/apps/cluster_api.py)
        "/api/cluster": {"get": _op("cluster", "The active world's nodes and their residents (owner)")},
        "/api/cluster/nodes": {"post": _op(
            "cluster", "Add a node; returns its token once", body=_obj(name=STR, agent_ids=INT_LIST),
            ok=_obj(node=OBJ, token=STR, applies=STR))},
        "/api/cluster/nodes/{node_id}/agents": {"post": _op(
            "cluster", "Reassign a node's residents (next run)", body=_obj(("agent_ids",), agent_ids=INT_LIST))},
        "/api/cluster/nodes/{node_id}/delete": {"post": _op("cluster", "Remove a node", ok=_obj(removed=STR))},
        "/api/cluster/node": {"get": _node_op("Who this node is (node token)")},
        "/api/cluster/node/heartbeat": {"post": _node_op("Node heartbeat", body=_obj(state=STR, run_id=STR))},
        "/api/cluster/node/bundle": {"get": _node_op(
            "The world's files as a zip", response={"description": "Zip archive",
                                                    "content": {"application/zip": {"schema": STR}}})},
        "/api/cluster/node/interventions": {"get": _node_op("Take this node's queued interventions",
                                                            ok=_obj(items=_arr(OBJ)))},
        "/api/cluster/node/records": {"post": _node_op(
            "Upload Recorder rows", body=_obj(tables=_d(OBJ, "table name → rows")), ok=_obj(written=INT))},
        "/api/cluster/node/sync": {"post": _node_op("Tick barrier", body=_obj(run_id=STR, day=INT, time=STR))},
        "/api/cluster/relay/register": {"post": _node_op("Relay: register this node's residents",
                                                         body=_obj(agents=_arr(OBJ)))},
        "/api/cluster/relay/directory": {"get": _node_op("Relay: who is where")},
        "/api/cluster/relay/message/send": {"post": _node_op("Relay: send a message", body=_obj(message=OBJ))},
        "/api/cluster/relay/message/poll": {"post": _node_op(
            "Relay: poll messages", body=_obj(recipient_ids=INT_LIST, since=OBJ, limit=INT))},
        # multiplayer (gaworld/apps/play_api.py)
        "/api/play": {"get": _op("play", "Residents of the active world, who plays whom, my lease")},
        "/api/play/claim": {"post": _op(
            "play", "Claim (or renew the two-minute lease on) a resident", body=_obj(("agent_id",), agent_id=INT),
            errors={"409": "Someone else plays this resident"})},
        "/api/play/release": {"post": _op("play", "Let go of the claimed resident")},
        "/api/play/act": {"post": _op("play", "Make the claimed resident do something",
                                      body=_obj(("text",), text=STR))},
        "/api/play/say": {"post": _op("play", "Make the claimed resident say something to someone",
                                      body=_obj(("target_id", "text"), target_id=INT, text=STR))},
    }


def _node_op(summary: str, **kw: Any) -> dict[str, Any]:
    op = _op("cluster-node", summary, **kw)
    op["security"] = [{"node": []}]
    return op


# -- the simulation: config, residents, runs, records -------------------------------


def _simulation() -> dict[str, Any]:
    agent_404 = {"404": "Agent not found"}
    return {
        "/api/config": {
            "get": _op("config", "Effective configuration summary"),
            "post": _op("config", "Patch the configuration (written to the world's dashboard_config.json)",
                        body=OBJ),
        },
        "/api/agents": {
            "get": _op("agents", "All residents of the active world", ok=_obj(agents=_arr(OBJ))),
            "post": _op("agents", "Create a resident", body=_obj(("name",), **AGENT_FIELDS)),
        },
        "/api/agents/{agent_id}/avatar": {"get": _op(
            "agents", "Generated avatar", errors=agent_404,
            response={"description": "SVG", "content": {"image/svg+xml": {"schema": STR}}})},
        "/api/agents/{agent_id}/profile": {
            "get": _op("agents", "Profile Markdown and its parsed fields", errors={"404": "Profile not found"}),
            "post": _op("agents", "Replace the profile Markdown", body=_obj(("text",), text=STR)),
        },
        "/api/agents/{agent_id}/state": {
            "get": _op("agents", "Nine-dimension state", errors=agent_404),
            "post": _op("agents", "Write the state", body=_obj(state=OBJ, age=INT)),
        },
        "/api/agents/{agent_id}/big5": {
            "get": _op("agents", "Big Five traits", errors=agent_404),
            "post": _op("agents", "Write the Big Five", body=_obj(
                ("values",), values=_d(OBJ, "openness … neuroticism, each 0–1")), errors={"400": "Bad values"}),
        },
        "/api/agents/{agent_id}/detail": {"get": _op("agents", "Everything about one resident", errors=agent_404)},
        "/api/agents/{agent_id}/autobiography": {"get": _op(
            "agents", "Autobiography written from the resident's memories (one model call)",
            errors={"400": "Invalid agent id", "502": "The model call failed"})},
        "/api/agents/{agent_id}/memory": {
            "get": _op("agents", "Memories, summary and tag counts"),
            "post": _op("agents", "Append a memory", body=_obj(("text",), text=STR, kind=STR)),
        },
        "/api/agents/{agent_id}/goals": {
            "get": _op("agents", "Goal tree"),
            "post": _op("agents", "Replace the goal tree", body=OBJ, errors={"400": "Invalid goals"}),
        },
        "/api/agents/{agent_id}/relationships": {"post": _op(
            "agents", "Write social ties", body=_obj(relations=_arr(OBJ), removed=INT_LIST))},
        "/api/agents/{agent_id}/finance": {"post": _op("agents", "Write accounts", body=_obj(accounts=OBJ))},
        "/api/skills": {"get": _op("agents", "Skill library", ok=_obj(skills=_arr(OBJ)))},
        "/api/relationships/friends": {"post": _op(
            "agents", "Make a group of residents mutual friends", body=_obj(("agent_ids",), agent_ids=INT_LIST))},
        "/api/interview": {"post": _op(
            "agents", "Interview one resident (runs `generative_city_sim.py interview`)",
            body=_obj(("agent_id", "questions"), agent_id=INT,
                      questions={"oneOf": [STR, STR_LIST]}, context=STR,
                      timeout=_d(INT, "Seconds, default 300")))},
        # runs
        "/api/run/status": {"get": _op(
            "run", "Run state, queue position and the log since an offset",
            query=[_q("log_offset", "Return log lines after this byte offset", INT)])},
        "/api/run/log/export": {"get": _op(
            "run", "The run log as a Markdown download",
            response={"description": "Markdown", "content": {"text/markdown": {"schema": STR}}})},
        "/api/run/start": {"post": _op(
            "run", "Start (or queue) a simulation in the active world",
            body=_obj(config=_d(OBJ, "Config patch saved first"), reset=_d(BOOL, "Reset before starting")),
            errors={"409": "A simulation is already running or queued"})},
        "/api/run/stop": {"post": _op("run", "Stop the simulation")},
        "/api/run/schedule": {"post": _op(
            "run", "Start a simulation later", body=_obj(("at",), at=_d(STR, "ISO time or HH:MM"),
                                                       config=OBJ, reset=BOOL))},
        "/api/run/schedule/cancel": {"post": _op("run", "Cancel the scheduled start")},
        "/api/analytics/runs": {"get": _op("analytics", "Runs that can be analysed", ok=_obj(runs=_arr(OBJ)))},
        "/api/analytics/{section}": {"get": _op(
            "analytics", "One analytics section of a run",
            query=[_q("run", "Run id from /api/analytics/runs (omitted: the current run)")],
            errors={"404": "Unknown run or section"})},
        "/api/trace/meta": {"get": _op("trace", "Latest trace: output directory, residents, frames")},
        "/api/trace/data": {"get": _op("trace", "Latest trace frames")},
        "/api/replay/runs": {"get": _op("trace", "Archived runs", ok=_obj(runs=_arr(OBJ)))},
        # life events
        "/api/life-events": {
            "get": _op("life-events", "Queued and consumed life events"),
            "post": _op("life-events", "Queue a life event", body=_obj(
                title=STR, description=STR, severity=NUM, agent_id=INT, agent_ids=INT_LIST,
                schedule_mode={"type": "string", "enum": ["immediate", "scheduled"]}, day=INT, time=STR,
                state_effects=OBJ, impact_tags=STR_LIST, template_key=STR,
                candidate_key=_d(STR, "Key from /api/life-events/candidates; fills the rest"))),
        },
        "/api/life-events/candidates": {"get": _op(
            "life-events", "Life events that fit one resident's situation",
            query=[_q("agent_id", "Resident id", INT, required=True), _q("limit", "Max candidates", INT)],
            errors={"400": "agent_id is required", "404": "Agent not found"})},
        # todo board
        "/api/todos": {
            "get": _op("todos", "The todo board"),
            "post": _op("todos", "Replace every item", body=_obj(("items",), items=_arr(OBJ))),
        },
        "/api/todos/create": {"post": _op("todos", "Add an item", body=OBJ)},
        "/api/todos/update": {"post": _op("todos", "Change an item", body=_obj(("id",), id=STR))},
        "/api/todos/clear": {"post": _op("todos", "Remove every item")},
        "/api/todos/create-form": {"post": _op(
            "todos", "Add an item from an HTML form; redirects to /board", body=OBJ, form=True, status="303",
            response={"description": "Redirect to /board"})},
        "/api/fos-export": {"post": _op(
            "trace", "Write a Frame-of-Science prompt from a run's output (one model call)",
            body=_obj(output_dir=STR, hint=STR, english=BOOL))},
        # collaboration (gaworld/collaboration)
        "/api/collaboration/sessions": {
            "get": _op("collaboration", "Discussion / cooperation sessions", query=[
                _q("kind", "discussion | cooperation"), _q("status", "Filter by status")]),
            "post": _op("collaboration", "Start a session", body=_obj(
                ("kind", "agent_ids"), kind={"type": "string", "enum": ["discussion", "cooperation"]},
                agent_ids=INT_LIST, topic=_d(STR, "discussion"), max_rounds=_d(INT, "discussion, default 6"),
                task=_d(STR, "cooperation"), leader_id=_d(INT, "cooperation"),
                role_overrides=_d(OBJ, "cooperation: agent id → role")))},
        "/api/collaboration/sessions/{session_id}": {"get": _op("collaboration", "One session")},
        "/api/collaboration/sessions/{session_id}/events": {"get": _op(
            "collaboration", "Session events after a sequence number", query=[_q("after", "Sequence number", INT)])},
        **{f"/api/collaboration/sessions/{{session_id}}/{action}": {"post": _op(
            "collaboration", f"{action.capitalize()} a session")} for action in ("pause", "resume", "cancel")},
        # kernel (gaworld/apps/kernel_api.py)
        "/api/interventions": {"get": _op(
            "kernel", "List interventions available to the running simulation",
            ok=_obj(running=BOOL, registered=STR_LIST, pending=_arr(INTERVENTION_REQUEST),
                    applied=_arr(INTERVENTION_REQUEST)))},
        "/api/interventions/{key}": {
            "get": _op("kernel", "Poll one queued request", ok=INTERVENTION_REQUEST,
                       errors={"404": "Unknown request id"}),
            "post": {
                "tags": ["kernel"],
                "summary": "Queue an intervention for the running simulation",
                "description": "`key` is the intervention name; the JSON body is its keyword arguments. "
                               "Applied at the next simulation tick through `controller.intervene` and audited "
                               "to the `controller.intervention` record table. Built-ins: `set_agent_state` "
                               "(agent_id, key, value), `update_config` (path, value), `remove_agent` "
                               "(agent_id), `inject_life_event`, `inject_info_item` (source_id, title, "
                               "excerpt?, url?); plugins may register more — see `GET /api/interventions`.",
                "requestBody": {"required": False, "content": {"application/json": {"schema": OBJ}}},
                "responses": {
                    "202": _json(INTERVENTION_REQUEST, "Queued"),
                    "404": _json({"allOf": [ERROR, _obj(registered=STR_LIST)]},
                                 "Name not registered by the running simulation"),
                    "409": _err("No simulation is running"),
                },
            },
        },
        "/api/events/stream": {"get": _op(
            "kernel", "Server-Sent Events feed of Recorder rows",
            description="Every row appended to `output/records/<table>.jsonl` after the connection "
                        "opens is sent as one event whose `event:` is the table name and `data:` "
                        "the row JSON. Common tables: `agent.step`, `controller.intervention`, "
                        "`controller.intervention_failed`, `infosources.injected`, "
                        "`infosources.read`, `traffic.tick`. Keep-alive comment every 15 s.",
            query=[_q("tables", "Comma-separated table names to include (default: all)")],
            response={"description": "Event stream", "content": {"text/event-stream": {"schema": STR}}})},
    }


# -- data panels: information, economy, family, homes, settings, external systems ---


def _panels() -> dict[str, Any]:
    return {
        "/api/infosources/sources": {"get": _op("infosources", "Source registry with cache counts")},
        "/api/infosources/feed": {"get": _op("infosources", "Cached items", query=[
            _q("source_id", "Only this source"), _q("limit", "Max items", {"type": "integer", "default": 20})])},
        "/api/infosources/diets": {"get": _op(
            "infosources", "Residents' media diets", query=[_q("agent_id", "Only this resident")],
            errors={"404": "No diet for that resident"})},
        "/api/infosources/reads": {"get": _op("infosources", "Feed reads (`infosources.read`), newest first", query=[
            _q("url", "Item URL, e.g. gaworld://injected/1"), _q("source_id", "Source"),
            _q("agent_id", "Resident"), _q("limit", "Max rows", {"type": "integer", "default": 100})])},
        "/api/bench/run": {"post": _op(
            "bench", "Start a benchmark job (one at a time)", status="202", ok=BENCH_JOB,
            description="Options mirror the CLIs `benchmark/gaworld_bench.py` (kind=bench), "
                        "`benchmark/rubric_bench.py` (kind=rubric) and `benchmark/rubric_calibrate.py` "
                        "(kind=calibration: `judge`, `set`, `judges` — the judge ensemble scores a "
                        "calibration set). Unknown options are rejected; path options must stay inside "
                        "the repository.",
            body=_obj(
                ("kind",), kind={"type": "string", "enum": ["bench", "rubric", "calibration"]},
                track={"type": "string", "enum": ["A", "B", "C", "D"]}, all=BOOL, synthetic=BOOL, output_dir=STR,
                games_dir=_d(STR, "Tracks B and D: archived playground games (default output/games)"),
                comparisons_root=STR, run=BOOL, days=INT, seed=INT,
                seeds=_d(STR, "Comma list, e.g. 1,2,3"), resume=BOOL, fast=BOOL, llm_provider=STR,
                synthetic_mode=STR, judges=STR, samples_per_judge=INT, min_days=INT, ablate=STR, dim=STR,
                judge=BOOL, set=STR),
            errors={"400": "Invalid option", "409": "Another job is running"})},
        "/api/bench/jobs": {"get": _op("bench", "Recent jobs", ok=_obj(jobs=_arr(BENCH_JOB)))},
        "/api/bench/jobs/{job_id}": {"get": _op("bench", "One job", ok=BENCH_JOB, errors={"404": "Unknown job"})},
        "/api/bench/scorecard": {"get": _op("bench", "Latest scorecards of both harnesses")},
        "/api/bench/reports": {"get": _op("bench", "Archived report names, newest first")},
        "/api/bench/reports/{name}": {"get": _op("bench", "One archived report (Markdown)",
                                                 errors={"404": "Unknown report"})},
        "/api/bench/calibration": {"get": _op(
            "bench", "Track R human calibration sets, newest first (tasks, annotators, gate)")},
        "/api/bench/calibration/build": {"post": _op(
            "bench", "Draw a calibration set from a run (stratified over R1–R4, a third corrupted, blind)",
            status="201", body=_obj(output_dir=_d(STR, "Default: the active world's run root"),
                                    n=_d(INT, "Tasks, 5–100 (default 30)"), seed=INT),
            errors={"400": "No rubric item has data in that run"})},
        "/api/bench/calibration/{set_id}": {"get": _op(
            "bench", "A set as annotators see it, with only this annotator's labels",
            query=[_q("annotator", "Annotator name")], errors={"404": "Unknown set"})},
        "/api/bench/calibration/{set_id}/label": {"post": _op(
            "bench", "Save one label: 0 / 1 / 2, or null for「无法判断」",
            body=_obj(("annotator", "task_id"), annotator=STR, task_id=STR,
                      score=_d({"type": ["integer", "null"]}, "0, 1, 2 or null"), note=STR),
            errors={"400": "Bad score or task", "404": "Unknown set"})},
        "/api/bench/calibration/{set_id}/analyze": {"post": _op(
            "bench", "Human–human α, human–judge ρ / QWK and the gate; writes analysis.json",
            errors={"404": "Unknown set"})},
        "/api/economy/overview": {"get": _op(
            "economy", "Macro state, sector pools, conservation audit, wealth, city ledger")},
        "/api/economy/loans": {"get": _op("economy", "Agent-to-agent loans, bank debt, two-sided ledger check")},
        "/api/economy/ledger": {"get": _op(
            "economy", "One resident's ledger series",
            query=[_q("agent_id", "Resident id", INT, required=True), _q("limit", "Last N rows", INT)],
            errors={"400": "Bad parameters", "404": "No ledger"})},
        "/api/family": {"get": _op("family", "Households overview (alias of /api/family/overview)")},
        "/api/family/overview": {"get": _op("family", "Households, ties and duties")},
        "/api/family/preview": {"get": _op("family", "What the generator would build for one resident",
                                           query=[AGENT_ID_Q])},
        "/api/family/override": {
            "get": _op("family", "Same as /api/family/preview", query=[AGENT_ID_Q]),
            "post": _op("family", "Pin (or clear) one resident's family", body=_obj(
                ("agent_id",), agent_id=INT, override=OBJ, clear=BOOL)),
        },
        "/api/family/agent": {"get": _op("family", "One resident's family record (latest run)",
                                         query=[_q("agent_id", "Resident id", INT, required=True)],
                                         errors={"404": "No family record"})},
        "/api/home": {"get": _op("home", "Residents with a home design")},
        "/api/home/{agent_id}": {"get": _op(
            "home", "One resident's home design and latest observations",
            query=[_q("tail", "Observations to return", INT)], errors={"404": "No home design yet"})},
        "/api/moltbook/agent": {"get": _op("moltbook", "One resident's Moltbook account and activity",
                                           query=[_q("id", "Resident id", INT, required=True)])},
        "/api/moltbook/toggle": {"post": _op("moltbook", "Turn Moltbook on / off for a resident", body=_obj(
            ("agent_id",), agent_id=INT, enabled=BOOL, name=STR))},
        "/api/moltbook/refresh": {"post": _op("moltbook", "Fetch a resident's latest Moltbook activity",
                                              body=_obj(("agent_id",), agent_id=INT))},
        "/api/settings/overview": {"get": _op("settings", "Every setting, its default, its override (secrets masked)")},
        "/api/settings/save": {"post": _op("settings", "Save overrides", body=_obj(config=OBJ))},
        "/api/settings/reset": {"post": _op("settings", "Drop some overrides",
                                            body=_obj(("paths",), paths=_d(STR_LIST, "Dotted keys")))},
        "/api/settings/reset-all": {"post": _op("settings", "Drop every override")},
        "/api/settings/llm/provider": {"post": _op("settings", "Add or replace a model provider", body=_obj(
            ("name", "type"), name=STR, type=STR, config=OBJ))},
        "/api/settings/llm/test": {"post": _op(
            "settings", "One real generation against a saved provider or a draft",
            body=_obj(name=STR, config=_d(OBJ, "Draft provider, tested before saving")))},
        "/api/settings/llm/credential": {"post": _op(
            "settings", "Write-only personal credential scoped to the signed-in account; never returned",
            body=_obj(("name",), name=STR, action=_d(STR, "save or delete"),
                      api_key={"type": "string", "format": "password", "writeOnly": True}))},
        "/api/external-systems/overview": {"get": _op("external-systems", "Economy, environment and services")},
        "/api/external-systems/health": {"get": _op("external-systems", "Reachability of external services")},
        "/api/external-systems/interventions": {
            "get": _op("external-systems", "Scheduled economy interventions"),
            "post": _op("external-systems", "Schedule an economy intervention", body=_obj(
                ("day",), day=INT, macro=OBJ, sector_delta=OBJ, note=STR)),
        },
        "/api/external-systems/interventions/cancel": {"post": _op(
            "external-systems", "Cancel scheduled interventions", body=_obj(id=STR, all=BOOL))},
        "/api/external-systems/config": {"post": _op("external-systems", "Save external-systems settings",
                                                     body=_obj(config=OBJ))},
    }


# -- cities and populations -----------------------------------------------------------


def _cities() -> dict[str, Any]:
    city_required = _q("city", "City slug or name", required=True)
    return {
        "/api/city": {"get": _op("city", "Cities and the selected one (alias of /api/city/overview)")},
        "/api/city/overview": {"get": _op("city", "Cities and the selected one")},
        "/api/city/catalogue": {"get": _op("city", "Presets and scales for creating a city")},
        "/api/city/detail": {"get": _op("city", "One city bundle", query=[CITY_Q], errors={"404": "Unknown city"})},
        "/api/city/agents": {"get": _op("city", "A city's residents, read straight from its bundle", query=[
            CITY_Q, _q("q", "Search text"), _q("limit", "Page size", INT), _q("offset", "Page offset", INT)])},
        "/api/city/agent": {
            "get": _op("city", "One resident of a city (read-only)",
                       query=[CITY_Q, _q("id", "Resident id", INT, required=True)]),
            "post": _op("city", "Add one resident to a city", body=_obj(
                ("city",), city=STR, name=STR, age=INT, gender=STR, job=STR, hukou=STR,
                education=STR, income=STR, residence=STR)),
        },
        "/api/city/map": {"get": _op("city", "A city's road network", query=[city_required])},
        "/api/city/knowledge": {
            "get": _op("city", "A city's knowledge base", query=[city_required]),
            "post": _op("city", "Rebuild the knowledge base", body=_obj(("city",), city=STR, offline=BOOL)),
        },
        "/api/city/news": {
            "get": _op("city", "A city's cached news", query=[city_required]),
            "post": _op("city", "Refresh the news", body=_obj(("city",), city=STR, force=BOOL, ttl_hours=NUM)),
        },
        "/api/city/create": {"post": _op("city", "Create a city from a place name", body=_obj(
            ("name",), name=STR, description=STR, slug=STR, size=INT, seed=INT, scale=STR, preset=STR,
            offline=_d(BOOL, "No network: procedural map"), force=_d(BOOL, "Overwrite (admin)")))},
        "/api/city/population": {"post": _op("city", "Generate residents for a city", body=_obj(
            ("city",), city=STR, size=INT, seed=INT, replace=BOOL, preset=STR))},
        "/api/city/migrate": {"post": _op("city", "Move a resident from one city to another", body=_obj(
            ("agent_id", "city"), agent_id=INT, city=STR, from_city=STR, rehome=BOOL))},
        "/api/city/select": {"post": _op("city", "Make a city the running world (or clear)",
                                         body=_obj(city=STR, clear=BOOL))},
        "/api/city/delete": {"post": _op("city", "Delete a city bundle", body=_obj(("city",), city=STR))},
        "/api/population/schema": {"get": _op("population", "Population spec schema")},
        "/api/population/jobs/{job_id}": _job("population"),
        "/api/population/export": {"get": _op("population", "Export the last generated population",
                                              query=[_q("format", "csv | json", {"type": "string", "default": "csv"})])},
        "/api/population/last": {"get": _op("population", "Size of the last generated population")},
        "/api/population/preview": {"post": _op("population", "Marginals a spec would produce",
                                                body=_obj(spec=OBJ))},
        "/api/population/generate": {"post": _started("population", "Generate a population", _obj(
            spec=OBJ, write=_d(BOOL, "Also write files"), out_dir=STR))},
        "/api/population/group-run": {"post": _started("population", "Run a population in group mode", _obj(
            source=_d(STR, "last | spec"), spec=OBJ, days=INT, seed=INT, materialization_budget=INT,
            audit_fraction=NUM, network_coupling=NUM, use_llm=BOOL, provider=STR, cohort_axes=STR_LIST,
            focal_ids=INT_LIST))},
        "/api/population/validate": {"post": _started("population", "Validate group mode against agents", _obj(
            spec=OBJ, days=INT, seed=INT, materialization_budget=INT, network_coupling=NUM))},
        "/api/import/schema": {"get": _op("import", "Canonical fields, synonyms and formats")},
        "/api/import/jobs/{job_id}": _job("import"),
        "/api/import/preview": {"post": _op("import", "Map and preview an upload", body=_import_body())},
        "/api/import/run": {"post": _started("import", "Import residents into a city", _import_body(
            city=STR, seed=INT, salt=STR, city_root=STR))},
    }


def _import_body(**extra: dict[str, Any]) -> dict[str, Any]:
    return _obj(
        format={"type": "string", "enum": ["csv", "xlsx", "jsonl"]}, rows=_arr(OBJ), headers=STR_LIST,
        file_text=STR, file_encoding=_d(STR, "`base64` for binary files"), filename=STR, content_type=STR,
        mapping=_d(OBJ, "column → canonical field"), anonymise=BOOL, expand_to=INT, **extra)


# -- interviews, research, personas ---------------------------------------------------


def _studies() -> dict[str, Any]:
    study_actions = {
        "update": ("Change a study's protocol (before approval)", OBJ, "200"),
        "approve": ("Approve the protocol (optionally run)", _obj(run=BOOL, force=BOOL), "200"),
        "run": ("Run an approved study", None, "202"),
        "pause": ("Pause the running study", None, "200"),
        "resume": ("Resume a paused study", None, "200"),
        "stop": ("Stop the running study", None, "200"),
        "reset": ("Back to the protocol stage (optionally run again)", _obj(run=BOOL), "200"),
        "delete": ("Delete a study", None, "200"),
    }
    interview_spec = _obj(
        title=STR, questions=_arr(OBJ), respondents=_d(OBJ, "Who to ask: cities, filters, sample"),
        context=STR, provider=STR, concurrency=INT, session_id=_d(STR, "Follow-up round of this session"))
    return {
        "/api/interview/roster": {"get": _op("interview", "Who can be interviewed, by city and axis", query=[
            _q("cities", "Comma-separated city slugs"), _q("axes", "Comma-separated axes")])},
        "/api/interview/sessions": {"get": _op("interview", "Interview sessions")},
        "/api/interview/sessions/{session_id}": {"get": _op("interview", "One session",
                                                            errors={"404": "Unknown session"})},
        "/api/interview/sessions/{session_id}/export": {"get": _op("interview", "A session as Markdown")},
        "/api/interview/jobs/{job_id}": _job("interview"),
        "/api/interview/plan": {"post": _op("interview", "Check a round and say who will be asked",
                                            body=interview_spec)},
        "/api/interview/run": {"post": _started("interview", "Run a round", interview_spec)},
        "/api/interview/delete": {"post": _op("interview", "Delete a session",
                                              body=_obj(("session_id",), session_id=STR))},
        "/api/research/context": {"get": _op("research", "What the workbench can build on (features, cities)")},
        "/api/research/plans": {"get": _op("research", "Saved plans")},
        "/api/research/plans/{plan_id}": {"get": _op("research", "One plan", errors={"404": "Unknown plan"})},
        "/api/research/plans/{plan_id}/export": {"get": _op("research", "A plan as Markdown")},
        "/api/research/jobs/{job_id}": _job("research"),
        "/api/research/digest": {"post": _started("research", "Read a paper into an editable digest", _obj(
            ("text",), text=STR, title=STR, language=STR, provider=STR))},
        "/api/research/analyze": {"post": _started("research", "Plan a study for an idea or a paper", _obj(
            ("text",), text=STR, title=STR, kind={"type": "string", "enum": ["idea", "paper"]},
            digest=_d(OBJ, "Edited digest from /digest"), language=STR, provider=STR))},
        "/api/research/extract": {"post": _op("research", "Text out of an uploaded paper", body=_obj(
            ("data",), data=_d(STR, "Base64 file contents"), name=STR))},
        "/api/research/delete": {"post": _op("research", "Delete a plan", body=_obj(("plan_id",), plan_id=STR))},
        "/api/research/studies": {
            "get": _op("research", "Studies (admin)"),
            "post": _started("research", "Compile a plan's design into a pre-registered study", _obj(
                ("plan_id",), plan_id=STR, design_index=INT, autopilot=BOOL, provider=STR)),
        },
        "/api/research/studies/{study_id}": {"get": _op("research", "One study", errors={"404": "Unknown study"})},
        "/api/research/studies/{study_id}/report": {"get": _op("research", "A study's report as Markdown")},
        **{
            f"/api/research/studies/{{study_id}}/{action}": {"post": _op(
                "research", summary, body=body, status=status, errors={"404": "Unknown study",
                                                                       "409": "Another study is running"})}
            for action, (summary, body, status) in study_actions.items()
        },
        "/api/research/games": {"get": _op("serious-games", "Designed games and sessions")},
        "/api/research/games/jobs/{job_id}": _job("serious-games"),
        "/api/research/games/design": {"post": _started("serious-games", "Design a game from a description", _obj(
            ("description",), description=STR, roles=_arr(OBJ), rounds=INT, provider=STR))},
        "/api/research/games/sessions": {"post": _op("serious-games", "Open a session of a game", body=_obj(
            ("game_id",), game_id=STR, seats=_d(OBJ, "role → agent id or `human`"), city=STR, provider=STR))},
        "/api/research/games/sessions/{session_id}": {"get": _op(
            "serious-games", "A session, as the host or one seat sees it",
            query=[_q("seat", "Seat token (omitted: host view)")], errors={"404": "Unknown session"})},
        "/api/research/games/sessions/{session_id}/export": {"get": _op("serious-games", "A session as Markdown")},
        "/api/research/games/sessions/{session_id}/act": {"post": _op(
            "serious-games", "A human seat's move", body=_obj(("seat",), seat=STR, action=STR, choice=STR))},
        "/api/research/games/sessions/{session_id}/resolve": {"post": _op(
            "serious-games", "Resolve the round now (fills missing moves)")},
        "/api/research/games/sessions/{session_id}/delete": {"post": _op("serious-games", "Delete a session")},
        "/api/research/games/{game_id}": {"get": _op("serious-games", "One game design",
                                                     errors={"404": "Unknown game"})},
        "/api/research/games/{game_id}/update": {"post": _op("serious-games", "Edit a game design",
                                                             body=_obj(("spec",), spec=OBJ))},
        "/api/research/games/{game_id}/delete": {"post": _op("serious-games", "Delete a game design")},
        "/api/research/policy": {"get": _op("policy-sim", "Policy simulation runs and sample limits")},
        "/api/research/policy/jobs/{job_id}": _job("policy-sim"),
        "/api/research/policy/run": {"post": _started("policy-sim", "Simulate, score and revise a policy", _obj(
            ("policy",), policy=STR, candidate=_d(STR, "Optional second version"), city=STR, city_name=STR,
            sample_size=INT, seed=INT, verify=BOOL, provider=STR))},
        "/api/research/policy/{run_id}": {"get": _op("policy-sim", "One run", errors={"404": "Unknown policy run"})},
        "/api/research/policy/{run_id}/export": {"get": _op("policy-sim", "A run as Markdown")},
        "/api/research/policy/{run_id}/delete": {"post": _op("policy-sim", "Delete a run")},
        "/api/persona/list": {"get": _op("persona", "Distilled portraits")},
        "/api/persona/jobs/{job_id}": _job("persona"),
        "/api/persona/detail/{slug}": {"get": _op("persona", "One portrait", errors={"404": "Unknown persona"})},
        "/api/persona/distill": {"post": _started("persona", "Research and distill a real person", _obj(
            ("subject",), subject=_d(STR, "Name or URL"), provider=STR))},
        "/api/persona/deploy": {"post": _op("persona", "Create a resident from a portrait", body=_obj(
            ("slug",), slug=STR, identity=_d(OBJ, "Field overrides"), state=OBJ))},
        "/api/persona/install-skill": {"post": _op("persona", "Install the portrait as a skill", body=_obj(
            ("slug",), slug=STR, overwrite=BOOL))},
        "/api/persona/delete": {"post": _op("persona", "Delete a portrait", body=_obj(("slug",), slug=STR))},
    }


# -- parallel worlds ------------------------------------------------------------------


def _parallel() -> dict[str, Any]:
    experiment = _obj(
        ("worlds",), worlds=_d(_arr(OBJ), "2–8 worlds: id, label, role, events, config, dose"),
        baseline_id=STR, note=STR, seeds=_d(INT_LIST, "One grouped experiment per seed"),
        reset=BOOL)
    root_q = _q("root", "Experiment root from /experiments", required=True)
    baseline_q = _q("baseline", "Baseline world (default: the spec's)")
    return {
        "/api/parallel-worlds/overview": {"get": _op("parallel-worlds", "Current experiment and its worlds")},
        "/api/parallel-worlds/experiments": {"get": _op("parallel-worlds", "Finished experiments")},
        "/api/parallel-worlds/experiment": {"get": _op(
            "parallel-worlds", "Counterfactual estimates of one experiment", query=[root_q, baseline_q],
            errors={"400": "root is required", "404": "Unknown experiment"})},
        "/api/parallel-worlds/heterogeneity": {"get": _op(
            "parallel-worlds", "Effect by resident subgroup", query=[
                root_q, _q("world", "Treated world", required=True), _q("metric", "Metric", required=True),
                baseline_q], errors={"400": "Missing parameters", "404": "Unknown experiment"})},
        "/api/parallel-worlds/interpretation": {"get": _op(
            "parallel-worlds", "Saved model reading of an experiment", query=[root_q, baseline_q])},
        "/api/parallel-worlds/job": {"get": _op("parallel-worlds", "The experiment job, or null",
                                                query=[_q("id", "Job id")], ok=_obj(job=JOB))},
        "/api/parallel-worlds/preview": {"post": _op("parallel-worlds", "Check a spec and describe each world",
                                                     body=experiment)},
        "/api/parallel-worlds/sweep": {"post": _op(
            "parallel-worlds", "Expand a one-parameter sweep into worlds (runs nothing)", body=_obj(
                ("path", "values"), path=_d(STR, "Dotted numeric config path, e.g. economy.shocks.layoff_base_prob"),
                values=_d(_arr({"type": "number"}), "Values to try; the configured value is the baseline"),
                placebo=_d(BOOL, "Add an exact copy of the baseline as the noise floor"),
                events=_d(_arr(OBJ), "Events copied into every world")),
            errors={"400": "Unknown or non-numeric path, reserved key, or bad values"})},
        "/api/parallel-worlds/start": {"post": _op(
            "parallel-worlds", "Run an experiment", body=experiment, status="202",
            errors={"400": "Invalid spec", "409": "An experiment is already running"})},
        "/api/parallel-worlds/stop": {"post": _op("parallel-worlds", "Stop the running experiment")},
        "/api/parallel-worlds/interpret": {"post": _op(
            "parallel-worlds", "One model call reading the estimates", body=_obj(
                ("root",), root=STR, baseline=STR, provider=STR, language=STR))},
    }


# -- playground ---------------------------------------------------------------------


def _games() -> dict[str, Any]:
    city_agents = {"city": STR, "agent_ids": INT_LIST}
    runs = {
        "disaster": ("Live through a disaster stage by stage", _obj(
            ("agent_ids",), **city_agents, disaster_id=STR, custom=OBJ, stages=INT)),
        "rumor": ("Spread a rumor over the roster's network", _obj(
            ("agent_ids",), **city_agents, rumor_id=STR, custom=OBJ, seeds=INT_LIST, rounds=INT)),
        "referendum": ("Private vote, campaign, public vote", _obj(
            ("agent_ids",), **city_agents, motion_id=STR, custom=OBJ, campaign=STR)),
        "duel": ("Two teams, one task, opposed methods, a blind judge", _obj(
            ("team_a", "team_b"), city=STR, team_a=INT_LIST, team_b=INT_LIST, task_id=STR, custom=OBJ,
            rounds=INT)),
        "novel": ("Write a novel with residents as the cast", _obj(
            ("agent_ids",), **city_agents, style_id=STR, style_custom=STR, target_words=INT,
            chunks_per_chapter=INT, outline=OBJ, title_hint=STR)),
        "jury": ("Deliberate a case to a verdict", _obj(
            ("agent_ids",), **city_agents, case_id=STR, custom=OBJ, rounds=INT, question_key=STR)),
        "commentary": ("Residents comment on a piece of news", _obj(
            ("agent_ids",), **city_agents, url=STR, title=STR, body=STR)),
    }
    paths: dict[str, Any] = {
        "/api/games/agents": {"get": _op("games", "Residents to pick from", query=[CITY_Q])},
        "/api/games/persuasion/sessions": {"get": _op("games", "Persuasion sessions (in memory, last 50)")},
        "/api/games/persuasion/sessions/{session_id}": {"get": _op("games", "One persuasion session",
                                                                   errors={"404": "Unknown session"})},
        "/api/games/persuasion/start": {"post": _op("games", "Ask a resident a question; open a session", body=_obj(
            ("agent_id", "question"), city=STR, agent_id=INT, question=STR, max_turns=INT))},
        "/api/games/persuasion/say": {"post": _op(
            "games", "One persuasion turn (settles after the last)", body=_obj(
                ("session_id", "message"), session_id=STR, message=STR), errors={"404": "Unknown session"})},
        "/api/games/persuasion/settle": {"post": _op(
            "games", "Ask again and let a judge decide whether the position moved",
            body=_obj(("session_id",), session_id=STR), errors={"404": "Unknown session"})},
        "/api/games/roommate/catalogue": {"get": _op("games", "Roommate mode: limits, room layout, activities")},
        "/api/games/roommate/sessions": {"get": _op("games", "Roommate sessions (in memory, last 30)")},
        "/api/games/roommate/sessions/{session_id}": {"get": _op(
            "games", "One roommate session: residents, events, relationships",
            errors={"404": "Unknown session"})},
        "/api/games/roommate/start": {"post": _op(
            "games", "Open a roommate session (no model calls)",
            body=_obj(("city", "agent_ids"), city=STR, agent_ids=INT_LIST, vibe=STR,
                      tick_minutes=INT, max_hours=INT))},
        "/api/games/roommate/tick": {"post": _op(
            "games", "Advance the simulation by N ticks (model calls only on interactions)",
            body=_obj(("session_id",), session_id=STR, steps=INT),
            errors={"404": "Unknown session"})},
        "/api/games/roommate/end": {"post": _op(
            "games", "Mark a roommate session finished and stop the simulation",
            body=_obj(("session_id",), session_id=STR),
            errors={"404": "Unknown session"})},
        "/api/games/roommate/sessions/{session_id}/direct": {"post": _op(
            "games", "Player override: send one resident to a room doing an activity",
            body=_obj(("agent_id", "activity"), agent_id=INT, activity=STR, room=STR, note=STR),
            errors={"404": "Unknown session", "400": "Bad agent_id / activity / room"})},
        "/api/games/whois/catalogue": {"get": _op("games", "Who's Human: topics and seat limits")},
        "/api/games/whois/rooms": {
            "get": _op("games", "Who's Human rooms the caller hosts (in memory)"),
            "post": _op(
                "games", "Open a room: residents and people at random numbers (no model calls until it opens)",
                body=_obj(city=STR, agents=INT, humans=INT, agent_ids=INT_LIST, rounds=INT,
                          topic_id=STR, custom=_obj(("text",), title=STR, text=STR))),
        },
        "/api/games/whois/rooms/{room_id}": {"get": _op(
            "games", "One room as a player (`seat`) or the host sees it; players never see who wrote or voted",
            query=[_q("seat", "A seat link's token; omitted = host view")], errors={"404": "Unknown room"})},
        "/api/games/whois/rooms/{room_id}/say": {"post": _op(
            "games", "A person's message for the open round", body=_obj(("seat", "text"), seat=STR, text=STR),
            errors={"404": "Unknown room"})},
        "/api/games/whois/rooms/{room_id}/vote": {"post": _op(
            "games", "A person's verdict on every other number: human or resident",
            body=_obj(("seat", "verdicts"), seat=STR, verdicts={"type": "object"}, reason=STR),
            errors={"404": "Unknown room"})},
        "/api/games/whois/rooms/{room_id}/next": {"post": _op(
            "games", "Host: close the round without the people who have not written",
            errors={"404": "Unknown room"})},
        "/api/games/whois/rooms/{room_id}/reveal": {"post": _op(
            "games", "Host: reveal with the ballots that are in", errors={"404": "Unknown room"})},
        "/api/games/rumor/graph": {"get": _op("games", "The network a rumor would travel (no model calls)",
                                              query=[CITY_Q, _q("agent_ids", "Comma-separated ids")])},
        "/api/games/novel/agents": {"get": _op("games", "Residents to cast", query=[CITY_Q])},
        "/api/games/guess/catalogue": {"get": _op("games", "Dilemmas")},
        "/api/games/guess/scoreboard": {"get": _op("games", "Guessing score")},
        "/api/games/guess/rounds/{round_id}": {"get": _op("games", "One round", errors={"404": "Unknown round"})},
        "/api/games/guess/deal": {"post": _op("games", "Deal a resident and a dilemma (no model calls)", body=_obj(
            city=STR, agent_id=_d(INT, "Omitted: random"), dilemma_id=_d(STR, "Omitted: random")))},
        "/api/games/guess/answer": {"post": _op("games", "Guess; the resident answers", body=_obj(
            ("round_id", "guess"), round_id=STR, guess=STR), errors={"404": "Unknown round"})},
        "/api/games/guess/again": {"post": _op("games", "Ask the same dilemma again (persona stability)",
                                               body=_obj(("round_id",), round_id=STR),
                                               errors={"404": "Unknown round"})},
    }
    for game, (summary, body) in runs.items():
        paths[f"/api/games/{game}/catalogue"] = {"get": _op("games", f"{game}: presets and limits")}
        paths[f"/api/games/{game}/runs"] = {"get": _op("games", f"{game}: finished rounds")}
        paths[f"/api/games/{game}/jobs/{{job_id}}"] = _job("games")
        paths[f"/api/games/{game}/run"] = {"post": _started("games", f"{game}: {summary}", body)}
    paths["/api/arena/tasks"] = {"get": _op("arena", "Task bank")}
    paths["/api/arena/agents"] = {"get": _op("arena", "Contestants of a city",
                                             query=[_q("city", "City", required=True)])}
    paths["/api/arena/jobs/{job_id}"] = _job("arena")
    paths["/api/arena/generate"] = {"post": _op("arena", "Generate tasks with a model", body=_obj(
        n=INT, categories=STR_LIST, difficulty=STR))}
    paths["/api/arena/run"] = {"post": _started("arena", "Run a round", _obj(
        ("city", "agent_ids"), city=STR, agent_ids=INT_LIST, task_ids=STR_LIST, custom_tasks=_arr(OBJ)))}
    paths["/api/arena/retain"] = {"post": _op("arena", "Keep the top k, eliminate the rest", body=_obj(
        ("city",), city=STR, leaderboard=_arr(OBJ), k=INT))}
    paths["/api/arena/refill"] = {"post": _op("arena", "Bring in new residents", body=_obj(
        ("city",), city=STR, from_city=STR, n=INT, city_root=STR, import_payload=OBJ))}
    paths["/api/arena/state"] = {"post": _op("arena", "Who is eliminated in a city", body=_obj(("city",), city=STR))}
    return paths


TAGS = (
    "meta", "auth", "worlds", "cluster", "cluster-node", "play", "config", "agents", "run", "analytics", "trace",
    "life-events", "todos", "collaboration", "kernel", "infosources", "bench", "economy", "family", "home",
    "moltbook", "settings", "external-systems", "city", "population", "import", "interview", "research",
    "serious-games", "policy-sim", "persona", "parallel-worlds", "games", "arena",
)

_PARAM = re.compile(r"\{([^}]+)\}")


def operation_id(method: str, template: str) -> str:
    """``("get", "/api/agents/{agent_id}/state")`` → ``get_agents_agent_id_state``."""
    words = [re.sub(r"[^0-9a-zA-Z]+", "_", part.strip("{}")) for part in template[len("/api/"):].split("/") if part]
    return "_".join([method, *words])


def _sample(template: str) -> str:
    return _PARAM.sub("1", template)


def _finish(paths: dict[str, Any]) -> dict[str, Any]:
    """Add what every operation has: path parameters, id, access level, error shape."""
    for template, item in paths.items():
        names = _PARAM.findall(template)
        for method, op in item.items():
            declared = {p["name"] for p in op.get("parameters", []) if p.get("in") == "path"}
            path_params = [{"name": name, "in": "path", "required": True, "schema": STR}
                           for name in names if name not in declared]
            if path_params:
                op["parameters"] = path_params + op.get("parameters", [])
            op["operationId"] = operation_id(method, template)
            if op["tags"] != ["cluster-node"]:
                op["x-gaworld-access"] = policy.required(method.upper(), _sample(template))
            if method == "post" and policy.quota_gated(_sample(template)):
                op["x-gaworld-quota"] = True
            op["responses"].setdefault("default", _err("Error"))
    return paths


DESCRIPTION = """\
Every route of the GAWorld dashboard (default port 8766). Conventions:

* JSON in, JSON out (UTF-8). Errors are `{"error": "..."}` with 400 (bad input), 401 (not signed in),
  403 (not allowed), 404 (unknown thing or route), 405 (known route, other method; `Allow` lists the
  methods), 409 (busy / conflicting state), 413 (body too large), 429 (daily model quota used up),
  500 (server fault).
* Long work starts a background job: `202` + `{"job_id"}`; poll the operation's `jobs/{job_id}` route
  until `status` is no longer `running` (`done` → `result`; `failed` / `error` → `error`).
* Authentication applies only when the server has `GAWORLD_DASHBOARD_TOKEN` set (send it as a Bearer
  token) or an account database (sign in with `POST /api/auth/login`, then send the `gaworld_session`
  cookie). `x-gaworld-access` is the level an account needs; `x-gaworld-quota` marks requests refused
  once a member's daily model quota is used up.
* With accounts, every route reads and writes the active world, chosen by `POST /api/worlds/select`
  (the `gaworld_world` cookie).
* `gaworld.client.GAWorldClient` calls any operation by its `operationId`.
"""


def spec() -> dict[str, Any]:
    paths: dict[str, Any] = {}
    for group in (_core, _simulation, _panels, _cities, _studies, _parallel, _games, _organizations):
        paths.update(group())
    return {
        "openapi": "3.1.0",
        "info": {"title": "GAWorld Dashboard API", "version": "1.0", "description": DESCRIPTION},
        "servers": [{"url": "http://127.0.0.1:8766"}],
        "security": [{}, {"bearer": []}, {"cookie": []}, {"session": []}],
        "tags": [{"name": name} for name in TAGS],
        "paths": _finish(paths),
        "components": {
            "schemas": {
                "Error": _obj(("error",), error=STR),
                "JobStarted": _obj(("job_id",), job_id=STR),
                "Job": _obj(
                    ("id", "status"), id=STR, kind=STR,
                    status=_d(STR, "running, then done / failed / error / stopped"),
                    progress=_d(NUM, "0–1"), message=STR, started_at=NUM,
                    finished_at={"type": ["number", "null"]}, result={}, error={"type": ["string", "null"]}),
            },
            "securitySchemes": {
                "bearer": {"type": "http", "scheme": "bearer",
                           "description": "The operator token, GAWORLD_DASHBOARD_TOKEN"},
                "cookie": {"type": "apiKey", "in": "cookie", "name": "gaworld_token",
                           "description": "Set by opening /?token=<token> once in a browser"},
                "session": {"type": "apiKey", "in": "cookie", "name": "gaworld_session",
                            "description": "Set by POST /api/auth/login when accounts are on"},
                "node": {"type": "http", "scheme": "bearer",
                         "description": "A distributed-world node token, <world>.<node>.<secret>"},
            },
        },
    }


@lru_cache(maxsize=1)
def _templates() -> tuple[tuple[re.Pattern[str], frozenset[str]], ...]:
    out = []
    for template, item in spec()["paths"].items():
        segments = ("[^/]+" if _PARAM.fullmatch(seg) else re.escape(seg) for seg in template.split("/"))
        pattern = re.compile("^" + "/".join(segments) + "$")
        out.append((pattern, frozenset(method.upper() for method in item)))
    return tuple(out)


def allowed_methods(path: str) -> frozenset[str]:
    """Methods the document lists for a concrete path; empty when it lists none."""
    path = path.rstrip("/") or path
    found: set[str] = set()
    for pattern, methods in _templates():
        if pattern.match(path):
            found |= methods
    return frozenset(found)
