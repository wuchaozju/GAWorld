"""
profiling.py -- lightweight live profiler for the headless council runs.

Drop-in timing instrument. Records named spans (LLM calls, model swaps,
prompt building, validation, whole rounds), aggregates them by category /
model / phase, and flushes a live snapshot to disk after every update so you
can watch where the time goes WHILE the run is still going:

    watch -n2 cat council_timing.txt     # human-readable, refreshes live
    tail -f council_timing.jsonl         # one JSON line per flush (for graphing)

Nothing here depends on the rest of the codebase. It degrades gracefully when
token/timing info isn't available (you still get wall-clock per model/phase).

Usage (module-level singleton, least invasive):

    from profiling import start_profiler, prof
    start_profiler(output_dir / "council_timing.txt")   # once, at run start
    ...
    p = prof()
    if p:
        with p.span("prompt_build", model=model, phase=phase):
            build_prompt(...)
    ...
    # around the actual LLM HTTP call (ideally inside LLMClient.chat):
    start = time.perf_counter()
    resp = do_request(...)
    if prof():
        prof().record_llm(model=model, phase=phase,
                          seconds=time.perf_counter() - start, response=resp)
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional


@dataclass
class _Bucket:
    count: int = 0
    seconds: float = 0.0
    prompt_tokens: int = 0
    gen_tokens: int = 0
    prompt_ms: float = 0.0     # server-side prefill time, if reported
    gen_ms: float = 0.0        # server-side decode time, if reported

    def add(self, seconds: float, prompt_tokens: int = 0, gen_tokens: int = 0,
            prompt_ms: float = 0.0, gen_ms: float = 0.0) -> None:
        self.count += 1
        self.seconds += seconds
        self.prompt_tokens += prompt_tokens
        self.gen_tokens += gen_tokens
        self.prompt_ms += prompt_ms
        self.gen_ms += gen_ms


class RunProfiler:
    """Thread-safe accumulator with live flush to disk."""

    def __init__(self, out_path: os.PathLike | str, flush_every: int = 1,
                 flush_interval: float = 2.0, echo: bool = True,
                 jsonl: bool = True):
        self.out = Path(out_path)
        self.out.parent.mkdir(parents=True, exist_ok=True)
        self.flush_every = max(1, flush_every)
        self.flush_interval = flush_interval
        self.echo = echo
        self.jsonl = jsonl

        self._lock = threading.RLock()
        self._t0 = time.perf_counter()
        self._by_category: dict[str, _Bucket] = {}
        self._by_model: dict[str, _Bucket] = {}
        self._by_phase: dict[str, _Bucket] = {}
        self._updates = 0
        self._last_flush = 0.0
        self._current: dict[str, Any] = {}
        self._active_phase: Optional[str] = None
        self._cold_pending: set[str] = set()
        self._by_warmth: dict[str, _Bucket] = {}

    # ---- recording -------------------------------------------------
    @staticmethod
    def _bucket(d: dict[str, _Bucket], key: str) -> _Bucket:
        b = d.get(key)
        if b is None:
            b = d[key] = _Bucket()
        return b

    def record(self, category: str, seconds: float, *, model: Optional[str] = None,
               phase: Optional[str] = None, prompt_tokens: int = 0,
               gen_tokens: int = 0, prompt_ms: float = 0.0,
               gen_ms: float = 0.0, warmth: Optional[str] = None) -> None:
        with self._lock:
            if phase is None:
                phase = self._active_phase
            self._bucket(self._by_category, category).add(
                seconds, prompt_tokens, gen_tokens, prompt_ms, gen_ms)
            if model is not None:
                self._bucket(self._by_model, model).add(
                    seconds, prompt_tokens, gen_tokens, prompt_ms, gen_ms)
            if phase is not None:
                self._bucket(self._by_phase, phase).add(
                    seconds, prompt_tokens, gen_tokens, prompt_ms, gen_ms)
            if warmth is not None:
                self._bucket(self._by_warmth, warmth).add(
                    seconds, prompt_tokens, gen_tokens, prompt_ms, gen_ms)
            self._updates += 1
            self._maybe_flush()

    @contextmanager
    def span(self, category: str, *, model: Optional[str] = None,
             phase: Optional[str] = None) -> Iterator[None]:
        start = time.perf_counter()
        self.set_current(category, model=model, phase=phase)
        try:
            yield
        finally:
            self.record(category, time.perf_counter() - start,
                        model=model, phase=phase)

    def record_llm(self, *, model: str, phase: Optional[str], seconds: float,
                   response: Any = None, prompt_tokens: int = 0,
                   gen_tokens: int = 0) -> None:
        """Record one LLM call. If `response` is a llama.cpp / OpenAI-style dict,
        prefill/decode token counts and server ms are auto-extracted so you get
        real prefill-vs-decode tok/s, not just wall clock."""
        p_tok, g_tok, p_ms, g_ms = self._extract(response)
        with self._lock:
            key = self._norm_model(model)
            if key in self._cold_pending:
                self._cold_pending.discard(key)
                warmth = "cold_after_swap"
            else:
                warmth = "warm"
        self.record(
            "llm_call", seconds, model=model, phase=phase,
            prompt_tokens=prompt_tokens or p_tok,
            gen_tokens=gen_tokens or g_tok,
            prompt_ms=p_ms, gen_ms=g_ms, warmth=warmth,
        )

    @staticmethod
    def _extract(response: Any) -> tuple[int, int, float, float]:
        if not isinstance(response, dict):
            return 0, 0, 0.0, 0.0
        usage = response.get("usage") or {}
        p_tok = usage.get("prompt_tokens", 0) or 0
        g_tok = usage.get("completion_tokens", 0) or 0
        # llama.cpp puts detailed server timings here (may be nested under choices)
        t = response.get("timings") or {}
        if not t:
            choices = response.get("choices") or []
            if choices and isinstance(choices[0], dict):
                t = choices[0].get("timings") or {}
        p_tok = p_tok or (t.get("prompt_n", 0) or 0)
        g_tok = g_tok or (t.get("predicted_n", 0) or 0)
        p_ms = t.get("prompt_ms", 0.0) or 0.0
        g_ms = t.get("predicted_ms", 0.0) or 0.0
        return p_tok, g_tok, p_ms, g_ms

    @staticmethod
    def _norm_model(m: Any) -> str:
        """Normalize 'openai/gpt-oss-20b' and 'gpt-oss-20b' to one key."""
        return str(m or "").rsplit("/", 1)[-1].strip().lower()

    def mark_cold(self, model: str) -> None:
        """Mark that the NEXT llm call for `model` is a post-swap cold call."""
        with self._lock:
            self._cold_pending.add(self._norm_model(model))

    def set_phase(self, phase: Optional[str]) -> None:
        """Set active phase; LLM records with phase=None inherit it."""
        with self._lock:
            self._active_phase = phase

    def set_current(self, label: str, *, model: Optional[str] = None,
                    phase: Optional[str] = None) -> None:
        with self._lock:
            self._current = {
                "doing": label, "model": model, "phase": phase,
                "since_s": round(time.perf_counter() - self._t0, 1),
            }

    # ---- flushing --------------------------------------------------
    def _maybe_flush(self) -> None:
        now = time.perf_counter()
        if (self._updates % self.flush_every == 0
                or now - self._last_flush >= self.flush_interval):
            self.flush()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            elapsed = time.perf_counter() - self._t0
            return {
                "elapsed_s": round(elapsed, 1),
                "current": dict(self._current),
                "by_category": self._dump(self._by_category, elapsed),
                "by_model": self._dump(self._by_model, elapsed),
                "by_phase": self._dump(self._by_phase, elapsed),
                "by_warmth": self._dump(self._by_warmth, elapsed),
                "swap_tax": self._swap_tax(),
            }

    def _swap_tax(self) -> dict[str, Any]:
        """Estimate total swap cost = load time + cold-cache penalty on the
        first call after each swap. Assumes caller holds the lock."""
        warm = self._by_warmth.get("warm")
        cold = self._by_warmth.get("cold_after_swap")
        swap = self._by_category.get("model_swap")
        load_s = swap.seconds if swap else 0.0
        n_cold = cold.count if cold else 0
        mean_warm = (warm.seconds / warm.count) if warm and warm.count else 0.0
        mean_cold = (cold.seconds / cold.count) if cold and cold.count else 0.0
        cold_penalty = max(0.0, mean_cold - mean_warm) * n_cold
        return {
            "load_s": round(load_s, 1),
            "n_swaps": swap.count if swap else 0,
            "n_cold_calls": n_cold,
            "mean_warm_call_s": round(mean_warm, 2),
            "mean_cold_call_s": round(mean_cold, 2),
            "cold_cache_penalty_s": round(cold_penalty, 1),
            "total_swap_tax_s": round(load_s + cold_penalty, 1),
        }

    @staticmethod
    def _dump(d: dict[str, _Bucket], elapsed: float) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, b in sorted(d.items(), key=lambda kv: -kv[1].seconds):
            row: dict[str, Any] = {
                "count": b.count,
                "total_s": round(b.seconds, 1),
                "pct_wall": round(100 * b.seconds / elapsed, 1) if elapsed else 0.0,
                "mean_s": round(b.seconds / b.count, 2) if b.count else 0.0,
            }
            if b.prompt_tokens or b.gen_tokens:
                row["prompt_tok"] = b.prompt_tokens
                row["gen_tok"] = b.gen_tokens
            if b.prompt_ms:
                row["prefill_tok_s"] = round(1000 * b.prompt_tokens / b.prompt_ms, 1)
            if b.gen_ms:
                row["decode_tok_s"] = round(1000 * b.gen_tokens / b.gen_ms, 1)
            out[key] = row
        return out

    def flush(self) -> None:
        with self._lock:
            snap = self.snapshot()
            self._last_flush = time.perf_counter()
        # atomic write so `cat` / `watch` never catch a half-written file
        tmp = self.out.with_suffix(self.out.suffix + ".tmp")
        tmp.write_text(self._render(snap))
        os.replace(tmp, self.out)
        if self.jsonl:
            with open(self.out.with_suffix(".jsonl"), "a") as f:
                f.write(json.dumps(snap) + "\n")
        if self.echo:
            c = snap["current"]
            print(f"[prof {snap['elapsed_s']}s] now={c.get('doing')} "
                  f"model={c.get('model')} phase={c.get('phase')}",
                  file=sys.stderr, flush=True)

    @staticmethod
    def _render(snap: dict[str, Any]) -> str:
        lines = [f"elapsed: {snap['elapsed_s']}s"]
        c = snap["current"]
        lines.append(
            f"now: {c.get('doing')}  model={c.get('model')}  phase={c.get('phase')}")
        for title, key in (("BY MODEL / INSTANCE", "by_model"),
                           ("BY CATEGORY", "by_category"),
                           ("BY PHASE", "by_phase"),
                           ("BY WARMTH (llm calls)", "by_warmth")):
            rows = snap[key]
            if not rows:
                continue
            lines.append("")
            lines.append(title)
            for name, r in rows.items():
                extra = ""
                if "prefill_tok_s" in r:
                    extra += f"  prefill={r['prefill_tok_s']}t/s"
                if "decode_tok_s" in r:
                    extra += f"  decode={r['decode_tok_s']}t/s"
                if "prompt_tok" in r:
                    extra += f"  ptok={r['prompt_tok']} gtok={r['gen_tok']}"
                lines.append(
                    f"  {name:24s} {r['pct_wall']:5.1f}%  {r['total_s']:8.1f}s  "
                    f"n={r['count']:<4d} mean={r['mean_s']}s{extra}")
        t = snap.get("swap_tax") or {}
        if t.get("n_swaps"):
            lines.append("")
            lines.append("SWAP TAX (estimated)")
            lines.append(
                f"  {t['n_swaps']} swap(s), {t['load_s']}s load"
                f" + {t['n_cold_calls']} cold call(s) "
                f"(cold {t['mean_cold_call_s']}s vs warm {t['mean_warm_call_s']}s)"
                f" = {t['cold_cache_penalty_s']}s cold-cache"
                f"  ->  ~{t['total_swap_tax_s']}s total")
        return "\n".join(lines) + "\n"


# ---- module-level singleton (least invasive to thread through the stack) ----
_ACTIVE: Optional[RunProfiler] = None


def start_profiler(out_path: os.PathLike | str, **kwargs: Any) -> RunProfiler:
    global _ACTIVE
    _ACTIVE = RunProfiler(out_path, **kwargs)
    return _ACTIVE


def prof() -> Optional[RunProfiler]:
    return _ACTIVE
