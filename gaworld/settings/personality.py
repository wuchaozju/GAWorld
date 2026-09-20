"""Big Five (OCEAN) personality defaults.

Three channels rather than one switch, because the whole point of the
subsystem is being able to tell "the decisions changed" apart from "the prose
changed": ``rules`` is deterministic modulation, ``prompt`` is anchor sentences
in decision prompts, ``voice`` is anchor sentences in the diary only. Turning a
channel off yields exactly the pre-personality behaviour on that path, which is
what makes the ablation arms in
``docs/proposals/2026-08-20-big-five-personality.md`` runnable.

Trait values are z scores read from ``profile_path``. When that file is absent
the plugin samples from the population prior below instead, so a fresh clone
still runs; the 51 Hangzhou residents are meant to use the calibrated file,
produced once by ``scripts/calibrate_big5.py``.

The amplitudes are not free parameters. ``style_fit_amplitude`` is sized
against the existing ``choose_action`` components (``growth_drive``=0.6,
``habit``~0.9), and ``scripts/big5_effect_ceiling.py`` reports the implied
trait/behaviour correlation for a given value — the acceptance band is
0.10-0.40, because personality that explains more than ~15% of behavioural
variance is louder than anything the literature supports.
"""

from __future__ import annotations

from typing import Any


def personality_settings() -> dict[str, Any]:
    return {
        "personality": {
            "enabled": True,
            # Independent channels, so an experiment can attribute an effect
            # to deterministic rules vs. prompt wording vs. diary style.
            # rules  = choose_action / dynamic behaviour / wealth drive / emotion baseline
            # prompt = anchor sentences in routine, action, goals, news, social prompts
            # voice  = anchor sentences in the diary only
            #
            # prompt defaults **off** as of the A4 arm (proposal section 15,
            # 1,632 calls). Turning it on is one line, and the authored
            # 人格与行为倾向 paragraph is unaffected either way -- it is not on
            # this channel and is always rendered. See config_docs for why.
            "channels": {"rules": True, "prompt": False, "voice": True},
            # Calibrated z scores, one row per agent. Frozen on disk and never
            # recomputed at runtime: an LLM re-scoring every boot would cost 150
            # calls and make two runs of the same seed disagree.
            "profile_path": "data/agents_big5.csv",
            "output_dir": "output/traits",
            # Global dial on every channel at once. Turn this down to weaken
            # personality without touching the loading tables.
            "strength": 1.0,
            # Additive component added to choose_action's weight sum, sized
            # like the components already there (growth_drive=0.6, habit~0.9).
            # 0.30 is not a guess: scripts/big5_effect_ceiling.py sweeps this
            # knob against the real choose_action and reports the implied
            # trait/behaviour correlation. 0.60 fails both acceptance windows
            # (E->social reaches 0.53 over 5 days, 0.73 aggregated); 0.40 fails
            # the aggregated one; 0.30 clears both with margin. Re-run that
            # script after changing this line.
            "style_fit_amplitude": 0.30,
            # Multiplicative modifiers are bounded to +-this. Narrow on
            # purpose: these hit small per-tick base rates that compound.
            "modifier_band": 0.25,
            # Idiosyncratic per-agent slack, as a ratio of the trait signal.
            # Without it the trait -> behaviour map is exact and the observed
            # correlation grows towards 1.0 with the observation window, which
            # would make any effect-size criterion meaningless.
            "residual_ratio": 0.6,
            "prompt": {
                # P(render this dimension) = Phi((|z| - midpoint) / spread).
                # A hard cutoff would turn a continuous trait into a three-way
                # classification with a jump at the threshold.
                "render_midpoint": 0.5,
                "render_spread": 0.4,
                # Past this |z| the stronger of the two anchor sentences is used.
                "strong_z": 1.5,
                # Personality is background, not the brief. Two lines is the
                # most that can be added without crowding out the situation.
                "max_dims": 2,
                # Below this |z| nothing is rendered at all, whatever the
                # probability above says. Distinct from render_midpoint: that
                # one decides how *distinctive* a pole must be to be worth
                # mentioning, this one decides whether the resident has a pole.
                # It is also the knob that separates the two things the prompt
                # channel could be: at 0.25 the anchors mostly restate what the
                # authored 人格与行为倾向 paragraph already says (|z| >= 0.5),
                # at 0.5 they only fill the gaps the paragraph left. See the
                # corpus-rewrite proposal, section 13.
                "floor_z": 0.25,
            },
            "emotion_baseline": {
                # Fixes a pre-existing defect: social contagion pulled emotion
                # towards the neighbour mean with nothing pulling it back to
                # the individual, so a long run flattened everyone onto one
                # value. Without this, N has nothing to act on.
                "enabled": True,
                # Was a hard-coded 0.1 in gaworld/sim/_cognition.py.
                "contagion_weight": 0.06,
                # Pull back towards the personal set point, applied on the
                # same step as contagion because the two are opposing forces on
                # the same variable. Comparable in size to contagion above:
                # much smaller and the averaging still wins, much larger and
                # nobody is affected by anybody.
                "recovery_rate": 0.08,
                # High N recovers more slowly, so a shock lasts longer and the
                # emotion series spreads wider — N's observable signature.
                "n_recovery_slope": 0.30,
                # The set point itself: N lowers it, E raises it. Anchored on
                # each agent's own starting emotion, so the heterogeneity
                # already in the state CSV survives.
                "n_baseline_slope": 0.12,
                "e_baseline_slope": 0.04,
            },
            "sampling": {
                # Used only when profile_path is missing (e.g. the synthetic
                # 500-person town, whose narrative personality text is itself a
                # function of its state variables and so cannot be scored
                # without circularity).
                "seed": 20260820,
                # Off-diagonal of the OCEAN correlation matrix, in the
                # o,c,e,a,n order. Consensus-range midpoints, not precise
                # literature values: N runs negative against the other four,
                # and A/C/E/O correlate mildly positively among themselves.
                "correlations": {
                    "oc": 0.05,
                    "oe": 0.25,
                    "oa": 0.10,
                    "on": -0.15,
                    "ce": 0.15,
                    "ca": 0.25,
                    "cn": -0.30,
                    "ea": 0.15,
                    "en": -0.25,
                    "an": -0.25,
                },
                # Rescale the drawn sample back to mean 0 / sd 1. At n=51 the
                # standard error of the mean is ~0.14 SD, so an unrescaled draw
                # can shift the whole town's personality.
                "rescale": True,
            },
        }
    }
