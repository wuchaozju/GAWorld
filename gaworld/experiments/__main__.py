"""CLI: ``python -m gaworld.experiments``.

Examples::

    # cost preview — expands the grid, calls nothing
    python -m gaworld.experiments --product-limit 5 --dry-run

    # smoke run: 5 products, 3 residents, both questions, all five arms
    python -m gaworld.experiments --name smoke --product-limit 5 \
        --subject-limit 3 --arms blind covariate unblinded agent agent_unblinded

    # the paper's protocol on the full catalog (expensive — see --dry-run first)
    python -m gaworld.experiments --name full --draws 50 --temperature 1.0

    # re-analyse an existing run without spending a token
    python -m gaworld.experiments --analyze-only --name full
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from gaworld.experiments.analysis import load_results, render_markdown, summarize
from gaworld.experiments.arms import ELICIT_FIELDS
from gaworld.experiments.runner import DEFAULT_OUTPUT_DIR, RunSpec, run
from gaworld.experiments.stimulus import DEFAULT_CATALOG, RELATIVE_PRICE_GRID


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m gaworld.experiments",
        description="需求估计提示词实验（Gui & Toubia 2025 的中文化 + 智能体化复现）。",
    )
    parser.add_argument("--name", default="demand", help="运行名，决定输出子目录")
    parser.add_argument(
        "--arms",
        nargs="+",
        default=["blind", "unblinded", "agent"],
        help="参与对比的 arm：blind covariate unblinded agent agent_unblinded",
    )
    parser.add_argument(
        "--questions", nargs="+", default=["elicit", "purchase"], help="elicit / purchase"
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG, help="商品目录 CSV")
    parser.add_argument("--groups", nargs="+", default=None, help="只跑这些品类组")
    parser.add_argument("--product-limit", type=int, default=None, help="只取前 N 个商品")
    parser.add_argument("--subject-limit", type=int, default=20, help="被试居民数量")
    parser.add_argument("--subject-ids", nargs="+", type=int, default=None, help="指定居民 id")
    parser.add_argument("--draws", type=int, default=1, help="无被试 arm 每格的采样次数（论文用 50）")
    parser.add_argument(
        "--subject-draws",
        type=int,
        default=1,
        help="有被试的 arm 每格的采样次数；异质性来自被试本身，默认 1",
    )
    parser.add_argument("--temperature", type=float, default=1.0, help="采样温度（论文用 1）")
    parser.add_argument("--provider", default=None, help="覆盖 LLM provider 名")
    parser.add_argument("--seed", type=int, default=42, help="世界状态与收入抽样的种子")
    parser.add_argument(
        "--elicit-fields",
        nargs="+",
        default=list(ELICIT_FIELDS),
        help="要问的未指定变量；只给一个即为论文 Prompt 1 的原始形态",
    )
    parser.add_argument("--max-workers", type=int, default=8, help="并发调用数")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="输出根目录")
    parser.add_argument("--dry-run", action="store_true", help="只展开网格并报数，不调用模型")
    parser.add_argument("--no-resume", action="store_true", help="忽略已有结果，全部重跑")
    parser.add_argument("--analyze-only", action="store_true", help="只对已有结果重新分析")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    out_dir = Path(args.output_dir) / args.name
    results_path = out_dir / "results.jsonl"

    if not args.analyze_only:
        spec = RunSpec(
            arms=list(args.arms),
            questions=list(args.questions),
            catalog=args.catalog,
            groups=args.groups,
            product_limit=args.product_limit,
            grid=RELATIVE_PRICE_GRID,
            subject_limit=args.subject_limit,
            subject_ids=args.subject_ids,
            draws=args.draws,
            subject_draws=args.subject_draws,
            temperature=args.temperature,
            provider=args.provider,
            seed=args.seed,
            elicit_fields=tuple(args.elicit_fields),
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

    summary = summarize(load_results(results_path), elicit_fields=tuple(args.elicit_fields))
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = render_markdown(summary)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"→ {out_dir/'summary.json'}\n→ {out_dir/'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
