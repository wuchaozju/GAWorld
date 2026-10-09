"""The ``compare-event`` and ``parallel-worlds`` subcommands.

``compare-event`` runs the simulator twice in subprocesses (with and without
one event) and writes a comparison report; ``parallel-worlds`` runs an
experiment file through :mod:`gaworld.parallel`. Moved out of
``generative_city_sim.py`` (REFACTOR_PLAN stage 1) unchanged; the simulator
re-exports every name, so ``generative_city_sim.<name>`` keeps working.
"""

import json
import os
import re
import subprocess
import sys
import time

import pandas as pd

from gaworld.logging_setup import get_logger
from gaworld.policy.intervention import INTERVENTION_METRICS
from gaworld.settings import CONFIG

_LOG = get_logger("gaworld.sim")
#: The repository root, and the simulator script compare-event runs twice.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SIM_SCRIPT = os.path.join(_REPO_ROOT, "generative_city_sim.py")


def _sanitize_slug(text):
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", str(text or "").strip())
    cleaned = cleaned.strip("_")
    return cleaned[:40] if cleaned else "event"


def _extract_run_failure_hint(log_path, max_lines=80):
    if not log_path or not os.path.exists(log_path):
        return "日志不存在"
    try:
        with open(log_path, encoding="utf-8") as f:
            lines = [line.rstrip("\n") for line in f]
    except OSError:
        return "日志读取失败"
    if not lines:
        return "日志为空"
    tail = lines[-max_lines:]
    joined = "\n".join(tail)
    hint_lines = []
    traceback_start = None
    for idx, line in enumerate(tail):
        if line.startswith("Traceback (most recent call last):"):
            traceback_start = idx
            break
    if traceback_start is not None:
        hint_lines.extend(tail[traceback_start:])
    else:
        error_markers = ["RuntimeError", "ConnectionError", "ValueError", "KeyError", "Exception"]
        for line in reversed(tail):
            if any(marker in line for marker in error_markers):
                hint_lines = [line]
                break
    if not hint_lines:
        hint_lines = tail[-8:]
    snippet = "\n".join(hint_lines[-20:])
    if "localhost" in joined and "11434" in joined and "Connection refused" in joined:
        snippet += (
            "\n建议：当前配置正在请求本地 Ollama（localhost:11434），"
            "请先启动 Ollama，或在 compare-event 命令中显式指定可用 provider（--llm-provider）。"
        )
    return snippet


def _build_compare_overrides(scenario_dir, include_event, event_payload, args):
    policy_events = [dict(item) for item in CONFIG.get("policy_events", []) if isinstance(item, dict)]
    if include_event:
        policy_events.append(dict(event_payload))
    overrides = {
        "memory_dir": os.path.join(scenario_dir, "memory"),
        "log_dir": os.path.join(scenario_dir, "logs"),
        "vector_db_path": os.path.join(scenario_dir, "memory", "vector_db.sqlite"),
        "state_output_dir": os.path.join(scenario_dir, "state"),
        "network_output_dir": os.path.join(scenario_dir, "network"),
        "environment_output_dir": os.path.join(scenario_dir, "environment"),
        "intervention": {
            "output_dir": os.path.join(scenario_dir, "intervention"),
        },
        "visualization": {
            "enabled": True,
            "output_dir": os.path.join(scenario_dir, "visualization"),
            "site_path": CONFIG.get("visualization", {}).get("site_path", "site/simviz/index.html"),
        },
        "policy_events": policy_events,
        "stateful": True,
        "random_seed": int(args.seed),
        "distributed": {
            "enabled": False,
        },
    }
    if args.sim_days is not None:
        overrides["sim_days"] = int(args.sim_days)
    if args.agent_ids:
        overrides["agent_ids"] = list(args.agent_ids)
    if getattr(args, "fast", False):
        # Fast mode: cut LLM calls per agent-day (deterministic cognition, skip
        # daily summary/diary) and shrink the cohort. Trades fidelity for speed
        # so local models can run longer horizons.
        overrides["fos_fast_mode"] = {
            "deterministic_cognition": True,
            "skip_daily_summary": True,
            "skip_daily_diary": True,
        }
        overrides.setdefault("agent_ids", [1, 2, 3])  # unless --agent-id was given
    if getattr(args, "llm_provider", None):
        routing = CONFIG.get("llm", {}).get("routing", {})
        task_map = routing.get("tasks", {})
        forced_tasks = {}
        if isinstance(task_map, dict):
            forced_tasks = {str(k): str(args.llm_provider) for k in task_map}
        overrides["llm"] = {
            "routing": {
                "default": str(args.llm_provider),
                "tasks": forced_tasks,
            }
        }
    return overrides


def _run_cli_subprocess(command, env, log_path):
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        proc = subprocess.run(
            command,
            env=env,
            stdout=f,
            stderr=subprocess.STDOUT,
            text=True,
        )
    return proc.returncode


def _launch_cli_subprocess(command, env, log_path):
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    f = open(log_path, "w", encoding="utf-8")  # noqa: SIM115 — the child writes to it; the caller closes it
    proc = subprocess.Popen(
        command,
        env=env,
        stdout=f,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc, f


def _final_metric_snapshot(state_csv_path):
    if not state_csv_path or not os.path.exists(state_csv_path):
        return {}
    try:
        df = pd.read_csv(state_csv_path)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError) as exc:
        _LOG.warning("Failed to read state CSV %s: %s", state_csv_path, exc)
        return {}
    required = {"agent_id", "step", "metric", "value"}
    if df.empty or not required.issubset(set(df.columns)):
        return {}
    final_idx = df.groupby(["agent_id", "metric"])["step"].idxmax()
    final_df = df.loc[final_idx]
    grouped = final_df.groupby("metric")["value"].mean()
    return {str(k): float(v) for k, v in grouped.items()}


def _mean_metric_snapshot(state_csv_path):
    if not state_csv_path or not os.path.exists(state_csv_path):
        return {}
    try:
        df = pd.read_csv(state_csv_path)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError) as exc:
        _LOG.warning("Failed to read state CSV %s: %s", state_csv_path, exc)
        return {}
    required = {"metric", "value"}
    if df.empty or not required.issubset(set(df.columns)):
        return {}
    grouped = df.groupby("metric")["value"].mean()
    return {str(k): float(v) for k, v in grouped.items()}


def _compose_comparison_rows(base_state_csv, event_state_csv):
    baseline_final = _final_metric_snapshot(base_state_csv)
    event_final = _final_metric_snapshot(event_state_csv)
    baseline_mean = _mean_metric_snapshot(base_state_csv)
    event_mean = _mean_metric_snapshot(event_state_csv)
    metrics = sorted(set(baseline_final) | set(event_final) | set(baseline_mean) | set(event_mean))
    rows = []
    for metric in metrics:
        b_final = float(baseline_final.get(metric, 0.0))
        e_final = float(event_final.get(metric, 0.0))
        b_mean = float(baseline_mean.get(metric, 0.0))
        e_mean = float(event_mean.get(metric, 0.0))
        rows.append(
            {
                "metric": metric,
                "baseline_final": b_final,
                "event_final": e_final,
                "delta_final": e_final - b_final,
                "baseline_mean": b_mean,
                "event_mean": e_mean,
                "delta_mean": e_mean - b_mean,
            }
        )
    rows.sort(key=lambda x: abs(x["delta_final"]), reverse=True)
    return rows


def _impact_hint(metric, delta):
    if abs(delta) < 1e-9:
        return "几乎无变化"
    sign = "上升" if delta > 0 else "下降"
    amount = abs(delta)
    if metric == "stress":
        direction = "压力" + sign
    elif metric == "emotion":
        direction = "情绪" + sign
    elif metric == "econ_security":
        direction = "经济安全感" + sign
    elif metric == "city_identity":
        direction = "城市认同" + sign
    elif metric == "mobility_intent":
        direction = "流动意愿" + sign
    elif metric == "stance_score":
        direction = "平均立场分数" + sign
    elif metric == "toxicity_score":
        direction = "毒性风险" + sign
    elif metric == "misinformation_risk":
        direction = "误信息风险" + sign
    elif metric == "cross_viewpoint_exposure":
        direction = "跨观点曝光" + sign
    elif metric == "intervention_reward":
        direction = "干预奖励" + sign
    else:
        direction = f"{metric}" + sign
    return f"{direction}（Δ={amount:.4f}）"


def _write_comparison_report(output_root, event_payload, rows):
    os.makedirs(output_root, exist_ok=True)
    metrics_csv = os.path.join(output_root, "comparison_metrics.csv")
    report_md = os.path.join(output_root, "comparison_summary.md")
    if rows:
        pd.DataFrame(rows).to_csv(metrics_csv, index=False)
    else:
        pd.DataFrame(
            columns=[
                "metric",
                "baseline_final",
                "event_final",
                "delta_final",
                "baseline_mean",
                "event_mean",
                "delta_mean",
            ]
        ).to_csv(metrics_csv, index=False)

    lines = []
    lines.append("# 事件影响对比报告")
    lines.append("")
    lines.append(f"- 事件名称：{event_payload.get('name', '')}")
    lines.append(f"- 事件时间：Day {event_payload.get('day', '')} {event_payload.get('time', '')}")
    lines.append(f"- 事件描述：{event_payload.get('description', '')}")
    lines.append("")
    if rows:
        top = rows[:5]
        intervention_rows = [row for row in rows if row.get("metric") in set(INTERVENTION_METRICS)]
        intervention_rows.sort(key=lambda x: abs(x["delta_final"]), reverse=True)
        if intervention_rows:
            lines.append("## PolicySim 干预指标")
            lines.append("")
            for item in intervention_rows:
                hint = _impact_hint(item["metric"], item["delta_final"])
                lines.append(
                    f"- `{item['metric']}`: baseline={item['baseline_final']:.4f}, "
                    f"event={item['event_final']:.4f}, Δ={item['delta_final']:.4f}，{hint}"
                )
            lines.append("")
        lines.append("## 关键差异（按终值绝对差排序）")
        lines.append("")
        for item in top:
            hint = _impact_hint(item["metric"], item["delta_final"])
            lines.append(
                f"- `{item['metric']}`: baseline={item['baseline_final']:.4f}, "
                f"event={item['event_final']:.4f}, Δ={item['delta_final']:.4f}，{hint}"
            )
        lines.append("")
        lines.append("## 估计结论")
        lines.append("")
        top_hint = "；".join(_impact_hint(r["metric"], r["delta_final"]) for r in top[:3])
        lines.append(f"事件对系统的主要影响表现为：{top_hint}。")
    else:
        lines.append("未生成有效状态对比数据，请检查两组 simulation 输出。")
    lines.append("")
    lines.append(f"- 指标明细：`{metrics_csv}`")
    with open(report_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return report_md, metrics_csv


def _cli_compare_event(args):
    event_payload = {
        "day": int(args.event_day),
        "time": str(args.event_time),
        "name": str(args.event_name),
        "description": str(args.event_description),
    }
    ts = time.strftime("%Y%m%d_%H%M%S")
    slug = _sanitize_slug(args.event_name)
    root = os.path.join(args.output_root, f"{ts}_{slug}")
    baseline_dir = os.path.join(root, "without_event")
    event_dir = os.path.join(root, "with_event")
    os.makedirs(baseline_dir, exist_ok=True)
    os.makedirs(event_dir, exist_ok=True)

    # Stamp run metadata so downstream scoring can flag low-fidelity (--fast)
    # runs and tell which code epoch produced the pair (see
    # gaworld/core/comparability.py).
    from gaworld.core.comparability import CURRENT_EPOCH

    with open(os.path.join(root, "run_meta.json"), "w", encoding="utf-8") as _meta:
        json.dump(
            {
                "comparability_epoch": CURRENT_EPOCH,
                "fast": bool(getattr(args, "fast", False)),
                "sim_days": args.sim_days,
                "seed": getattr(args, "seed", None),
                "llm_provider": getattr(args, "llm_provider", None),
                "event_name": str(args.event_name),
            },
            _meta,
            ensure_ascii=False,
            indent=2,
        )

    baseline_overrides = _build_compare_overrides(
        baseline_dir,
        include_event=False,
        event_payload=event_payload,
        args=args,
    )
    event_overrides = _build_compare_overrides(
        event_dir,
        include_event=True,
        event_payload=event_payload,
        args=args,
    )

    script_path = _SIM_SCRIPT
    python_bin = sys.executable
    base_env = os.environ.copy()
    env_without = dict(base_env)
    env_with = dict(base_env)
    env_without["GAWORLD_CONFIG_OVERRIDES"] = json.dumps(baseline_overrides, ensure_ascii=False)
    env_with["GAWORLD_CONFIG_OVERRIDES"] = json.dumps(event_overrides, ensure_ascii=False)

    # Clean reset both scenarios before run.
    reset_without_log = os.path.join(baseline_dir, "reset.log")
    reset_with_log = os.path.join(event_dir, "reset.log")
    rc = _run_cli_subprocess([python_bin, script_path, "reset"], env_without, reset_without_log)
    if rc != 0:
        raise RuntimeError(f"无事件场景 reset 失败，日志：{reset_without_log}")
    rc = _run_cli_subprocess([python_bin, script_path, "reset"], env_with, reset_with_log)
    if rc != 0:
        raise RuntimeError(f"有事件场景 reset 失败，日志：{reset_with_log}")

    # Run in parallel.
    run_without_log = os.path.join(baseline_dir, "run.log")
    run_with_log = os.path.join(event_dir, "run.log")
    proc_without, file_without = _launch_cli_subprocess(
        [python_bin, script_path, "run"],
        env_without,
        run_without_log,
    )
    proc_with, file_with = _launch_cli_subprocess(
        [python_bin, script_path, "run"],
        env_with,
        run_with_log,
    )
    code_without = proc_without.wait()
    code_with = proc_with.wait()
    file_without.close()
    file_with.close()
    if code_without != 0 or code_with != 0:
        without_hint = _extract_run_failure_hint(run_without_log)
        with_hint = _extract_run_failure_hint(run_with_log)
        raise RuntimeError(
            "并行 simulation 运行失败。"
            f"\n无事件日志：{run_without_log}\n{without_hint}\n"
            f"\n有事件日志：{run_with_log}\n{with_hint}"
        )

    baseline_state_csv = os.path.join(baseline_overrides["state_output_dir"], "agent_state_history.csv")
    event_state_csv = os.path.join(event_overrides["state_output_dir"], "agent_state_history.csv")
    rows = _compose_comparison_rows(baseline_state_csv, event_state_csv)
    report_md, metrics_csv = _write_comparison_report(root, event_payload, rows)

    print("\n✅ 对比 simulation 完成")
    print(f"输出目录: {root}")
    print(f"报告文件: {report_md}")
    print(f"指标文件: {metrics_csv}")
    if rows:
        print("\nTop differences:")
        for item in rows[:5]:
            print(
                f"- {item['metric']}: baseline={item['baseline_final']:.4f}, "
                f"event={item['event_final']:.4f}, delta={item['delta_final']:.4f}"
            )


def _cli_parallel_worlds(args):
    """Run N worlds from a JSON experiment file.

    ``compare-event`` stays as-is (two worlds, its own output layout, the
    benchmark reads it); this is the generalised form for three or more
    branches, and it shares its engine with the console's Parallel Worlds
    panel so a spec written here opens there and vice versa.
    """
    from gaworld.parallel import ExperimentRunner, normalize_experiment, prepare_experiment
    from gaworld.parallel.analysis import summarize_report
    from gaworld.parallel.sweep import describe_patch, parse_sweep_arg, sweep_worlds

    if not args.spec and not args.sweep:
        raise SystemExit("parallel-worlds 需要 --spec 或 --sweep")
    payload = {}
    if args.spec:
        with open(args.spec, encoding="utf-8") as f:
            payload = json.load(f)
    if args.sweep:
        # The spec, if any, supplies the shared settings and — through its
        # baseline world — events every swept world shares; its worlds are replaced.
        declared = [w for w in payload.get("worlds") or [] if isinstance(w, dict)]
        base = next(
            (
                w
                for w in declared
                if w.get("role") == "baseline" or (w.get("id") and w.get("id") == payload.get("baseline_id"))
            ),
            declared[0] if declared else {},
        )
        try:
            path, values = parse_sweep_arg(args.sweep)
            expanded = sweep_worlds(CONFIG, path, values, events=base.get("events"), placebo=args.placebo)
        except ValueError as exc:
            raise SystemExit(f"参数扫描：{exc}") from None
        payload["worlds"] = expanded["worlds"]
        payload["baseline_id"] = expanded["baseline_id"]
        payload.setdefault("name", f"参数扫描 {path}")
        for item in expanded["dropped"]:
            print(f"跳过取值 {item['value']}：{item['reason']}")
    if args.sim_days is not None:
        payload["sim_days"] = int(args.sim_days)
    if args.seed is not None:
        payload["seed"] = int(args.seed)
    if args.llm_provider:
        payload["llm_provider"] = args.llm_provider
    if args.fast:
        payload["fast"] = True

    spec = normalize_experiment(payload)
    repo_root = _REPO_ROOT
    manifest = prepare_experiment(spec, repo_root, output_root=args.output_root, base_config=CONFIG)
    print(f"实验目录：{manifest['root']}")
    for world in spec.worlds:
        marker = "（基准）" if world.id == spec.baseline_id else ""
        events = (
            "；".join(
                [f"Day {item['day']} {item['time']} {item['name']}" for item in world.events]
                + describe_patch(world.config)
            )
            or "无事件"
        )
        print(f"  - {world.label}{marker}：{events}")

    runner = ExperimentRunner(manifest, repo_root, max_parallel=spec.max_parallel)
    report = runner.run(on_progress=lambda progress, message: print(f"[{progress:6.1%}] {message}"))
    print("\n✅ 平行世界实验完成")
    for line in summarize_report(report):
        print(f"- {line}")
    print(f"\n报告：{os.path.join(manifest['root'], 'divergence_summary.md')}")
