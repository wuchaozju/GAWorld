"""Run one city's share of a group interview, in its own process.

    python -m gaworld.interview --spec spec.json --out answers.json

Why a process per city rather than a loop: ``build_agent``, the memory store
and the vector DB all read module-level paths fixed at config load, and the
selected city is what those paths point at. Interviewing residents of two
cities in one process means mutating that config mid-flight — under a thread
pool, against a process-global SQLite connection. A child per city with
``GAWORLD_CONFIG_OVERRIDES={"city": "<slug>"}`` gets the isolation for free
and costs one interpreter start per city.

Progress is emitted as JSON lines on **stdout** so the parent can drive a
real progress bar; the final payload is written to ``--out`` rather than
stdout so a warning printed by some import cannot corrupt it. That mistake
is easy to make and impossible to debug from the panel.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from gaworld.interview.local import CityInterviewer
from gaworld.interview.runner import deserialize_material, run_round
from gaworld.interview.schema import normalize_spec


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m gaworld.interview",
        description="Answer one round of a group interview as residents of the configured city.",
    )
    parser.add_argument("--spec", required=True, help="Path to the session-spec JSON.")
    parser.add_argument("--out", required=True, help="Where to write the transcripts JSON.")
    args = parser.parse_args(argv)

    with open(args.spec, encoding="utf-8") as handle:
        payload = json.load(handle)

    spec = normalize_spec(payload)
    material = deserialize_material(payload.get("material"))
    interviewer = CityInterviewer(provider=spec.provider)

    def report(done: int, total: int, message: str) -> None:
        _emit({"type": "progress", "done": done, "total": total, "message": message})

    def stage(message: str) -> None:
        # A separate event type: this is narration, not a completed turn, and
        # folding it into `progress` would make the parent's counter advance
        # for work that has not been paid for yet.
        _emit({"type": "stage", "message": message})

    transcripts = run_round(
        spec,
        persona_fn=lambda respondent: interviewer.persona(respondent, spec.questions),
        ask_fn=interviewer.ask,
        material=material,
        report=report,
        stage=stage,
    )

    result = {
        "transcripts": [transcript.to_dict() for transcript in transcripts],
        "city": str(payload.get("city") or ""),
    }
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False)
    _emit({"type": "done", "respondents": len(transcripts)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
