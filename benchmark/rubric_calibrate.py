#!/usr/bin/env python3
"""Track R human anchor calibration (design doc §5.3, roadmap P4).

    cd benchmark

    # 1. draw ~30 tasks from a run, stratified over R1–R4 (a third corrupted, blind)
    python rubric_calibrate.py --build --output-dir ../output

    # 2. two people label it in the console: /site/dashboard/rubric-calibration.html
    #    (labels land in results/rubric_calibration/<set>/labels/<name>.json)

    # 3. the judge ensemble scores exactly the same tasks (costs LLM calls)
    python rubric_calibrate.py --judge --set <set_id> --judges minimax,ollama_gemma4

    # 4. α, ρ, QWK and the gate → analysis.json / analysis.md
    python rubric_calibrate.py --analyze --set <set_id>

    python rubric_calibrate.py --list

The next ``rubric_bench.py`` run picks up the newest analysis for the current
rubric; until one passes, the Track R gate stays UNVERIFIED.

``--synthetic`` builds from the synthetic fixtures and judges with the stub,
under results/synthetic/rubric_calibration/, never next to real sets.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rubric import calibration as calib  # noqa: E402
from rubric import loader, runner, synth  # noqa: E402

SYNTHETIC_DIR = Path(__file__).resolve().parent / "results" / "synthetic" / "rubric_calibration"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Track R 人类锚点校准")
    action = p.add_mutually_exclusive_group(required=True)
    action.add_argument("--build", action="store_true", help="从一次运行抽出校准集")
    action.add_argument("--judge", action="store_true", help="让 judge 集成给校准集打分（会调模型）")
    action.add_argument("--analyze", action="store_true", help="算一致性并写 analysis.json / .md")
    action.add_argument("--list", action="store_true", help="列出已有校准集")
    p.add_argument("--output-dir", default="../output", help="GAWorld output/ 目录（--build）")
    p.add_argument("--synthetic", action="store_true", help="合成数据 + stub judge，写到 results/synthetic/ 下")
    p.add_argument("--n", type=int, default=calib.DEFAULT_N, help="任务数（--build）")
    p.add_argument("--seed", type=int, default=7, help="抽任务与选破坏样本的种子（--build）")
    p.add_argument("--sample-seed", type=int, default=42, help="评测单元的抽样种子，与 rubric_bench 一致（--build）")
    p.add_argument("--min-days", type=int, default=30)
    p.add_argument("--set", default="", help="校准集 id（--judge / --analyze）")
    p.add_argument("--judges", default="", help="逗号分隔的 provider 名（--judge）")
    p.add_argument("--samples-per-judge", type=int, default=3)
    p.add_argument("--root", default=None, help="校准集目录，默认 results/rubric_calibration/")
    args = p.parse_args(argv)

    root = Path(args.root) if args.root else (SYNTHETIC_DIR if args.synthetic else calib.CALIBRATION_DIR)

    if args.list:
        for row in calib.list_sets(root):
            gate = (row.get("gate") or {}).get("status") or "未分析"
            print(f"{row['set_id']}  {row['n_tasks']} 个任务  维度 {row['dims']}  标注 {row['annotators']}  "
                  f"judge {'有' if row['judged'] else '无'}  {gate}")
        return 0

    if args.build:
        rubric = runner.load_rubric()
        data = synth.build() if args.synthetic else loader.load_all(Path(args.output_dir))
        set_doc, key_doc = calib.build_set(data, rubric, n=args.n, seed=args.seed, sample_seed=args.sample_seed,
                                           min_days=args.min_days,
                                           source="synthetic" if args.synthetic else str(args.output_dir))
        if not set_doc["tasks"]:
            print("[错误] 这次运行里没有任何 rubric 条目可评（缺 episodes / 轨迹 / 社交数据），抽不出校准任务。")
            return 2
        folder = calib.save_set(set_doc, key_doc, root)
        print(f"[写入] {folder}：{set_doc['n_tasks']} 个任务，按维度 {set_doc['dims']}")
        if set_doc["dims_without_data"]:
            print(f"[提示] 这次运行没有 {'、'.join(set_doc['dims_without_data'])} 的数据，校准集不覆盖它们；"
                  "有了全保真长 run 后重抽一份。")
        return 0

    if not args.set:
        p.error("--judge / --analyze 需要 --set")
    set_doc, key_doc = calib.load_set(args.set, root)

    if args.judge:
        providers = ["stub-a", "stub-b", "stub-c"] if args.synthetic else \
            [s.strip() for s in args.judges.split(",") if s.strip()]
        if not providers:
            p.error("--judge 需要 --judges")
        n_calls = sum(1 for t in set_doc["tasks"] if t["checker"] in calib.JUDGED_CHECKERS) \
            * len(providers) * args.samples_per_judge
        print(f"[judge] {len(providers)} 个 judge × 每题 {args.samples_per_judge} 次，约 {n_calls} 次模型调用")
        judge_doc = calib.judge_set(set_doc, providers, samples_per_judge=args.samples_per_judge,
                                    call=runner.stub_judge if args.synthetic else None)
        calib.save_judge(args.set, judge_doc, root)
        print(f"[写入] {root / args.set / 'judge.json'}")
        return 0

    analysis = calib.run_analysis(args.set, root)
    print(calib.render_markdown(analysis))
    print(json.dumps(analysis["gate"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
