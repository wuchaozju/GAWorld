import base64
import copy
import io
import json
import zipfile

import pytest

from gaworld.research import batch_export
from tests.test_research_batch_api import create
from tests.test_research_batch_api import env as batch_env

env = batch_env


def unpack(batch):
    exported = batch_export.export_zip(batch)
    archive = zipfile.ZipFile(io.BytesIO(base64.b64decode(exported["data"])))
    manifest = json.loads(archive.read("experiment.json"))
    files = {
        name: base64.b64encode(archive.read(name)).decode()
        for name in archive.namelist()
        if name.startswith("inputs/")
    }
    return archive, {"bundle": manifest, "files": files}


def test_export_has_runnable_python_and_no_credentials(env):
    _, source, _ = env
    batch = create(source)
    archive, payload = unpack(batch)
    script = archive.read("run_experiment.py").decode()
    compile(script, "run_experiment.py", "exec")
    assert "GAWorldClient" in script and "127.0.0.1:8766" in script
    assert {"README.md", "experiment.json", "run_experiment.py"} <= set(archive.namelist())
    assert "SECRET_A" not in str(payload) and "SECRET_B" not in str(payload)
    assert "/Users/" not in json.dumps(payload["bundle"])
    imported = batch_export.import_bundle(payload)
    assert imported["id"] != batch["id"]
    assert imported["protocol_hash"] == batch["protocol_hash"]
    assert imported["status"] == "draft"
    assert imported["inputs"][""]["sample_hash"] == batch["inputs"][""]["sample_hash"]


def test_import_rejects_tampering_path_injection_and_version_drift(env):
    _, source, _ = env
    _, payload = unpack(create(source))
    cases = []
    changed = copy.deepcopy(payload)
    changed["files"][next(iter(changed["files"]))] = base64.b64encode(b"bad").decode()
    cases.append(changed)
    changed = copy.deepcopy(payload)
    changed["bundle"]["inputs"][""]["parameters"]["plugins"] = ["evil.py"]
    cases.append(changed)
    changed = copy.deepcopy(payload)
    changed["bundle"]["epoch"] = -1
    cases.append(changed)
    changed = copy.deepcopy(payload)
    changed["bundle"]["inputs"][""]["assets"]["csv_path"]["name"] = "../../secret"
    cases.append(changed)
    for changed in cases:
        with pytest.raises(ValueError):
            batch_export.import_bundle(changed)


def test_export_rejects_changed_frozen_inputs(env):
    _, source, _ = env
    batch = create(source)
    from pathlib import Path

    Path(batch["inputs"][""]["assets"]["csv_path"]["path"]).write_text("tampered")
    with pytest.raises(ValueError):
        batch_export.export_zip(batch)


def test_generated_script_runs_full_experiment_over_local_http(env, monkeypatch):
    import subprocess
    import sys
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from gaworld.accounts.context import USER, WORLD
    from gaworld.apps import routes
    from tests.test_research_batch_execution import install_runner

    root, source, _ = env
    install_runner(monkeypatch)
    archive, _ = unpack(create(source))
    destination = root / "exported"
    archive.extractall(destination)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def dispatch(self):
            user = USER.set({"id": "alice", "role": "member"})
            world = WORLD.set({"id": "alice-world"})
            try:
                if self.command == "GET":
                    result = routes.dispatch_get(self.path, {})
                else:
                    body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    result = routes.dispatch_post(self.path, body)
                data, status = result
                encoded = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
            finally:
                WORLD.reset(world)
                USER.reset(user)

        do_GET = dispatch
        do_POST = dispatch

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(destination / "run_experiment.py"),
                "--url",
                f"http://127.0.0.1:{server.server_port}",
                "--output",
                str(destination / "results"),
                "--interval",
                "0.1",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        saved = list((destination / "results").glob("*/batch.json"))
        assert len(saved) == 1
        actual = json.loads(saved[0].read_text())
        assert actual["status"] == "done"
        assert len(actual["comparison"]["groups"]) == 2
        assert len(list(saved[0].parent.glob("m*.md"))) == 4
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
