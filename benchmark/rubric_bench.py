#!/usr/bin/env python3
"""GAWorld-Rubric-Bench (Track R) CLI.

See benchmark/GAWORLD_RUBRIC_BENCH.md for the method.

    cd benchmark

    # offline: synthetic fixtures + stub judge, exercises the whole pipeline
    python rubric_bench.py --synthetic --ablate all

    # rule-only scoring of a real run (zero LLM calls)
    python rubric_bench.py --output-dir ../output

    # full scoring with a judge ensemble
    python rubric_bench.py --output-dir ../output --judges minimax,ollama_gemma4

    # discrimination check (this is what lifts Track R out of UNVERIFIED)
    python rubric_bench.py --output-dir ../output --judges minimax --ablate N1,N3,N7
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rubric import loader, runner, synth  # noqa: E402
from rubric.aggregate import render_markdown  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="GAWorld-Rubric-Bench (Track R)")
    p.add_argument("--output-dir", default="../output", help="GAWorld output/ 目录")
    p.add_argument("--synthetic", action="store_true",
                   help="用合成数据 + stub judge 跑通管线，不调 LLM")
    p.add_argument("--synthetic-mode", choices=("full", "fast_forward"), default="full",
                   help="合成数据模拟哪种 run：full=全保真（有 episodes），"
                        "fast_forward=快进（无 episodes，只有状态历史/成长/模板日记）")
    p.add_argument("--judges", default="",
                   help="逗号分隔的 provider 名；留空则只跑 rule 类 item")
    p.add_argument("--samples-per-judge", type=int, default=3)
    p.add_argument("--sample-seed", type=int, default=42)
    p.add_argument("--min-days", type=int, default=30,
                   help="演化维度所需的最短轨迹天数；不足则 R2 弃权")
    p.add_argument("--ablate", default="",
                   help="消融算子，逗号分隔（N1..N8）或 all")
    p.add_argument("--dim", default="", help="只跑某个维度（R1/R2/R3/R4）")
    p.add_argument("--results-dir", default=str(RESULTS_DIR))
    args = p.parse_args(argv)

    if args.synthetic:
        data = (synth.build_fast_forward() if args.synthetic_mode == "fast_forward"
                else synth.build())
        judge_call = runner.stub_judge
        providers = ["stub-a", "stub-b", "stub-c"]
    else:
        data = loader.load_all(Path(args.output_dir))
        judge_call = None
        providers = [s.strip() for s in args.judges.split(",") if s.strip()]

    caps = data.get("capabilities") or {}
    if not any(caps.get(k) for k in ("episodes", "series", "growth")):
        print(f"[错误] {args.output_dir} 下既无 episodes 也无状态历史/成长快照，无可评测数据。")
        return 2
    if not caps.get("episodes"):
        print(f"[提示] 未发现 episodes（run 模式：{data.get('run_mode')}）。"
              "日内粒度的 R1/R3/R4 将全部弃权，只有 R2 可评——这需要一份全保真 run 来补。")

    rubric = runner.load_rubric()
    if args.ablate.strip().lower() == "all":
        ablations = list(rubric["ablations"])
    else:
        ablations = [s.strip().upper() for s in args.ablate.split(",") if s.strip()]

    scorecard = runner.run(
        data, providers=providers, sample_seed=args.sample_seed,
        min_days=args.min_days, samples_per_judge=args.samples_per_judge,
        ablations=ablations, judge_call=judge_call)
    scorecard["mode"] = "synthetic" if args.synthetic else "real"

    if args.dim:
        keep = args.dim.strip().upper()
        scorecard["dimensions"] = {k: v for k, v in scorecard["dimensions"].items() if k == keep}
        scorecard["items"] = {k: v for k, v in scorecard["items"].items() if v["dim"] == keep}

    out_dir = Path(args.results_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "rubric_scorecard.json").write_text(
        json.dumps(scorecard, ensure_ascii=False, indent=2), encoding="utf-8")
    md = render_markdown(scorecard)
    (out_dir / "rubric_scorecard.md").write_text(md, encoding="utf-8")

    print(md)
    print(f"[写入] {out_dir / 'rubric_scorecard.json'}")
    if not ablations:
        print("[提示] 未跑消融判别力检验 → Track R 停留在 UNVERIFIED，分数不得进对外材料。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
