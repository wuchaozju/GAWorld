"""BigFivePlugin — seeds OCEAN traits once, then gets out of the way.

One hook, ``agents.built``, because personality is a trait: it is decided
before the run and never touched again. There is no ``on_day_end`` drift
handler and that is deliberate — the measured pace of adult personality change
is on the order of 0.1-0.2 SD per *decade*, so a per-day drift term would be
noise dressed as psychology.

Two seeding paths:

* ``profile_path`` (``data/agents_big5.csv``) — z scores calibrated offline by
  ``scripts/calibrate_big5.py`` from the narrative 性格与情绪特征 paragraphs.
  This is the path the 51 Hangzhou residents take. Frozen on disk, so the
  values cannot drift between runs and cost nothing at boot.
* Population prior — a correlated multivariate normal draw, used when the file
  is missing or an agent is not in it. This is the right path for the
  synthetic town from ``gaworld/population/synth.py``, whose narrative
  personality text is itself generated from ``stress``/``voice_propensity``;
  scoring that text would recover the state variables and produce traits with
  no information beyond what the simulation already had.

Note what the plugin does *not* do: it never derives traits from
``agent["state"]``. That would make OCEAN a reparameterisation of
``risk_preference`` and friends, and the incremental-information criterion in
``docs/proposals/2026-08-20-big-five-personality.md`` would be structurally
impossible to pass.
"""

from __future__ import annotations

import csv
import math
import os
import random
from typing import Any

from gaworld.kernel import Plugin
from gaworld.logging_setup import get_logger
from gaworld.personality.traits import (
    DIMENSION_NAMES_ZH,
    DIMENSIONS,
    PROMPT_DEFAULTS,
    Z_CLIP,
)

_LOG = get_logger("gaworld.personality.plugin")

#: Order of the off-diagonal keys in ``sampling.correlations``.
_PAIRS = [(i, j) for i in range(len(DIMENSIONS)) for j in range(i + 1, len(DIMENSIONS))]


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def correlation_matrix(pairs: dict[str, float]) -> list[list[float]]:
    """Build the 5x5 OCEAN correlation matrix from the flat config dict."""
    size = len(DIMENSIONS)
    matrix = [[1.0 if i == j else 0.0 for j in range(size)] for i in range(size)]
    for i, j in _PAIRS:
        key = f"{DIMENSIONS[i]}{DIMENSIONS[j]}"
        value = float(pairs.get(key, pairs.get(f"{DIMENSIONS[j]}{DIMENSIONS[i]}", 0.0)) or 0.0)
        matrix[i][j] = matrix[j][i] = _clip(value, -0.95, 0.95)
    return matrix


def cholesky(matrix: list[list[float]]) -> list[list[float]]:
    """Lower-triangular Cholesky factor.

    Hand-rolled rather than via numpy so the plugin has no hard numeric
    dependency; at 5x5 the loop is cheaper than the import. A correlation
    matrix assembled from independently-chosen pairwise values is not
    guaranteed positive definite, so a non-positive pivot falls back to zero
    (which degrades the draw towards independence instead of raising).
    """
    size = len(matrix)
    lower = [[0.0] * size for _ in range(size)]
    for i in range(size):
        for j in range(i + 1):
            total = sum(lower[i][k] * lower[j][k] for k in range(j))
            if i == j:
                pivot = matrix[i][i] - total
                lower[i][j] = math.sqrt(pivot) if pivot > 1e-12 else 0.0
            elif lower[j][j] > 1e-12:
                lower[i][j] = (matrix[i][j] - total) / lower[j][j]
    return lower


def sample_traits(rng: random.Random, factor: list[list[float]]) -> dict[str, float]:
    """One correlated standard-normal OCEAN draw."""
    raw = [rng.gauss(0.0, 1.0) for _ in DIMENSIONS]
    return {
        dim: _clip(sum(factor[i][k] * raw[k] for k in range(i + 1)), -Z_CLIP, Z_CLIP)
        for i, dim in enumerate(DIMENSIONS)
    }


def load_profiles(path: str) -> dict[int, dict[str, Any]]:
    """Read the calibrated score file; ``{}`` when absent.

    Each entry is ``{"values": {...}, "source": str, "unstated": str,
    "redundant": str}``. The two provenance columns are carried rather than
    dropped because both are things a reader of the run output has to know:

    ``unstated``
        dimensions the source profile never described. Those score exactly 0,
        so they contribute nothing and render no anchor sentence — but that is
        indistinguishable from "measured, and average" unless it is recorded.
    ``redundant``
        dimensions ``scripts/big5_collinearity.py`` found to be largely
        predictable from the pre-existing state variables. A run must not
        present those as independent personality effects.
    """
    if not path or not os.path.exists(path):
        return {}
    profiles: dict[int, dict[str, Any]] = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            try:
                agent_id = int(str(row.get("id", "")).strip())
            except (TypeError, ValueError):
                continue
            values: dict[str, float] = {}
            for dim in DIMENSIONS:
                try:
                    values[dim] = _clip(float(row.get(dim, 0.0) or 0.0), -Z_CLIP, Z_CLIP)
                except (TypeError, ValueError):
                    values[dim] = 0.0
            profiles[agent_id] = {
                "values": values,
                "source": str(row.get("source", "") or "calibrated"),
                "unstated": str(row.get("unstated", "") or ""),
                "redundant": str(row.get("redundant", "") or ""),
            }
    return profiles


def rescale(records: list[dict[str, float]]) -> None:
    """Centre and scale each dimension to mean 0 / sd 1, in place.

    At n=51 the standard error of a sampled mean is ~0.14 SD, so an unrescaled
    draw can tilt the whole population's personality — an effect that would
    then be read as a finding about the town.
    """
    count = len(records)
    if count < 3:
        return
    for dim in DIMENSIONS:
        values = [rec[dim] for rec in records]
        mean = sum(values) / count
        var = sum((v - mean) ** 2 for v in values) / (count - 1)
        sd = math.sqrt(var)
        if sd < 1e-9:
            continue
        for rec in records:
            rec[dim] = _clip((rec[dim] - mean) / sd, -Z_CLIP, Z_CLIP)


class BigFivePlugin(Plugin):
    id = "big_five"

    # Personality works on its own: no economy, no family, no LLM.
    requires = ()

    def setup(self, ctx: Any) -> None:
        cfg = (getattr(ctx, "config", None) or {}).get("personality", {}) or {}
        self._cfg = cfg
        if not cfg.get("enabled", True):
            return
        ctx.bus.on("agents.built", self._seed)

    # -- seeding -------------------------------------------------------------

    def _channels(self) -> list[str]:
        raw = self._cfg.get("channels", {}) or {}
        return [name for name in ("rules", "prompt", "voice") if raw.get(name, True)]

    def _tuning(self) -> dict[str, float]:
        cfg = self._cfg
        return {
            "strength": float(cfg.get("strength", 1.0)),
            "amplitude": float(cfg.get("style_fit_amplitude", 0.6)),
            "band": float(cfg.get("modifier_band", 0.25)),
            "residual_ratio": float(cfg.get("residual_ratio", 0.6)),
        }

    def _prompt_knobs(self) -> dict[str, float]:
        """``personality.prompt.*`` in a form the read side can use.

        The names differ on purpose: the operator writes ``render_midpoint``
        because "midpoint" alone means nothing in a settings file, while
        :func:`anchor_lines` takes ``midpoint`` because its neighbours are
        ``spread`` and ``floor_z``. Translating here keeps both readable and
        keeps the leaf module free of CONFIG.
        """
        cfg = self._cfg.get("prompt", {}) or {}
        return {
            "midpoint": float(cfg.get("render_midpoint", PROMPT_DEFAULTS["midpoint"])),
            "spread": float(cfg.get("render_spread", PROMPT_DEFAULTS["spread"])),
            "strong_z": float(cfg.get("strong_z", PROMPT_DEFAULTS["strong_z"])),
            "max_dims": float(cfg.get("max_dims", PROMPT_DEFAULTS["max_dims"])),
            "floor_z": float(cfg.get("floor_z", PROMPT_DEFAULTS["floor_z"])),
        }

    def _seed(self, hook_ctx: dict[str, Any]) -> None:
        ctx = hook_ctx["sim"]
        agents = hook_ctx.get("agents") or []
        if not agents:
            return
        cfg = self._cfg
        sampling = cfg.get("sampling", {}) or {}
        profiles = load_profiles(str(cfg.get("profile_path", "") or ""))
        factor = cholesky(correlation_matrix(sampling.get("correlations", {}) or {}))
        seed = int(sampling.get("seed", 20260820) or 20260820)

        drawn: list[dict[str, float]] = []
        assigned: list[tuple[Any, dict[str, float], dict[str, str]]] = []
        for agent in agents:
            try:
                agent_id = int(agent["id"])
            except (KeyError, TypeError, ValueError):
                continue
            profile = profiles.get(agent_id)
            if profile:
                values = {dim: float(profile["values"][dim]) for dim in DIMENSIONS}
                meta = {
                    "source": str(profile.get("source", "calibrated")),
                    "unstated": str(profile.get("unstated", "")),
                    "redundant": str(profile.get("redundant", "")),
                }
            else:
                # Per-agent RNG stream, so the *draw* does not depend on where
                # the agent sits in the roster. The population rescale below
                # does depend on who else is in the run, which is the price of
                # not letting a small sample tilt the whole town.
                values = sample_traits(random.Random(seed * 1000003 + agent_id), factor)
                drawn.append(values)
                meta = {"source": "prior_sampled", "unstated": "", "redundant": ""}
            assigned.append((agent, values, meta))

        if drawn and sampling.get("rescale", True):
            rescale(drawn)

        channels = self._channels()
        tuning = self._tuning()
        knobs = self._prompt_knobs()
        for agent, values, meta in assigned:
            record = ctx.agent_ext(agent, self.id)
            record.update({
                "v": 1, "channels": list(channels),
                "tuning": dict(tuning), "prompt": dict(knobs), **meta,
            })
            record.update({dim: round(float(values[dim]), 4) for dim in DIMENSIONS})

        self._dump(ctx, assigned, channels)
        self._report(assigned, channels)

    # -- what the operator is told -------------------------------------------

    def _report(
        self,
        assigned: list[tuple[Any, dict[str, float], dict[str, str]]],
        channels: list[str],
    ) -> None:
        """Print what is in force, including the caveats.

        The two warnings below are printed on every run rather than left in a
        report, because both change how the run's results may be read and the
        report is the thing nobody opens.
        """
        total = len(assigned)
        calibrated = sum(1 for _, _, meta in assigned if meta["source"] != "prior_sampled")
        print(
            "🧬 大五人格已就绪："
            f"{total} 人（标定 {calibrated} / 先验采样 {total - calibrated}），"
            f"启用通道 {'+'.join(channels) if channels else '无'}"
        )

        # Dimensions the source profiles never described: those agents score
        # exactly 0, so personality is silent for them on that dimension.
        blank: dict[str, int] = {}
        for _, _, meta in assigned:
            for dim in filter(None, meta["unstated"].split("|")):
                blank[dim] = blank.get(dim, 0) + 1
        if blank:
            detail = "、".join(
                f"{DIMENSION_NAMES_ZH.get(d, d)} {n}/{total}" for d, n in sorted(blank.items())
            )
            print(f"   ⚪ 人物设定未描述、因而取 0（无倾向、不写进提示词）：{detail}")

        # Dimensions the collinearity gate rejected.
        flagged = sorted({d for _, _, meta in assigned
                          for d in filter(None, meta["redundant"].split("|"))})
        if flagged:
            names = "、".join(DIMENSION_NAMES_ZH.get(d, d) for d in flagged)
            print(
                f"   ⚠️  {names} 未通过共线性闸门：这些维度基本可由已有状态变量线性预测，"
                "本次运行中它们的效应不能当作独立的人格效应来解释"
                "（复核：python scripts/big5_collinearity.py）"
            )

    # -- audit trail ---------------------------------------------------------

    def _dump(
        self,
        ctx: Any,
        assigned: list[tuple[Any, dict[str, float], dict[str, str]]],
        channels: list[str],
    ) -> None:
        """Write the traits actually in force, so a run cannot be misread later."""
        out_dir = str(self._cfg.get("output_dir", "output/traits") or "output/traits")
        try:
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, "agent_traits.csv")
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    ["id", "name", *DIMENSIONS, "source", "channels", "unstated", "redundant"]
                )
                for agent, values, meta in assigned:
                    writer.writerow([
                        agent.get("id"),
                        agent.get("name", ""),
                        *[round(float(values[dim]), 4) for dim in DIMENSIONS],
                        meta["source"],
                        "|".join(channels),
                        meta["unstated"],
                        meta["redundant"],
                    ])
        except OSError as exc:
            _LOG.warning("big_five: trait dump failed: %s", exc)
        try:
            ctx.recorder.record(
                "big_five.seeded",
                {
                    "agents": len(assigned),
                    "channels": list(channels),
                    "tuning": self._tuning(),
                    "sources": sorted({meta["source"] for _, _, meta in assigned}),
                    "redundant_dimensions": sorted({
                        d for _, _, meta in assigned
                        for d in filter(None, meta["redundant"].split("|"))
                    }),
                },
            )
        except Exception as exc:  # pragma: no cover - recorder is best-effort
            _LOG.warning("big_five: recording failed: %s", exc)
