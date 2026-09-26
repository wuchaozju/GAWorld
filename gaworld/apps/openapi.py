"""OpenAPI 3.1 description of the dashboard's external API, served at
``GET /api/openapi.json``.

Scope: the programmatic surface meant for other systems — kernel interventions,
the record stream, information sources, benchmarks and economy. The console's
own panel routes (population studio, arena, family editor, …) are not listed
yet; see docs/API_REFERENCE.md for those.

Kept as Python rather than a JSON file so shared shapes are written once.
``tests/test_openapi.py`` checks the document is valid and that every listed
path is actually routed, so it cannot silently drift from the server.
"""

from __future__ import annotations

from typing import Any

ERROR = {"$ref": "#/components/schemas/Error"}


def _json(schema: dict[str, Any] | None = None, description: str = "OK") -> dict[str, Any]:
    return {"description": description,
            "content": {"application/json": {"schema": schema or {"type": "object"}}}}


def _err(description: str) -> dict[str, Any]:
    return _json(ERROR, description)


def _q(name: str, description: str, schema: dict | None = None, required: bool = False) -> dict:
    return {"name": name, "in": "query", "required": required, "description": description,
            "schema": schema or {"type": "string"}}


def _p(name: str, description: str) -> dict:
    return {"name": name, "in": "path", "required": True, "description": description,
            "schema": {"type": "string"}}


def _get(summary: str, tag: str, *, params=(), ok=None, errors=None, description: str = "") -> dict:
    op = {"tags": [tag], "summary": summary, "parameters": list(params),
          "responses": {"200": ok or _json(), **(errors or {})}}
    if description:
        op["description"] = description
    return op


INTERVENTION_REQUEST = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "kwargs": {"type": "object"},
        "queued_at": {"type": "number"},
        "status": {"type": "string", "enum": ["pending", "applied", "failed"]},
        "applied_at": {"type": "object", "properties": {"day": {"type": "integer"}, "time": {"type": "string"}}},
        "result": {},
        "error": {"type": "string"},
    },
    "required": ["id", "name", "status"],
}

BENCH_JOB = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "kind": {"type": "string", "enum": ["bench", "rubric"]},
        "status": {"type": "string", "enum": ["running", "done", "failed"]},
        "command": {"type": "string"},
        "started_at": {"type": "number"},
        "finished_at": {"type": ["number", "null"]},
        "returncode": {"type": ["integer", "null"]},
        "scorecard": {"type": ["object", "null"], "description": "This job's own scorecard, kept after later runs"},
        "log_tail": {"type": "string"},
    },
}


def spec() -> dict[str, Any]:
    paths: dict[str, Any] = {
        # -- kernel ---------------------------------------------------------
        "/api/interventions": {
            "get": _get(
                "List interventions available to the running simulation", "kernel",
                ok=_json({"type": "object", "properties": {
                    "running": {"type": "boolean"},
                    "registered": {"type": "array", "items": {"type": "string"}},
                    "pending": {"type": "array", "items": INTERVENTION_REQUEST},
                    "applied": {"type": "array", "items": INTERVENTION_REQUEST}}}),
            ),
        },
        "/api/interventions/{key}": {
            "get": _get(
                "Poll one queued request", "kernel",
                params=[_p("key", "Request id returned by the POST")],
                ok=_json(INTERVENTION_REQUEST), errors={"404": _err("Unknown request id")},
            ),
            "post": {
                "tags": ["kernel"],
                "summary": "Queue an intervention for the running simulation",
                "description": "The JSON body is the intervention's keyword arguments. Applied at the next "
                               "simulation tick through `controller.intervene` and audited to the "
                               "`controller.intervention` record table. Built-ins: `set_agent_state` "
                               "(agent_id, key, value), `update_config` (path, value), `remove_agent` "
                               "(agent_id), `inject_life_event`, `inject_info_item` (source_id, title, "
                               "excerpt?, url?); plugins may register more — see `GET /api/interventions`.",
                "parameters": [_p("key", "Registered intervention name")],
                "requestBody": {"required": False, "content": {"application/json": {"schema": {"type": "object"}}}},
                "responses": {
                    "202": _json(INTERVENTION_REQUEST, "Queued"),
                    "404": _json({"allOf": [ERROR, {"type": "object", "properties": {
                        "registered": {"type": "array", "items": {"type": "string"}}}}]},
                        "Name not registered by the running simulation"),
                    "409": _err("No simulation is running"),
                },
            },
        },
        "/api/events/stream": {
            "get": {
                "tags": ["kernel"],
                "summary": "Server-Sent Events feed of Recorder rows",
                "description": "Every row appended to `output/records/<table>.jsonl` after the connection "
                               "opens is sent as one event whose `event:` is the table name and `data:` "
                               "the row JSON. Common tables: `agent.step`, `controller.intervention`, "
                               "`controller.intervention_failed`, `infosources.injected`, "
                               "`infosources.read`, `traffic.tick`. Keep-alive comment every 15 s.",
                "parameters": [_q("tables", "Comma-separated table names to include (default: all)")],
                "responses": {"200": {"description": "Event stream",
                                      "content": {"text/event-stream": {"schema": {"type": "string"}}}}},
            },
        },
        # -- information sources -------------------------------------------
        "/api/infosources/sources": {"get": _get("Source registry with cache counts", "infosources")},
        "/api/infosources/feed": {"get": _get(
            "Cached items", "infosources",
            params=[_q("source_id", "Only this source"), _q("limit", "Max items", {"type": "integer", "default": 20})])},
        "/api/infosources/diets": {"get": _get(
            "Residents' media diets", "infosources", params=[_q("agent_id", "Only this resident")],
            errors={"404": _err("No diet for that resident")})},
        "/api/infosources/reads": {"get": _get(
            "Feed reads (`infosources.read`), newest first", "infosources",
            params=[_q("url", "Item URL, e.g. gaworld://injected/1"), _q("source_id", "Source"),
                    _q("agent_id", "Resident"), _q("limit", "Max rows", {"type": "integer", "default": 100})])},
        # -- benchmarks ------------------------------------------------------
        "/api/bench/run": {"post": {
            "tags": ["bench"],
            "summary": "Start a benchmark job (one at a time)",
            "description": "Options mirror the CLIs `benchmark/gaworld_bench.py` (kind=bench) and "
                           "`benchmark/rubric_bench.py` (kind=rubric). Unknown options are rejected; "
                           "path options must stay inside the repository.",
            "requestBody": {"required": True, "content": {"application/json": {"schema": {
                "type": "object", "required": ["kind"], "properties": {
                    "kind": {"type": "string", "enum": ["bench", "rubric"]},
                    "track": {"type": "string", "enum": ["A", "C"]}, "all": {"type": "boolean"},
                    "synthetic": {"type": "boolean"}, "output_dir": {"type": "string"},
                    "comparisons_root": {"type": "string"}, "run": {"type": "boolean"},
                    "days": {"type": "integer"}, "seed": {"type": "integer"},
                    "seeds": {"type": "string", "description": "Comma list, e.g. 1,2,3"},
                    "resume": {"type": "boolean"}, "fast": {"type": "boolean"},
                    "llm_provider": {"type": "string"}, "synthetic_mode": {"type": "string"},
                    "judges": {"type": "string"}, "samples_per_judge": {"type": "integer"},
                    "min_days": {"type": "integer"}, "ablate": {"type": "string"}, "dim": {"type": "string"}},
            }}}},
            "responses": {"202": _json(BENCH_JOB, "Started"), "400": _err("Invalid option"),
                          "409": _json({"type": "object"}, "Another job is running")},
        }},
        "/api/bench/jobs": {"get": _get("Recent jobs", "bench", ok=_json({"type": "object", "properties": {
            "jobs": {"type": "array", "items": BENCH_JOB}}}))},
        "/api/bench/jobs/{job_id}": {"get": _get(
            "One job", "bench", params=[_p("job_id", "Job id")], ok=_json(BENCH_JOB),
            errors={"404": _err("Unknown job")})},
        "/api/bench/scorecard": {"get": _get("Latest scorecards of both harnesses", "bench")},
        "/api/bench/reports": {"get": _get("Archived report names, newest first", "bench")},
        "/api/bench/reports/{name}": {"get": _get(
            "One archived report (Markdown)", "bench", params=[_p("name", "File name from the listing")],
            errors={"404": _err("Unknown report")})},
        # -- economy -------------------------------------------------------------
        "/api/economy/overview": {"get": _get(
            "Macro state, sector pools, conservation audit, wealth, city ledger", "economy")},
        "/api/economy/loans": {"get": _get(
            "Agent-to-agent loans, bank debt, two-sided ledger check", "economy")},
        "/api/economy/ledger": {"get": _get(
            "One resident's ledger series", "economy",
            params=[_q("agent_id", "Resident id", {"type": "integer"}, required=True),
                    _q("limit", "Last N rows", {"type": "integer"})],
            errors={"400": _err("Bad parameters"), "404": _err("No ledger")})},
        "/api/openapi.json": {"get": _get("This document", "meta")},
    }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "GAWorld Dashboard API",
            "version": "0.1",
            "description": "Programmatic surface of the GAWorld dashboard (default port 8766). "
                           "Authentication applies only when the server has GAWORLD_DASHBOARD_TOKEN set.",
        },
        "servers": [{"url": "http://127.0.0.1:8766"}],
        "security": [{}, {"bearer": []}, {"cookie": []}],
        "tags": [{"name": n} for n in ("kernel", "infosources", "bench", "economy", "meta")],
        "paths": paths,
        "components": {
            "schemas": {"Error": {"type": "object", "properties": {"error": {"type": "string"}},
                                  "required": ["error"]}},
            "securitySchemes": {
                "bearer": {"type": "http", "scheme": "bearer"},
                "cookie": {"type": "apiKey", "in": "cookie", "name": "gaworld_token",
                           "description": "Set by opening /?token=<token> once in a browser"},
            },
        },
    }
