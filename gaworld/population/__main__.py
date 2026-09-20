"""CLI: ``python -m gaworld.population``.

Examples::

    # 500-person town with the default preset
    python -m gaworld.population --size 500 --out data/town

    # aging community, reproducible, dry run (no files written)
    python -m gaworld.population --preset aging_community --seed 7 --check

    # drive every knob from a JSON spec
    python -m gaworld.population --spec my_town.json --out data/town
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from gaworld.population.generate import generate_population
from gaworld.population.report import worst_gaps
from gaworld.population.schema import PRESETS, normalize_spec


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m gaworld.population",
        description="Generate a synthetic population as a state CSV + profile Markdown.",
    )
    parser.add_argument("--spec", type=Path, help="JSON file with the full population spec")
    parser.add_argument("--preset", choices=sorted(PRESETS), help="Preset to start from")
    parser.add_argument("--size", type=int, help="Number of residents")
    parser.add_argument("--seed", type=int, help="Master random seed")
    parser.add_argument("--name", help="Population name; used for the output filenames")
    parser.add_argument("--out", type=Path, help="Output directory")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Generate and report, but write nothing (use to preview a spec)",
    )
    parser.add_argument("--json", action="store_true", help="Emit the full report as JSON")
    return parser


def _load_overrides(args: argparse.Namespace) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    if args.spec:
        raw = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    for key in ("preset", "size", "seed", "name"):
        value = getattr(args, key)
        if value is not None:
            raw[key] = value
    return raw


def _print_summary(result: Any) -> None:
    report = result.report
    spec = result.spec
    print(f"生成完成：{report['size']} 人 | preset={spec.preset} seed={spec.seed}")

    fit = report["fit"]["ipf"]
    status = "收敛" if fit["converged"] else "未收敛"
    print(f"  IPF：{fit['iterations']} 轮，{status}，最大边缘偏差 {fit['max_marginal_deviation']:.4f}")

    achieved = report["achieved"]
    print("  关键指标（目标 → 实际）：")
    for knob in (
        "median_age",
        "employment_rate",
        "tertiary_rate",
        "income_median",
        "income_gini",
        "household_mean_size",
        "mean_degree",
    ):
        entry = achieved[knob]
        print(f"    {knob:22s} {entry['target']:>10.3f} → {entry['achieved']:>10.3f}")

    network = report["network"]
    print(
        f"  社交网络：{network['edges']} 条边，平均度 {network['mean_degree']:.1f}，"
        f"聚类 {network['clustering']:.3f}（随机图 {network['random_clustering']:.3f}），"
        f"平均路径 {network['mean_path_length']:.2f}，small-world σ={network['small_world_sigma']:.1f}"
    )

    gaps = worst_gaps(report)
    if gaps and gaps[0]["relative_error"] > 0.05:
        print("  被松弛的旋钮（相对误差最大的几个）：")
        for gap in gaps:
            if gap["relative_error"] > 0.05:
                print(
                    f"    {gap['knob']:22s} 要求 {gap['target']} → 实际 {gap['achieved']} "
                    f"（偏差 {gap['relative_error']:.1%}）"
                )

    for issue in result.feasibility:
        print(f"  [{issue.level}] {issue.knob}: {issue.message}")
        if issue.suggestion:
            print(f"           建议：{issue.suggestion}")
    for finding in result.findings:
        print(f"  [{finding.level}] {finding.code}: {finding.message}（{finding.count} 例）")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    spec = normalize_spec(_load_overrides(args))
    result = generate_population(spec)

    if args.json:
        print(
            json.dumps(
                {
                    "spec": spec.to_dict(),
                    "report": result.report,
                    "feasibility": [i.to_dict() for i in result.feasibility],
                    "findings": [f.to_dict() for f in result.findings],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        _print_summary(result)

    if not result.ok:
        print("校验未通过，未写出文件。", file=sys.stderr)
        return 1

    if args.check:
        if not args.json:
            print("（--check：未写出文件）")
        return 0

    output_dir = args.out or Path("output/population")
    written = result.write(output_dir)
    if not args.json:
        print("已写出：")
        for label, path in written.items():
            print(f"  {label:12s} {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
