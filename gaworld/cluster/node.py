"""The node process: runs this machine's share of a distributed world.

``python -m gaworld.cluster join <hub> --token <world>.<node>.<secret>`` keeps
one loop going until Ctrl+C or until the token is revoked:

- every two seconds a heartbeat tells the hub how this machine is doing and
  learns whether the world is running, which run, and which residents are ours;
- a new run → download the world package, start the simulator for our
  residents (with this machine's own model settings and key); the hub
  stopping → stop it;
- every second, the interventions waiting for us (players' actions) go into
  the local queue, and new rows of the local record stream go to the hub.

Every request goes from here to the hub, so this works behind NAT; when the hub
cannot be reached the simulator keeps running and records are sent later.
"""

from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests

from gaworld.city.config import agent_file_overrides, run_root_overrides
from gaworld.cluster import bundle

REPO_ROOT = Path(__file__).resolve().parents[2]
NODES_DIR = "output/nodes"
LOOP_SECONDS = 1.0
HEARTBEAT_EVERY = 2
REQUEST_TIMEOUT = 10.0
#: Records sent per request, at most (the hub refuses bodies over 1 MB).
MAX_UPLOAD_BYTES = 768 * 1024


class Revoked(Exception):
    """The hub no longer accepts this node's token."""


def _deep_update(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    from gaworld.settings.overrides import deep_update

    deep_update(base, patch)
    return base


def run_overrides(info: dict[str, Any], package: dict[str, Any], hub_url: str, token: str, base: str) -> dict:
    """The config this node's simulator runs with (``GAWORLD_CONFIG_OVERRIDES``)."""
    world_id, node_id = info["world"]["id"], info["node"]["id"]
    ours = [int(aid) for aid in info["agent_ids"]]
    patch = json.loads(json.dumps(package["settings"]))
    # The city comes from the package, never from this machine's data/cities.
    patch["city"] = package["city_dir"] or ""
    _deep_update(patch, run_root_overrides(f"{base}/run"))
    # The world's agent-keyed inputs came in the package, next to its residents.
    _deep_update(patch, agent_file_overrides(os.path.dirname(package["seed_csv"])))
    patch["csv_path"], patch["md_path"] = package["seed_csv"], package["seed_md"]
    patch["agent_ids"] = ours
    patch["distributed"] = {
        "enabled": True,
        "cluster": world_id,
        "node_id": node_id,
        "local_agent_ids": ours,
        "relay": {"base_url": f"{hub_url}/api/cluster/relay", "token": token},
    }
    patch["cluster"] = {
        "enabled": True,
        "hub_url": hub_url,
        "token": token,
        "run_id": info["run_id"],
        "node_id": node_id,
        "sync_timeout_seconds": info.get("sync_timeout_seconds", 60),
    }
    return patch


class NodeRunner:
    def __init__(self, hub_url: str, token: str, repo_root: str | os.PathLike[str] = REPO_ROOT, log=None):
        self.hub_url = hub_url.rstrip("/")
        self.token = token.strip()
        self.repo_root = str(repo_root)
        # Flushed: a node's output is often redirected to a file or a service log.
        self.log = log or functools.partial(print, flush=True)
        self.http = requests.Session()
        self.http.headers["Authorization"] = f"Bearer {self.token}"
        self.world_id = self.token.split(".", 1)[0]
        self.base = f"{NODES_DIR}/{self.world_id}"
        self.process: subprocess.Popen | None = None
        self.run_id = ""
        self.state = "idle"
        self.error = ""
        self.pending: list[dict[str, Any]] = []
        self.offsets: dict[str, int] = {}
        self.ticks = 0

    # -- paths ---------------------------------------------------------------

    def _abs(self, *parts: str) -> str:
        return os.path.join(self.repo_root, self.base, *parts)

    @property
    def records_dir(self) -> str:
        return self._abs("run", "records")

    @property
    def queue_path(self) -> str:
        return self._abs("run", "kernel", "interventions.json")

    @property
    def log_path(self) -> str:
        return self._abs("run.log")

    # -- talking to the hub --------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        response = self.http.request(method, self.hub_url + path, timeout=REQUEST_TIMEOUT, **kwargs)
        if response.status_code == 401:
            raise Revoked(response.text)
        response.raise_for_status()
        return response

    def _log_tail(self) -> str:
        try:
            with open(self.log_path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                handle.seek(max(0, handle.tell() - 1500))
                return handle.read().decode("utf-8", "replace")
        except OSError:
            return ""

    def heartbeat(self) -> dict[str, Any]:
        payload = {
            "state": self.state,
            "run_id": self.run_id,
            "error": self.error,
            "log_tail": self._log_tail(),
        }
        return self._request("POST", "/api/cluster/node/heartbeat", json=payload).json()

    # -- the simulator -------------------------------------------------------

    def _running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def launch(self, env: dict[str, str]) -> subprocess.Popen:
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        log_file = open(self.log_path, "a", encoding="utf-8")  # noqa: SIM115 -- the child owns it
        log_file.write(f"\n[node] run at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        log_file.flush()
        return subprocess.Popen(
            [sys.executable, os.path.join(self.repo_root, "generative_city_sim.py"), "run"],
            cwd=self.repo_root,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )

    def start(self, info: dict[str, Any]) -> None:
        self.stop()
        self.state, self.error = "downloading", ""
        data = self._request("GET", "/api/cluster/node/bundle").content
        target = self._abs("bundle")
        shutil.rmtree(target, ignore_errors=True)  # nothing of an earlier package lingers
        package = bundle.extract(data, target)
        overrides = run_overrides(info, package, self.hub_url, self.token, self.base)
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["GAWORLD_CONFIG_OVERRIDES"] = json.dumps(overrides, ensure_ascii=False)
        # Rows an earlier run left behind were sent then (or belong to it): start at the end.
        self.offsets = {name: os.path.getsize(path) for name, path in self._record_files()}
        self.pending = []
        self.process = self.launch(env)
        self.run_id = info["run_id"]
        self.state = "running"
        self.log(f"▶ 第 {self.run_id} 次运行：本机负责居民 {info['agent_ids']}（日志 {self.log_path}）")

    def stop(self) -> None:
        if self._running():
            assert self.process is not None
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.log("■ 已停止本机的仿真")
        self.process = None
        if self.state == "running":
            self.state = "idle"

    # -- forwarding ----------------------------------------------------------

    def forward_interventions(self) -> int:
        from gaworld.kernel import remote

        self.pending.extend(self._request("GET", "/api/cluster/node/interventions").json().get("items", []))
        applied = 0
        while self.pending:
            item = self.pending[0]
            try:
                remote.enqueue(self.queue_path, item["name"], item.get("kwargs") or {})
            except KeyError:
                self.log(f"⚠ 本机仿真不认识干预 {item['name']!r}，已丢弃")
            except LookupError:
                break  # the simulator has not published its queue yet; try again next second
            self.pending.pop(0)
            applied += 1
        return applied

    def _record_files(self) -> list[tuple[str, str]]:
        try:
            names = sorted(os.listdir(self.records_dir))
        except OSError:
            return []
        return [
            (name[: -len(".jsonl")], os.path.join(self.records_dir, name))
            for name in names
            if name.endswith(".jsonl")
        ]

    def upload_records(self) -> int:
        tables: dict[str, list[dict[str, Any]]] = {}
        advanced: dict[str, int] = {}
        budget = MAX_UPLOAD_BYTES
        for name, path in self._record_files():
            offset = self.offsets.get(name, 0)
            if budget <= 0 or os.path.getsize(path) <= offset:
                continue
            with open(path, "rb") as handle:
                handle.seek(offset)
                chunk = handle.read(budget)
            end = chunk.rfind(b"\n")
            if end < 0:
                continue  # half a line: wait for the rest
            rows = []
            for line in chunk[: end + 1].splitlines():
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
            if rows:
                tables[name] = rows
            advanced[name] = offset + end + 1
            budget -= end + 1
        if not advanced:
            return 0
        if tables:
            self._request("POST", "/api/cluster/node/records", json={"tables": tables})
        self.offsets.update(advanced)
        return sum(len(rows) for rows in tables.values())

    # -- the loop --------------------------------------------------------------

    def step(self) -> None:
        """One second of the node's life."""
        if self.process is not None and not self._running():
            code = self.process.returncode
            self.process = None
            self.state = "finished" if code == 0 else "error"
            self.error = "" if code == 0 else f"仿真进程退出，返回码 {code}；看日志 {self.log_path}"
            self.log(f"■ 本机仿真结束（返回码 {code}）")
        if self.ticks % HEARTBEAT_EVERY == 0:
            info = self.heartbeat()
            wanted = bool(info.get("running") and info.get("agent_ids") and info.get("run_id"))
            if wanted and info["run_id"] != self.run_id:
                try:
                    self.start(info)
                    self.heartbeat()  # tell the hub at once: actions for our residents may come now
                except (requests.RequestException, OSError, ValueError) as exc:
                    self.state, self.error = "error", f"启动失败：{exc}"
                    self.run_id = info["run_id"]  # do not retry the same run every two seconds
                    self.log(f"✗ {self.error}")
            elif not wanted and self._running():
                self.stop()
                self.run_id = ""
        if self._running() or self.pending:
            self.forward_interventions()
        self.upload_records()
        self.ticks += 1

    def run(self) -> int:
        self.log(f"GAWorld 节点：连接 {self.hub_url}（世界 {self.world_id}），Ctrl+C 退出")
        try:
            while True:
                started = time.time()
                try:
                    self.step()
                except Revoked:
                    self.log("✗ 枢纽拒绝了这个令牌（节点已被移除，或世界已删除）")
                    return 2
                except requests.RequestException as exc:
                    # The hub is out of reach: the simulator carries on alone.
                    self.log(f"⚠ 暂时连不上枢纽：{exc}")
                time.sleep(max(0.0, LOOP_SECONDS - (time.time() - started)))
        except KeyboardInterrupt:
            return 0
        finally:
            self.stop()


__all__ = ["NodeRunner", "Revoked", "run_overrides"]
