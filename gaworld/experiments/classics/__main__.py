"""CLI: ``python -m gaworld.experiments.classics``.

Examples::

    python -m gaworld.experiments.classics list
    # cost preview — expands the grid, calls nothing
    python -m gaworld.experiments.classics run --dry-run
    # two paradigms, 20 residents
    python -m gaworld.experiments.classics run framing anchoring --subject-limit 20
    # re-analyse without spending a token
    python -m gaworld.experiments.classics analyze
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from gaworld.experiments.classics.analysis import load_rows, render_markdown, summarize
from gaworld.experiments.classics.paradigms import PARADIGMS
from gaworld.experiments.classics.runner import DEFAULT_OUTPUT_DIR, ClassicSpec, run


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m gaworld.experiments.classics",
        description="经典实验库：居民当被试，复现六个教科书范式的方向。",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="列出范式")
    for name, help_text in (("run", "跑实验（续跑已有结果），然后分析"), ("analyze", "只分析已有结果")):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--name", default="default", help="运行名，决定输出子目录")
        cmd.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="输出根目录")
        if name == "run":
            cmd.add_argument("paradigms", nargs="*", help=f"范式（默认全部）：{' '.join(PARADIGMS)}")
            cmd.add_argument("--subject-limit", type=int, default=40, help="被试居民数（按 id 顺序取）")
            cmd.add_argument("--subject-ids", nargs="+", type=int, default=None, help="指定居民 id")
            cmd.add_argument("--draws", type=int, default=1, help="每人每条件的调用次数")
            cmd.add_argument("--temperature", type=float, default=1.0)
            cmd.add_argument("--provider", default=None, help="覆盖 LLM provider 名")
            cmd.add_argument("--seed", type=int, default=42, help="居民收入抽样的种子")
            cmd.add_argument("--max-workers", type=int, default=8)
            cmd.add_argument("--dry-run", action="store_true", help="只报调用数，不调用模型")
            cmd.add_argument("--no-resume", action="store_true", help="忽略已有结果，全部重跑")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "list":
        for paradigm in PARADIGMS.values():
            control, treatment = (paradigm.condition_labels[c] for c in paradigm.conditions)
            print(
                f"{paradigm.id:<22} {paradigm.name} —— {paradigm.measure}：{treatment} > {control}（{paradigm.reference}）"
            )
        return 0

    out_dir = Path(args.output_dir) / args.name
    results_path = out_dir / "results.jsonl"
    if args.command == "run":
        spec = ClassicSpec(
            paradigms=list(args.paradigms or PARADIGMS),
            subject_limit=args.subject_limit,
            subject_ids=args.subject_ids,
            draws=args.draws,
            temperature=args.temperature,
            provider=args.provider,
            seed=args.seed,
            max_workers=args.max_workers,
            name=args.name,
            output_dir=args.output_dir,
        )
        results_path = run(spec, dry_run=args.dry_run, resume=not args.no_resume)
        if args.dry_run:
            return 0

    if not results_path.exists():
        print(f"⚠️ 没有找到结果文件：{results_path}")
        return 1
    summary = summarize(load_rows(results_path))
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report = render_markdown(summary, args.name)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"→ {out_dir / 'summary.json'}\n→ {out_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
