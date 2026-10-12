# This file draws the twin2k6 study's EXACTLY three figures from the tidy
# CSVs that twin2k6.analyze writes. Fig 1 shows every experiment's arm
# means (human benchmark as a bold reference line, each model as a thin
# line) side by side for blinded vs unblinded; the PDF has one overview
# page plus one page per model because 15 models on one panel is dense.
# Fig 2 is the unblinding-gain heatmap (blinded error minus unblinded
# error; positive = seeing the randomization note helped). Fig 3 pairs
# each model's overall blinded/unblinded error as horizontal dots with its
# delta. Each figure is written as PDF and PNG with the tidy CSV that
# backs it saved alongside. --selftest renders all three from synthetic
# fixture data (via the real analyze module) into a temp dir — no study
# data or model server needed.

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import tempfile
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS = _SCRIPT_DIR.parent
_REPO_ROOT = _SCRIPTS.parent
for _dir in (str(_SCRIPTS), str(_REPO_ROOT / "src")):
    if _dir not in sys.path:
        sys.path.insert(0, _dir)

import matplotlib  # noqa: E402

matplotlib.use("Agg")  # never opens a window; safe on a headless run
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

from twin2k6 import analyze, config, experiments  # noqa: E402

# Short arm labels for the fig-1 x axes, in each experiment's pinned arm
# order (the task's examples: gain/loss; A/B/C; all/98/95; no_card/card;
# WTP-c/WTA/WTP-n).
SHORT_ARM_LABELS: dict[str, dict[str, str]] = {
    "disease": {"gain": "gain", "loss": "loss"},
    "less_is_more": {"A": "A", "B": "B", "C": "C"},
    "fire_extinguisher": {"all": "all", "98pct": "98", "95pct": "95"},
    "seatbelt": {"all": "all", "98pct": "98", "95pct": "95"},
    "sunk_cost": {"no_card": "no_card", "card": "card"},
    "wta_wtp": {
        "wtp_certainty": "WTP-c", "wta_certainty": "WTA",
        "wtp_noncertainty": "WTP-n",
    },
}

# Each experiment's scored-outcome axis: label and the scale's own range
# (disease's statistic is the safe-side probability, a 0-1 scale).
Y_LABELS: dict[str, str] = {
    "disease": "P(safe) (Program A)",
    "less_is_more": "Expected (1–5)",
    "fire_extinguisher": "Expected (1–5)",
    "seatbelt": "Expected (1–6)",
    "sunk_cost": "Expected (0–20)",
    "wta_wtp": "Expected bracket (1–10)",
}
Y_LIMS: dict[str, tuple[float, float]] = {
    "disease": (0.0, 1.0),
    "less_is_more": (1.0, 5.0),
    "fire_extinguisher": (1.0, 5.0),
    "seatbelt": (1.0, 6.0),
    "sunk_cost": (0.0, 20.0),
    "wta_wtp": (1.0, 10.0),
}

FIG1_STEM = "fig1_treatment_profiles"
FIG2_STEM = "fig2_unblinding_gain_heatmap"
FIG3_STEM = "fig3_overall_error"


def load_arm_means(path: Path) -> dict[tuple, float]:
    """Read analyze's arm_means.csv into {(model, exp, blind, arm): mean}."""
    means: dict[tuple, float] = {}
    with open(path, encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            means[(row["model"], row["experiment"], row["blinding"],
                   row["arm"])] = float(row["mean"])
    return means


def load_errors(path: Path) -> dict[tuple, float]:
    """Read analyze's errors.csv into {(model, exp, blind, contrast): err}."""
    errors: dict[tuple, float] = {}
    with open(path, encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            errors[(row["model"], row["experiment"], row["blinding"],
                    row["contrast"])] = float(row["normalized_error"])
    return errors


def load_human(path: Path) -> dict[tuple, float]:
    """The wave1_3 human arm numbers: disease p_safe, other arms' means."""
    benchmarks = json.loads(Path(path).read_text(encoding="utf-8"))
    wave = benchmarks["waves"]["wave1_3"]
    human: dict[tuple, float] = {}
    for experiment, entry in wave.items():
        for arm, arm_entry in entry["arms"].items():
            key = "p_safe" if experiment == "disease" else "mean"
            if arm_entry.get(key) is not None:
                human[(experiment, arm)] = float(arm_entry[key])
    return human


def ordered_models(models_in_data: set[str]) -> list[str]:
    """The study's pinned model order first, then any extras alphabetically."""
    pinned = [model for model in config.MODELS if model in models_in_data]
    extras = sorted(models_in_data - set(config.MODELS))
    return pinned + extras


def _fig1_panel(ax, experiment: str, blinding: str, arm_means: dict[tuple, float],
                human: dict[tuple, float], models: list[str]) -> None:
    """One fig-1 facet: human bold + the given models as thin arm-mean lines."""
    spec = experiments.EXPERIMENTS[experiment]
    arms = [arm for arm, _qid in spec.arms]
    xs = list(range(len(arms)))
    human_values = [human.get((experiment, arm)) for arm in arms]
    ax.plot(xs, human_values, color="black", linewidth=2.4, marker="o",
            label="Human (wave1_3)", zorder=3)
    for model in models:
        values = [arm_means.get((model, experiment, blinding, arm)) for arm in arms]
        if any(value is None for value in values):
            continue
        ax.plot(xs, values, color="tab:blue", alpha=0.35, linewidth=0.9, zorder=2)
    ax.set_xticks(xs, [SHORT_ARM_LABELS[experiment][arm] for arm in arms])
    ax.set_ylim(*Y_LIMS[experiment])
    ax.set_ylabel(Y_LABELS[experiment])
    ax.set_title(f"{experiment} — {blinding}", fontsize=10)


def _draw_fig1_page(models: list[str], arm_means: dict[tuple, float],
                    human: dict[tuple, float]):
    """One fig-1 page: 6 experiment rows × 2 blinding columns of facets."""
    figure, axes = plt.subplots(
        len(experiments.EXPERIMENTS), len(config.BLINDINGS),
        figsize=(9, 15), squeeze=False,
    )
    for row, experiment in enumerate(experiments.EXPERIMENTS):
        for column, blinding in enumerate(config.BLINDINGS):
            _fig1_panel(axes[row][column], experiment, blinding,
                        arm_means, human, models)
    legend_handles = [
        plt.Line2D([], [], color="black", linewidth=2.4, marker="o",
                   label="Human (wave1_3)"),
        plt.Line2D([], [], color="tab:blue", alpha=0.5, linewidth=1.0,
                   label="models" if len(models) > 1 else models[0]),
    ]
    figure.legend(handles=legend_handles, loc="lower center", ncols=2)
    figure.suptitle(
        "Arm means by experiment — "
        + ("all models (overview)" if len(models) > 1 else models[0]),
        fontsize=12,
    )
    figure.tight_layout(rect=(0, 0.03, 1, 0.98))
    return figure


def _write_fig1(arm_means: dict[tuple, float], human: dict[tuple, float],
                models: list[str], out_dir: Path) -> list[Path]:
    """Fig 1: multipage PDF (overview + one page per model), PNG, tidy CSV."""
    written: list[Path] = []
    with PdfPages(out_dir / f"{FIG1_STEM}.pdf") as pdf:
        pages = [models] + [[model] for model in models]
        for page_models in pages:
            figure = _draw_fig1_page(page_models, arm_means, human)
            pdf.savefig(figure)
            plt.close(figure)
    written.append(out_dir / f"{FIG1_STEM}.pdf")
    figure = _draw_fig1_page(models, arm_means, human)  # PNG = overview page
    figure.savefig(out_dir / f"{FIG1_STEM}.png", dpi=150)
    plt.close(figure)
    written.append(out_dir / f"{FIG1_STEM}.png")
    rows = [["source", "experiment", "blinding", "arm", "arm_label", "value"]]
    for (model, experiment, blinding, arm), value in sorted(arm_means.items()):
        rows.append([model, experiment, blinding, arm,
                     SHORT_ARM_LABELS[experiment][arm], value])
    for (experiment, arm), value in sorted(human.items()):
        rows.append(["Human", experiment, "", arm,
                     SHORT_ARM_LABELS[experiment][arm], value])
    _write_csv(out_dir / "fig1_tidy.csv", rows)
    written.append(out_dir / "fig1_tidy.csv")
    return written


def compute_fig2_gains(errors: dict[tuple, float]) -> dict[tuple, float]:
    """Unblinding gain per (model, experiment): mean blinded normalized
    error minus mean unblinded normalized error (positive = helps)."""
    per_cell: dict[tuple, dict[str, list[float]]] = {}
    for (model, experiment, blinding, _contrast), value in errors.items():
        per_cell.setdefault((model, experiment), {}).setdefault(
            blinding, []).append(value)
    gains: dict[tuple, float] = {}
    for (model, experiment), by_blinding in per_cell.items():
        blinded = by_blinding.get("blinded")
        unblinded = by_blinding.get("unblinded")
        if blinded and unblinded:
            gains[(model, experiment)] = (
                sum(blinded) / len(blinded) - sum(unblinded) / len(unblinded)
            )
    return gains


def _write_fig2(gains: dict[tuple, float], models: list[str],
                out_dir: Path) -> list[Path]:
    """Fig 2: models × experiments heatmap of the unblinding gain."""
    experiment_names = list(experiments.EXPERIMENTS)
    grid = [
        [gains.get((model, experiment)) for experiment in experiment_names]
        for model in models
    ]
    present = [value for row in grid for value in row if value is not None]
    limit = max((abs(value) for value in present), default=1.0) or 1.0
    figure, ax = plt.subplots(figsize=(8, 7))
    image = ax.imshow(grid, cmap="RdBu_r", vmin=-limit, vmax=limit)
    for row, model in enumerate(models):
        for column, experiment in enumerate(experiment_names):
            value = gains.get((model, experiment))
            if value is not None:
                ax.text(column, row, f"{value:+.2f}", ha="center",
                        va="center", fontsize=7,
                        color="white" if abs(value) > 0.6 * limit else "black")
    ax.set_xticks(range(len(experiment_names)), experiment_names,
                  rotation=30, ha="right")
    ax.set_yticks(range(len(models)), models, fontsize=8)
    ax.set_title("Unblinding gain (normalized error, blinded − unblinded)")
    bar = figure.colorbar(image, ax=ax)
    bar.set_label("positive = unblinding helps (less error)")
    figure.tight_layout()
    for suffix in (".pdf", ".png"):
        figure.savefig(out_dir / f"{FIG2_STEM}{suffix}")
    written = [out_dir / f"{FIG2_STEM}.pdf", out_dir / f"{FIG2_STEM}.png"]
    plt.close(figure)
    rows = [["model", "experiment", "gain"]]
    rows += [[model, experiment, gains[(model, experiment)]]
             for (model, experiment) in sorted(gains)]
    _write_csv(out_dir / "fig2_tidy.csv", rows)
    written.append(out_dir / "fig2_tidy.csv")
    return written


def compute_fig3_means(errors: dict[tuple, float]) -> dict[str, dict[str, float]]:
    """Per model: mean normalized error over all tasks, blinded vs unblinded."""
    per_model: dict[str, dict[str, list[float]]] = {}
    for (model, _experiment, blinding, _contrast), value in errors.items():
        per_model.setdefault(model, {}).setdefault(blinding, []).append(value)
    means: dict[str, dict[str, float]] = {}
    for model, by_blinding in per_model.items():
        blinded = by_blinding.get("blinded")
        unblinded = by_blinding.get("unblinded")
        if blinded and unblinded:
            blinded_mean = sum(blinded) / len(blinded)
            unblinded_mean = sum(unblinded) / len(unblinded)
            means[model] = {
                "blinded": blinded_mean,
                "unblinded": unblinded_mean,
                "delta": blinded_mean - unblinded_mean,
            }
    return means


def _write_fig3(means: dict[str, dict[str, float]], models: list[str],
                out_dir: Path) -> list[Path]:
    """Fig 3: paired horizontal dots (blinded vs unblinded) + delta labels."""
    ordered = [model for model in models if model in means]
    figure, ax = plt.subplots(figsize=(8, 7))
    span = max(
        (value for entry in means.values()
         for value in (entry["blinded"], entry["unblinded"])),
        default=1.0,
    )
    for row, model in enumerate(ordered):
        blinded = means[model]["blinded"]
        unblinded = means[model]["unblinded"]
        ax.plot([blinded, unblinded], [row, row], color="lightgray",
                linewidth=1.5, zorder=1)
        ax.scatter([blinded], [row], color="tab:red", zorder=2, s=28,
                   label="blinded" if row == 0 else None)
        ax.scatter([unblinded], [row], color="tab:blue", zorder=2, s=28,
                   label="unblinded" if row == 0 else None)
        ax.text(span * 1.05, row, f"{means[model]['delta']:+.3f}",
                va="center", fontsize=7)
    ax.set_yticks(range(len(ordered)), ordered, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("mean normalized error across the 6 tasks")
    ax.set_xlim(0, span * 1.22)
    ax.set_title("Overall error per model: blinded vs unblinded")
    ax.legend(loc="lower right")
    figure.tight_layout()
    for suffix in (".pdf", ".png"):
        figure.savefig(out_dir / f"{FIG3_STEM}{suffix}")
    written = [out_dir / f"{FIG3_STEM}.pdf", out_dir / f"{FIG3_STEM}.png"]
    plt.close(figure)
    rows = [["model", "blinded", "unblinded", "delta"]]
    rows += [[model, entry["blinded"], entry["unblinded"], entry["delta"]]
             for model, entry in sorted(means.items())]
    _write_csv(out_dir / "fig3_tidy.csv", rows)
    written.append(out_dir / "fig3_tidy.csv")
    return written


def _write_csv(path: Path, rows: list[list]) -> None:
    """One tidy CSV from full rows including the header row."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)


def render_all(arm_means: dict[tuple, float], errors: dict[tuple, float],
               human: dict[tuple, float], out_dir: Path) -> list[Path]:
    """The study's three figures (+ tidy CSVs) into out_dir; nothing else."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    models = ordered_models({key[0] for key in arm_means} | {key[0] for key in errors})
    written = _write_fig1(arm_means, human, models, out_dir)
    written += _write_fig2(compute_fig2_gains(errors), models, out_dir)
    written += _write_fig3(compute_fig3_means(errors), models, out_dir)
    return written


def render_from_analysis(analysis_dir: Path, benchmarks_path: Path,
                         out_dir: Path) -> list[Path]:
    """Load analyze's tidy CSVs + the benchmarks, then render everything."""
    return render_all(
        load_arm_means(Path(analysis_dir) / "arm_means.csv"),
        load_errors(Path(analysis_dir) / "errors.csv"),
        load_human(Path(benchmarks_path)),
        Path(out_dir),
    )


def _synthetic_record(rng: random.Random, model: str, experiment: str,
                      spec, arm: str, blind: str) -> dict:
    """One synthetic analyzed-looking record (selftest fixture, no meaning)."""
    shift = 0.4 if blind == "unblinded" else 0.0
    raw = {
        letter: rng.expovariate(1.0) * (1.0 + shift + rng.uniform(-0.2, 0.2))
        for letter in spec.label_letters
    }
    total = sum(raw.values())
    mass = rng.uniform(0.75, 1.0)
    p_norm = {letter: value / total * mass for letter, value in raw.items()}
    record = {
        "model": model,
        "experiment": experiment,
        "blind": blind,
        "arm": arm,
        "branch_mass": mass,
        "low_branch_mass": mass < config.LOW_BRANCH_MASS_THRESHOLD,
    }
    if experiment == "disease":
        record["p_safe_norm"] = sum(
            p_norm[letter] for letter in ("A", "B", "C")
        )
    else:
        record[spec.outcome_field] = sum(
            spec.label_values[letter] * p_norm[letter]
            for letter in spec.label_letters
        )
    return record


def synthetic_fixtures(seed: int = 0) -> tuple[list[dict], dict]:
    """The selftest's fixture data: fake records + a fake human benchmark.

    15 fake models answer every arm of every experiment in both blinding
    arms for 4 synthetic personas; the fake benchmarks carry the same arm
    and contrast names analyze expects, so the whole real rendering path
    runs with zero study data.
    """
    rng = random.Random(seed)
    models = [f"model-{index:02d}" for index in range(15)]
    records = [
        _synthetic_record(rng, model, experiment, spec, arm, blind)
        for model in models
        for experiment, spec in experiments.EXPERIMENTS.items()
        for arm, _qid in spec.arms
        for blind in config.BLINDINGS
        for _persona in range(4)
    ]
    wave = {}
    for experiment, spec in experiments.EXPERIMENTS.items():
        key = "p_safe" if experiment == "disease" else "mean"
        wave[experiment] = {
            "arms": {
                arm: {key: round(rng.uniform(0, 1 if experiment == "disease"
                else spec.label_count), 4)}
                for arm, _qid in spec.arms
            },
            "contrasts": {
                name: {"value": round(rng.uniform(-1, 1), 4)}
                for name in analyze.CONTRASTS[experiment]
            },
        }
    benchmarks = {"waves": {"wave1_3": wave}}
    return records, benchmarks


def _write_analysis_csvs(records: list[dict], benchmarks: dict,
                         analysis_dir: Path) -> None:
    """Write the two tidy CSVs the figures read, via analyze's own loaders.

    Deliberately NOT analyze.write_analysis_outputs: that locked writer
    currently crashes on its own gain-rows unpacking (found by this
    selftest, reported to the orchestrator); the figures only need
    arm_means.csv and errors.csv, written here with analyze's exact
    columns from analyze's pure mean/error functions.
    """
    analysis_dir = Path(analysis_dir)
    analysis_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(
        analysis_dir / "arm_means.csv",
        [["model", "experiment", "blinding", "arm", "mean"]]
        + [[model, experiment, blinding, arm, mean]
           for (model, experiment, blinding, arm), mean in sorted(
               analyze.arm_means(records).items())],
    )
    _write_csv(
        analysis_dir / "errors.csv",
        [["model", "experiment", "blinding", "contrast", "normalized_error"]]
        + [[model, experiment, blinding, name, value]
           for (model, experiment, blinding), by_name in sorted(
               analyze.normalized_contrast_errors(records, benchmarks).items())
           for name, value in by_name.items()],
    )


def selftest(out_dir: Path | None = None) -> list[Path]:
    """Render all three figures from synthetic fixtures into a temp dir.

    Builds fake records and a fake human benchmark, writes the analyze-
    shaped tidy CSVs from them, then renders into out_dir (or a fresh
    temp dir when none was given). Returns the written paths.
    """
    records, benchmarks = synthetic_fixtures()
    with tempfile.TemporaryDirectory(prefix="twin2k6-figs-") as scratch:
        analysis_dir = Path(scratch) / "analysis"
        _write_analysis_csvs(records, benchmarks, analysis_dir)
        benchmark_file = _fake_benchmarks_file(scratch, benchmarks)
        target = Path(out_dir) if out_dir is not None else Path(scratch) / "figs"
        written = render_from_analysis(analysis_dir, benchmark_file, target)
        for path in written:
            label = path if out_dir is not None else path.name
            print(f"{label} ({path.stat().st_size:,} bytes)")
        return written


def _fake_benchmarks_file(scratch: str, benchmarks: dict) -> Path:
    """The fixture benchmarks written to a file (load_human reads a path)."""
    path = Path(scratch) / "benchmarks_fixture.json"
    path.write_text(json.dumps(benchmarks), encoding="utf-8")
    return path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """The figures CLI: real renders from an analysis dir, or --selftest."""
    parser = argparse.ArgumentParser(
        prog="python -m scripts.twin2k6.figures",
        description="Render the study's three figures from analyze's CSVs.",
    )
    parser.add_argument(
        "--selftest", action="store_true",
        help="render all three figures from synthetic fixture data",
    )
    parser.add_argument(
        "--analysis-dir", type=Path, default=None,
        help="folder holding analyze's arm_means.csv and errors.csv",
    )
    parser.add_argument("--out", type=Path, default=None,
                        help="output folder (default: ./figures)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """The CLI entry point (module execution starts here)."""
    args = parse_args(argv)
    if args.selftest:
        selftest(args.out)
        return 0
    if args.analysis_dir is None:
        raise SystemExit("error: give --analysis-dir (or use --selftest)")
    render_from_analysis(args.analysis_dir, config.BENCHMARKS_PATH,
                         args.out or Path("figures"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
