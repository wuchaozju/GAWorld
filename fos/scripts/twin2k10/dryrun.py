# This file is the twin2k10 study's offline rehearsal: everything the
# runner's --dry-run flag does instead of touching a model server. It
# prints the cell counts for the mode requested (the full 57,000-cell
# grid, the --smoke filter's 38 cells, or --preflight-only's persona-0
# cells), then renders EVERY first-token item's prompt pair with a
# clearly-synthetic placeholder persona and checks each one carries its
# exact stimulus wording and lettered option lines. It writes nothing
# anywhere. Functions:
#   dry_run             — the whole rehearsal (counts + prompt checks);
#   log_grid_counts     — the production grid's counts per model;
#   log_preflight_counts— the persona-0 preflight counts (no grid);
#   log_smoke_coverage  — the smoke filter's grid shape + item kinds;
#   check_prompt_pair   — one rendered pair's exactness checks;
#   _item_prompt_pairs  — every (system, item user prompt) pair, checked.

from datetime import datetime, timezone

from twin2k10 import cells, config, experiments, prompts

# A clearly-synthetic persona so --dry-run can render real prompts with no
# model server and no pool on disk (never used for actual measurements).
PLACEHOLDER_PERSONA = {
    "age": 34, "gender": "woman", "education": "bachelor's degree",
    "household_income": 50000, "occupation": "teacher", "ethnicity": "white",
    "marital_status": "married", "household_size": 3, "number_of_children": 1,
    "state": "CA", "home_ownership": "own",
}


def check_prompt_pair(system: str, user: str, arm_qids: tuple[str, ...],
                      stimuli: dict[str, dict]) -> None:
    """One rendered prompt pair's exactness checks (raises SystemExit)."""
    if not system or not user:
        raise SystemExit(f"error: empty prompt for {arm_qids}")
    for qid in arm_qids:
        if stimuli[qid]["question_text"] not in user:
            raise SystemExit(
                f"error: exact stimulus wording missing for {qid}"
            )
        for letter, text in _label_map(stimuli[qid]).items():
            if f"{letter}. {text}" not in user:
                raise SystemExit(
                    f"error: option line missing for {letter} in {qid}"
                )


def _label_map(stimulus: dict) -> dict[str, str]:
    """Letter -> option text for a choice question (empty for digit items)."""
    options = stimulus.get("options")
    labels = stimulus.get("labels")
    if not options or not labels:
        return {}
    return dict(zip(labels, options))


def log_smoke_coverage() -> None:
    """The offline smoke-filter report: grid shape + item kinds covered.

    Pure enumeration over the shipped stimuli — proves without a server
    that the smoke grid is 1 model x 1 persona x 19 arms x 2 blindings
    and that choice and digit questions all appear in it.
    """
    grid = cells.smoke_cells()
    stimuli = experiments.load_stimuli()
    kinds: set[str] = set()
    for _model, _persona, experiment, arm, _blind in grid:
        for item in experiments.arm_items(experiment, arm, stimuli):
            kinds.add(item["kind"])
    arms = {(cell[2], cell[3]) for cell in grid}
    blindings = sorted({cell[4] for cell in grid})
    models = sorted({cell[0] for cell in grid})
    personas = sorted({cell[1] for cell in grid})
    _log(f"dry run (smoke): {len(grid)} cells = {len(models)} model "
         f"({config.SMOKE_MODEL}) x {len(personas)} persona x "
         f"{len(arms)} arms x {len(blindings)} blindings {blindings}")
    _log(f"dry run (smoke): item kinds covered: {sorted(kinds)}")


def log_grid_counts(models: list[str]) -> None:
    """The production grid's offline counts (all models, 100 personas)."""
    total = len(cells.enumerate_cells())
    _log(f"dry run: {len(models)} models x "
         f"{cells.EXPECTED_RECORDS_PER_MODEL} = {total} cells total")
    for model in models:
        count = len(cells.enumerate_cells(models=[model]))
        _log(f"dry run: model {model}: {count} cells")


def log_preflight_counts(models: list[str], persona_id: int) -> None:
    """The preflight-only counts: one persona on every arm, no grid."""
    per_model = len(cells.enumerate_cells(models=[models[0]],
                                          personas=[persona_id]))
    _log(f"dry run (preflight-only): {len(models)} models x {per_model} "
         f"persona-{persona_id} cells = {len(models) * per_model} "
         f"preflight cells — the grid will not run")


def _item_prompt_pairs(stimuli: dict[str, dict]) -> int:
    """Render and check every item's prompt pair; return how many.

    For every experiment arm and both blinding prompts, each first-token
    item is rendered on its own user prompt and checked for its verbatim
    question text (and its lettered option lines when it is a choice).
    """
    checked = 0
    for experiment, spec in experiments.EXPERIMENTS.items():
        for arm, _arm_qids in spec.arms:
            items = experiments.arm_items(experiment, arm, stimuli)
            for blinded in (True, False):
                system = prompts.build_system_prompt(experiment, blinded)
                for item in items:
                    user = prompts.build_user_prompt(
                        PLACEHOLDER_PERSONA, experiment, arm, item=item)
                    check_prompt_pair(system, user, (item["qid"],), stimuli)
                    checked += 1
    return checked


def dry_run(models: list[str], smoke: bool = False,
            preflight_only: bool = False, preflight_persona: int = 0) -> int:
    """The offline rehearsal: cell counts + prompt exactness, no server.

    Prints the requested mode's cell counts, checks every item prompt
    pair, and returns 0 — the runner's --dry-run exit code. smoke=True
    reports the smoke filter's grid, preflight_only=True the persona-0
    preflight counts (never the 57,000-cell grid).
    """
    stimuli = experiments.load_stimuli()
    if smoke:
        log_smoke_coverage()
    elif preflight_only:
        log_preflight_counts(models, preflight_persona)
    else:
        log_grid_counts(models)
    checked = _item_prompt_pairs(stimuli)
    _log(f"dry run: {checked} item prompt pairs checked — exact stimuli "
         f"and option lines present in all")
    return 0


def _log(message: str) -> None:
    """One timestamped progress line on stdout (the rehearsal's output)."""
    stamp = datetime.now(timezone.utc).isoformat()
    print(f"[{stamp}] {message}", flush=True)
