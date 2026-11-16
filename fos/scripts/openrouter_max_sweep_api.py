"""OpenRouter API layer for the Qwen3.8-Max grammar sweep (TASK-1654).

This module is the "phone line" half of the OpenRouter sweep harness: it
knows how to talk to https://openrouter.ai/api/v1/chat/completions and how
to read what comes back, but it never decides WHAT to ask. The run half
(plan, legs, records, resume, CLI) lives in openrouter_max_sweep.py, which
re-exports everything defined here.

What each function / object does (plain language):
    SWEEP_PROFILE           - The run-family stamp put in every manifest.
    DEFAULT_MODEL           - The pinned OpenRouter model id (never the
                              bare alias).
    NONE_LEG_TEMPERATURE    - The plain-draw legs' temperature, taken from
                              the local sweep kit so they cannot drift.
    PERSONA_LEG_TEMPERATURE - The persona legs' temperature, ditto.
    DEFAULT_DRAWS           - Draws per (product x level) for the plan.
    PROMPT_USD_PER_M ...    - The dollar prices per million tokens used for
                              all cost accounting.
    DEFAULT_MAX_COST_USD    - The default spend cap (the harness refuses to
                              start a call that would push past it).
    DEFAULT_CONCURRENCY     - How many legs may run at once.
    MAX_TRIES               - The most times one call is attempted.
    DEFAULT_TIMEOUT_SECONDS - Seconds one call may take before it is cut.
    DEFAULT_MAX_TOKENS      - The answer-size cap: a truncation guard, not
                              a cost knob (only generated tokens bill).
    OPENROUTER_URL          - The chat-completions endpoint.
    DEFAULT_POOLS_FROM      - The archived persona pools reused by default
                              (taken from launch_queue so it cannot drift).
    PERSONA_INDICES         - The four spread pool personas the demographics
                              legs embody, in draw order 0..3.
    DEFAULT_LEVELS          - The default 11-step price ladder (percent of
                              regular price).
    OpenRouterError         - One failed API exchange (HTTP status + the
                              server's message).
    build_response_format() - The exact strict JSON schema every request
                              must carry (the API stand-in for the local
                              one-token grammar).
    parse_decision(text)    - Reads the answer's JSON object: True for
                              "purchase", False for "not purchase", None
                              for anything unparsable or unmapped.
    decision_text(text)     - The answer's raw decision string, or None
                              when the text holds no JSON decision field.
    call_cost_usd(usage)    - One response's token usage priced at the
                              pinned per-million rates.
    subsample_personas(pool) - The four personas at PERSONA_INDICES, in
                              order; refuses a pool too short to hold them.
    make_openrouter_chat_fn(...) - Wraps a transport into the sweep kit's
                              chat function: builds the payload (pinned
                              schema attached), retries 429/5xx and
                              connection errors/read timeouts with
                              growing backoff, aborts loudly on a rejected
                              model id, and reports each answer's token
                              usage to on_usage.
    make_http_transport(...) - The real network transport: one POST per
                              call, key in the Authorization header only
                              (the key never enters logs or errors).

Importing this module never opens a socket; dialing happens only when a
transport built by make_http_transport is actually called.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
for _dir in (_SCRIPT_DIR, _REPO_ROOT / "src"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from fos.experiments import sweep_kit  # noqa: E402
from launch_queue import DEFAULT_POOLS_FROM  # noqa: E402, F401 - re-exported

# The run-family stamp (manifests, run-dir names).
SWEEP_PROFILE = "R1-API-QWEN38MAX"

# The pinned model id: always the dated snapshot, never the bare alias
# that OpenRouter may re-point at a different model.
DEFAULT_MODEL = "qwen/qwen3.8-max-0902"

# Temperatures are taken from the local sweep kit by construction, so the
# API legs sample exactly like the local R1 runs did (1.0 draws, 0.0
# personas - the personas carry the heterogeneity, not sampling noise).
NONE_LEG_TEMPERATURE = sweep_kit._TEMPERATURE
PERSONA_LEG_TEMPERATURE = sweep_kit._PERSONA_TEMPERATURE

# Plan geometry and money knobs (see module docstring).
DEFAULT_DRAWS = 4
PROMPT_USD_PER_M = 2.0
COMPLETION_USD_PER_M = 6.0
DEFAULT_MAX_COST_USD = 15.0
DEFAULT_CONCURRENCY = 4
MAX_TRIES = 5
# Generous because this endpoint mandates reasoning: a reasoning model can
# legitimately think for minutes before answering, and cutting it off turns
# a slow-but-good call into a wasted one.
DEFAULT_TIMEOUT_SECONDS = 240.0

# The answer-size cap. Deliberately generous: the strict schema keeps the
# answer itself tiny, but this endpoint mandates reasoning (sending a
# reasoning-disable is rejected with HTTP 400), and a reasoning model
# burns tokens before the answer. The cap exists to stop that reasoning
# from starving the answer into an empty content string (every token
# still billed, nothing parsed - seen live at 64 tokens).
DEFAULT_MAX_TOKENS = 2048

# The endpoint every call POSTs to.
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# The four spread personas of the shared pool slice, in draw order; a
# demographics draw d always embodies PERSONA_INDICES[d].
PERSONA_INDICES = (40, 46, 52, 58)

# The full 11-step price ladder of the R1 sweep (percent of regular price).
DEFAULT_LEVELS: list[float] = [float(x) for x in range(0, 220, 20)]

# Exponential backoff: sleep 2s, 4s, 8s, ... between retries.
_BACKOFF_BASE_SECONDS = 2.0

# The strict JSON schema pinned for every request (the grammar stand-in).
_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "purchase_decision",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "decision": {"type": "string", "enum": ["purchase", "not purchase"]}
            },
            "required": ["decision"],
            "additionalProperties": False,
        },
    },
}

# Answer scavengers: some models wrap the JSON object in a markdown code
# fence or pad it with prose, so the parser tries the bare text, the
# unfenced text, then the first {...} block.
_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")
_FIRST_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class OpenRouterError(Exception):
    """One failed API exchange: an HTTP status plus the server's message.

    status -1 means the exchange never got an HTTP response at all
    (connection error or timeout). The message never contains the API key.
    """

    def __init__(self, status: int, message: str):
        super().__init__(f"OpenRouter HTTP {status}: {message}")
        self.status = status
        self.message = message


def build_response_format() -> dict[str, Any]:
    """Return a fresh copy of the pinned strict JSON decision schema."""
    return json.loads(json.dumps(_RESPONSE_FORMAT))


def _decision_object(content: Any) -> dict[str, Any] | None:
    """Pull the JSON object out of an answer's content text, or None.

    Tries the whole text, the text with a markdown code fence stripped,
    then the first {...} block; anything that is not a JSON object is None.
    """
    if not isinstance(content, str):
        return None
    text = content.strip()
    if not text:
        return None
    candidates = [text]
    unfenced = _CODE_FENCE.sub("", text).strip()
    if unfenced and unfenced != text:
        candidates.append(unfenced)
    braced = _FIRST_OBJECT.search(text)
    if braced:
        candidates.append(braced.group(0))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def parse_decision(content: Any) -> bool | None:
    """Read the answer's decision field: True, False, or None.

    Only the exact enum words count - "purchase" is True, "not purchase" is
    False, and any other value (or unparsable text, or an empty answer) is
    None so the caller records it as unclassified instead of guessing.
    """
    data = _decision_object(content)
    if data is None:
        return None
    decision = data.get("decision")
    if decision == "purchase":
        return True
    if decision == "not purchase":
        return False
    return None


def decision_text(content: Any) -> str | None:
    """The answer's raw decision string (even an unmapped one), or None.

    Keeping the model's own word beside the parsed flag lets a reader see
    WHAT an unclassified answer actually said instead of just that it did
    not parse.
    """
    data = _decision_object(content)
    if data is None:
        return None
    decision = data.get("decision")
    return decision if isinstance(decision, str) else None


def call_cost_usd(usage: dict[str, Any]) -> float:
    """Price one response's token usage at the pinned per-million rates."""
    prompt = float(usage.get("prompt_tokens") or 0)
    completion = float(usage.get("completion_tokens") or 0)
    return (
        prompt / 1_000_000 * PROMPT_USD_PER_M
        + completion / 1_000_000 * COMPLETION_USD_PER_M
    )


def subsample_personas(pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The four spread pool personas at PERSONA_INDICES, in draw order.

    A pool too short to hold index 58 is refused loudly - silently
    answering with fewer personas would quietly change the study geometry.
    """
    missing = [index for index in PERSONA_INDICES if index >= len(pool)]
    if missing:
        raise RuntimeError(
            f"persona pool holds only {len(pool)} personas; the pinned "
            f"subsample needs pool indices {PERSONA_INDICES} "
            f"(missing {missing}) - never silently shrink the design"
        )
    return [pool[index] for index in PERSONA_INDICES]


def _is_retryable(status: int) -> bool:
    """True for the polite-to-retry outcomes: rate limits (429), server
    hiccups (5xx), and exchanges that never got an answer at all (-1:
    connection errors and read timeouts - the most common transient
    failure, so they retry exactly like a 429 would)."""
    return status == -1 or status == 429 or 500 <= status <= 599


def _is_model_rejection(status: int) -> bool:
    """True for the statuses OpenRouter uses to reject an unknown model id."""
    return status in (400, 404)


def _content_of(response: dict[str, Any]) -> str:
    """The answer text of one parsed response body ("" when malformed).

    An empty string is deliberately not an error: the answer flows through
    parse_decision, which records it as unclassified.
    """
    choices = response.get("choices") if isinstance(response, dict) else None
    if not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return content if isinstance(content, str) else ""


def make_openrouter_chat_fn(
    transport: Callable[[dict[str, Any]], dict[str, Any]],
    model: str = DEFAULT_MODEL,
    sleep: Callable[[float], None] = time.sleep,
    max_tries: int = MAX_TRIES,
    on_usage: Callable[[dict[str, Any]], None] | None = None,
) -> Callable[[list[dict[str, str]], float], str]:
    """Wrap a transport into the sweep kit's chat function (the adapter).

    transport is a payload-dict-in, parsed-JSON-body-out callable (the real
    HTTP layer in production, a fake in tests). The returned function takes
    (messages, temperature) and returns the answer text, with the pinned
    response_format attached to every request, with reasoning left at
    the provider default (this endpoint mandates reasoning; disabling it
    is rejected with HTTP 400). Rate limits (429), server errors (5xx),
    and exchanges that never got an HTTP answer (connection errors and
    read timeouts, reported with status -1) are retried with growing
    sleeps, at most max_tries tries; a rejected model id aborts at once
    naming the model - never retried, never substituted. A transport that
    fails with some other non-OpenRouterError failure also consumes one
    try; if every try fails that way, the adapter raises
    OpenRouterError(-1) naming the underlying error - nothing is swallowed.
    Each successful call reports its usage block to on_usage (the caller's
    cost accounting), when given.
    """

    def chat_fn(messages: list[dict[str, str]], temperature: float) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "temperature": temperature,
            "response_format": build_response_format(),
            "max_tokens": DEFAULT_MAX_TOKENS,
        }
        for attempt in range(max_tries):
            try:
                response = transport(payload)
            except OpenRouterError as exc:
                if _is_retryable(exc.status) and attempt < max_tries - 1:
                    sleep(_BACKOFF_BASE_SECONDS * (2**attempt))
                    continue
                if _is_model_rejection(exc.status):
                    raise RuntimeError(
                        f"OpenRouter rejected the model id {model!r} "
                        f"(HTTP {exc.status}): {exc.message} - aborting "
                        "without retry or substitution"
                    ) from exc
                raise
            except Exception as exc:  # a try lost without any HTTP answer
                if attempt < max_tries - 1:
                    sleep(_BACKOFF_BASE_SECONDS * (2**attempt))
                    continue
                raise OpenRouterError(
                    -1,
                    f"transport failed {max_tries} tries without an HTTP "
                    f"answer; last error: {exc!r}",
                ) from exc
            if on_usage is not None:
                on_usage(response.get("usage") or {})
            return _content_of(response)
        raise OpenRouterError(-1, f"retry loop exhausted after {max_tries} tries")

    return chat_fn


def _body_excerpt(body: str, limit: int = 300) -> str:
    """The first `limit` characters of a response body, whitespace-flat."""
    flat = " ".join(body.split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


def make_http_transport(
    api_key: str,
    url: str = OPENROUTER_URL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Build the real network transport: one POST per call.

    The key rides ONLY in the Authorization header - it never enters an
    error message, a log line, or any written artifact. HTTP error statuses
    become OpenRouterError (so the retry layer can classify them); a call
    that never gets a response becomes OpenRouterError with status -1.
    """

    def transport(payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise OpenRouterError(exc.code, _body_excerpt(detail)) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise OpenRouterError(-1, f"connection error: {reason}") from None

    return transport
