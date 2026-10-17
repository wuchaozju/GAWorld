"""Exported, runnable Python client for a frozen GAWorld experiment."""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
from pathlib import Path

try:
    from gaworld.client import GAWorldClient
except ModuleNotFoundError:
    from gaworld_client import GAWorldClient


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8766")
    parser.add_argument("--world", help="Select an existing authorized local world")
    parser.add_argument("--batch-id", help="Continue an imported local batch")
    parser.add_argument("--check-only", action="store_true", help="Import/check without model calls")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("results"))
    parser.add_argument("--interval", type=float, default=2)
    args = parser.parse_args()
    gw = GAWorldClient(args.url)
    if os.environ.get("GAWORLD_USER"):
        gw.login(os.environ["GAWORLD_USER"], os.environ["GAWORLD_PASSWORD"])
    if args.world:
        gw.post("/api/worlds/select", {"id": args.world})
    if args.batch_id:
        batch = gw.get("/api/research/batches/" + args.batch_id)
    else:
        directory = Path(__file__).resolve().parent
        manifest = json.loads((directory / "experiment.json").read_text(encoding="utf-8"))
        files = {}
        for entry in manifest["inputs"].values():
            for asset in entry["assets"].values():
                path = (directory / asset["name"]).resolve()
                if not path.is_relative_to(directory):
                    raise ValueError("Input escaped experiment directory")
                files[asset["name"]] = base64.b64encode(path.read_bytes()).decode("ascii")
        batch = gw.post("/api/research/batches/import", {"bundle": manifest, "files": files})
    batch_id = batch["id"]
    path = "/api/research/batches/" + batch_id
    print("Local batch:", batch_id, flush=True)
    print(json.dumps(batch["preflight"], ensure_ascii=False, indent=2), flush=True)
    output = args.output / batch_id
    output.mkdir(parents=True, exist_ok=True)
    if args.check_only:
        (output / "batch.json").write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if batch["preflight"]["ok"] else 2
    if not batch["preflight"]["ok"]:
        return 2
    try:
        if batch["status"] not in {"running", "paused", "stopping", "done"}:
            gw.post(path + "/run", {"retry_failed": args.retry_failed})
        elif batch["status"] == "paused":
            gw.post(path + "/resume", {})
        while True:
            batch = gw.get(path)
            print(batch["status"], f"{batch.get('progress', 0):.0%}", flush=True)
            if batch["status"] not in {"running", "paused", "stopping"}:
                break
            time.sleep(max(0.1, args.interval))
    except KeyboardInterrupt:
        gw.post(path + "/stop", {})
        batch = gw.get(path)
        print("Stop requested; original results retained.", flush=True)
    finally:
        (output / "batch.json").write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
        report = gw.get(path + "/report")
        (output / "report.md").write_text(report["markdown"], encoding="utf-8")
        for cell in batch["cells"]:
            if cell.get("study_id"):
                child_path = "/api/research/studies/" + cell["study_id"]
                child = gw.get(child_path)
                (output / (cell["id"] + ".json")).write_text(
                    json.dumps(child, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                child_report = gw.get(child_path + "/report")
                (output / (cell["id"] + ".md")).write_text(child_report["markdown"], encoding="utf-8")
    return 0 if batch["status"] == "done" else 2


if __name__ == "__main__":
    raise SystemExit(main())
