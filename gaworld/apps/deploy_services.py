from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    command: list[str]
    health_url: str


def _run(command: list[str], *, cwd: Path, dry_run: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    print("+ " + " ".join(command))
    if dry_run:
        return subprocess.CompletedProcess(command, 0, "", "")
    return subprocess.run(command, cwd=str(cwd), check=check, text=True)


def _capture(command: list[str], *, cwd: Path) -> str:
    return subprocess.check_output(command, cwd=str(cwd), text=True).strip()


def _repo_root(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def _venv_python(repo: Path, venv: str) -> Path:
    root = (repo / venv).resolve()
    if sys.platform == "win32":
        return root / "Scripts" / "python.exe"
    return root / "bin" / "python"


def _host_for_health(host: str) -> str:
    return "127.0.0.1" if host in {"0.0.0.0", "::"} else host


def service_specs(args, python_bin: str) -> list[ServiceSpec]:
    health_host = _host_for_health(args.host)
    return [
        ServiceSpec(
            name="dashboard",
            command=[
                python_bin,
                "generative_city_sim.py",
                "dashboard",
                "--host",
                args.host,
                "--port",
                str(args.dashboard_port),
            ],
            health_url=f"http://{health_host}:{args.dashboard_port}/api/config",
        ),
        ServiceSpec(
            name="relay",
            command=[
                python_bin,
                "generative_city_sim.py",
                "serve-distributed",
                "--host",
                args.host,
                "--port",
                str(args.relay_port),
                "--state-path",
                args.relay_state_path,
                "--max-messages",
                str(args.relay_max_messages),
            ],
            health_url=f"http://{health_host}:{args.relay_port}/health",
        ),
    ]


def _is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _stop_service(pidfile: Path, *, dry_run: bool = False, timeout: float = 8.0) -> None:
    pid = _read_pid(pidfile)
    if pid is None:
        return
    if not _is_running(pid):
        if not dry_run:
            pidfile.unlink(missing_ok=True)
        return
    print(f"stopping pid {pid} from {pidfile}")
    if dry_run:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pidfile.unlink(missing_ok=True)
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _is_running(pid):
            pidfile.unlink(missing_ok=True)
            return
        time.sleep(0.2)
    os.kill(pid, signal.SIGKILL)
    pidfile.unlink(missing_ok=True)


def _start_service(repo: Path, spec: ServiceSpec, runtime_dir: Path, *, dry_run: bool = False) -> int:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    log_path = runtime_dir / f"{spec.name}.log"
    pidfile = runtime_dir / f"{spec.name}.pid"
    _stop_service(pidfile, dry_run=dry_run)
    print(f"starting {spec.name}; log={log_path}")
    if dry_run:
        return 0
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo) + os.pathsep + env.get("PYTHONPATH", "")
    with open(log_path, "ab") as log:
        process = subprocess.Popen(
            spec.command,
            cwd=str(repo),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    pidfile.write_text(str(process.pid), encoding="utf-8")
    return process.pid


def _health_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urlopen(url, timeout=timeout) as response:
            return 200 <= int(response.status) < 500
    except (OSError, URLError):
        return False


def _wait_for_health(specs: list[ServiceSpec], *, seconds: float, dry_run: bool = False) -> bool:
    if dry_run:
        return True
    deadline = time.time() + seconds
    pending = {spec.name: spec for spec in specs}
    while pending and time.time() < deadline:
        for name, spec in list(pending.items()):
            if _health_ok(spec.health_url):
                print(f"{name} healthy: {spec.health_url}")
                pending.pop(name, None)
        if pending:
            time.sleep(0.5)
    for spec in pending.values():
        print(f"{spec.name} health check failed: {spec.health_url}")
    return not pending


def sync_code(args, repo: Path) -> None:
    if args.no_git:
        print("skip git sync")
        return
    _run(["git", "fetch", args.remote], cwd=repo, dry_run=args.dry_run)
    branch_exists = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", args.branch],
        cwd=str(repo),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0
    if branch_exists:
        _run(["git", "switch", args.branch], cwd=repo, dry_run=args.dry_run)
    else:
        _run(
            ["git", "switch", "--track", f"{args.remote}/{args.branch}"],
            cwd=repo,
            dry_run=args.dry_run,
        )
    _run(["git", "pull", "--ff-only", args.remote, args.branch], cwd=repo, dry_run=args.dry_run)


def install_dependencies(args, repo: Path) -> Path:
    python_bin = Path(args.python).expanduser().resolve() if args.python else Path(sys.executable)
    venv_python = _venv_python(repo, args.venv)
    if not args.no_venv and not venv_python.exists():
        _run([str(python_bin), "-m", "venv", args.venv], cwd=repo, dry_run=args.dry_run)
    runtime_python = python_bin if args.no_venv else venv_python
    if args.skip_install:
        print("skip dependency install")
        return runtime_python
    requirements = repo / args.requirements
    if not requirements.exists():
        raise FileNotFoundError(f"requirements file not found: {requirements}")
    _run(
        [str(runtime_python), "-m", "pip", "install", "-r", args.requirements],
        cwd=repo,
        dry_run=args.dry_run,
    )
    return runtime_python


def deploy_once(args) -> int:
    repo = _repo_root(args.repo)
    runtime_dir = (repo / args.runtime_dir).resolve()
    sync_code(args, repo)
    runtime_python = install_dependencies(args, repo)
    specs = service_specs(args, str(runtime_python))
    for spec in specs:
        _start_service(repo, spec, runtime_dir, dry_run=args.dry_run)
    return 0 if _wait_for_health(specs, seconds=args.health_timeout, dry_run=args.dry_run) else 1


def status(args) -> int:
    repo = _repo_root(args.repo)
    runtime_dir = (repo / args.runtime_dir).resolve()
    runtime_python = _venv_python(repo, args.venv)
    if args.no_venv or not runtime_python.exists():
        runtime_python = Path(args.python).expanduser().resolve() if args.python else Path(sys.executable)
    failed = False
    for spec in service_specs(args, str(runtime_python)):
        pid = _read_pid(runtime_dir / f"{spec.name}.pid")
        running = _is_running(pid or 0)
        healthy = _health_ok(spec.health_url)
        print(f"{spec.name}: pid={pid or '-'} running={running} healthy={healthy} url={spec.health_url}")
        failed = failed or not healthy
    return 1 if failed else 0


def watch(args) -> int:
    repo = _repo_root(args.repo)
    while True:
        try:
            before = _capture(["git", "rev-parse", "HEAD"], cwd=repo)
            _run(["git", "fetch", args.remote], cwd=repo, dry_run=args.dry_run, check=True)
            after = _capture(["git", "rev-parse", f"{args.remote}/{args.branch}"], cwd=repo)
            if before != after:
                print(f"new version detected: {before[:12]} -> {after[:12]}")
                code = deploy_once(args)
                if code != 0:
                    print("deploy failed; will retry on next poll")
            else:
                print(f"no change on {args.remote}/{args.branch}: {before[:12]}")
        except Exception as exc:
            print(f"watch iteration failed: {exc}", file=sys.stderr)
        time.sleep(max(5, int(args.interval)))


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=None, help="Repository path. Defaults to this checkout.")
    parser.add_argument("--remote", default="origin", help="Git remote name.")
    parser.add_argument("--branch", default="Dev", help="Branch to deploy.")
    parser.add_argument("--host", default="0.0.0.0", help="Service bind host.")
    parser.add_argument("--dashboard-port", type=int, default=8766, help="Dashboard/team board port.")
    parser.add_argument("--relay-port", type=int, default=8877, help="Agent relay port.")
    parser.add_argument(
        "--relay-state-path",
        default="output/distributed/relay_state.json",
        help="Relay state JSON path, relative to repo unless absolute.",
    )
    parser.add_argument("--relay-max-messages", type=int, default=20000)
    parser.add_argument("--runtime-dir", default="runtime/services", help="Pid/log directory.")
    parser.add_argument("--python", default=None, help="Python executable used to create/run the venv.")
    parser.add_argument("--venv", default=".venv-deploy", help="Virtualenv directory.")
    parser.add_argument("--requirements", default="requirements.txt")
    parser.add_argument("--skip-install", action="store_true", help="Do not run pip install.")
    parser.add_argument("--no-venv", action="store_true", help="Use --python/current Python directly.")
    parser.add_argument("--no-git", action="store_true", help="Restart current checkout without git fetch/pull.")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without changing anything.")
    parser.add_argument("--health-timeout", type=float, default=30.0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deploy GAWorld dashboard and distributed relay services.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    deploy = subparsers.add_parser("deploy", help="Fetch/pull code, install deps, restart services, check health.")
    _add_common(deploy)
    restart = subparsers.add_parser("restart", help="Restart services from the current checkout.")
    _add_common(restart)
    restart.set_defaults(no_git=True, skip_install=True)
    stat = subparsers.add_parser("status", help="Show pidfile and health-check status.")
    _add_common(stat)
    watch_cmd = subparsers.add_parser("watch", help="Poll Git and auto-deploy when the target branch changes.")
    _add_common(watch_cmd)
    watch_cmd.add_argument("--interval", type=int, default=60, help="Polling interval in seconds.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "deploy":
        return deploy_once(args)
    if args.command == "restart":
        args.no_git = True
        args.skip_install = True
        return deploy_once(args)
    if args.command == "status":
        return status(args)
    if args.command == "watch":
        return watch(args)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
