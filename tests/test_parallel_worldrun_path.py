"""Closure STAGE B contract tests: the PW production spawn path reaches worldrun.

These tests start from the REAL production functions —
``ExperimentRunner._run_world`` / ``_spawn_when_admitted`` and
``prunner.prepare_experiment`` — and prove that process creation and
checkpoint seeding are delegated to :mod:`gaworld.worldrun` at its
authoritative location (``gaworld.worldrun.run.launch_subprocess`` /
``seed_from_dir``), not re-implemented PW-side.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from gaworld.parallel import runner as prunner
from gaworld.parallel import spec as spec_mod
from gaworld.worldrun import run as worldrun_run

BASIC_PAYLOAD = {
    "name": "worldrun-path",
    "sim_days": 1,
    "seed": 7,
    "worlds": [
        {"label": "基准世界", "events": []},
        {"label": "对照世界", "events": []},
    ],
}

_STUB_SIM = "import sys; sys.exit(0)\n"


def _write_stub(tmp: str) -> str:
    stub = os.path.join(tmp, "stub_sim.py")
    with open(stub, "w", encoding="utf-8") as handle:
        handle.write(_STUB_SIM)
    return stub


class ProductionSpawnPathTests(unittest.TestCase):
    """The runner's own spawn path must go through the worldrun primitive."""

    def test_production_spawn_goes_through_worldrun_launch_primitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = _write_stub(tmp)
            manifest = prunner.prepare_experiment(spec_mod.normalize_experiment(BASIC_PAYLOAD), tmp)
            live = prunner.ExperimentRunner(
                manifest, tmp, python_bin=sys.executable, script_path=stub, reset=False
            )
            world_id = sorted(manifest["worlds"])[0]
            calls: list[dict] = []
            real_launch = worldrun_run.launch_subprocess

            def recording_launch(command, **kwargs):
                calls.append({"command": list(command), **kwargs})
                return real_launch(command, **kwargs)

            with mock.patch.object(worldrun_run, "launch_subprocess", recording_launch):
                # Run the REAL world lifecycle, not a direct launch call.
                live._run_world(world_id)

            self.assertEqual(live._states[world_id]["status"], "done")
            self.assertEqual(len(calls), 1, "production spawn must reach worldrun exactly once")
            call = calls[0]
            self.assertEqual(call["command"], [sys.executable, stub, "run"])
            self.assertEqual(call["cwd"], tmp)
            self.assertEqual(call["world_id"], world_id)
            # run.log capture: the child's stdout tees into the world's log.
            self.assertEqual(
                os.path.abspath(getattr(call["stdout"], "name", "")),
                os.path.abspath(os.path.join(tmp, manifest["worlds"][world_id]["run_log"])),
            )
            # Historical PW process-group semantics preserved.
            self.assertFalse(call["new_process_group"])

    def test_worldrun_launch_subprocess_defaults_are_unchanged(self):
        """The new stdout/new_process_group options are strictly additive."""
        captured: dict = {}

        class FakeProc:
            pid = 4242

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return 0

        def fake_popen(command, **kwargs):
            captured.update(kwargs)
            return FakeProc()

        with mock.patch.object(worldrun_run.subprocess, "Popen", fake_popen):
            # Default: DEVNULL + fresh session, exactly the old contract.
            worldrun_run.launch_subprocess(["x"], world_id="w")
            self.assertIs(captured["stdout"], subprocess.DEVNULL)
            self.assertIs(captured["stderr"], subprocess.DEVNULL)
            if hasattr(os, "setsid"):
                self.assertTrue(captured["start_new_session"])
            else:
                self.assertNotIn("start_new_session", captured)
            # Opt-in: log capture + caller's process group.
            captured.clear()
            with open(os.devnull, "w") as handle:
                worldrun_run.launch_subprocess(
                    ["x"],
                    world_id="w",
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    new_process_group=False,
                )
            self.assertIs(captured["stdout"], handle)
            self.assertIs(captured["stderr"], subprocess.STDOUT)
            self.assertNotIn("start_new_session", captured)


class SeedFromCheckpointPlumbTests(unittest.TestCase):
    """seed_from_checkpoint materializes the world dir via worldrun.seed_from_dir."""

    def _make_source_run(self, tmp: str) -> str:
        source = os.path.join(tmp, "source_run")
        os.makedirs(os.path.join(source, "state"))
        os.makedirs(os.path.join(source, "checkpoints", "day_0002"))
        with open(os.path.join(source, "state", "agent_state_history.csv"), "w") as handle:
            handle.write("agent_id,step,metric,value\n1,1,emotion,0.5\n")
        with open(os.path.join(source, "checkpoints", "day_0002", "ckpt.json"), "w") as handle:
            handle.write("{}\n")
        return source

    def test_seeded_world_dir_is_materialized_and_reset_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self._make_source_run(tmp)
            payload = dict(
                BASIC_PAYLOAD,
                worlds=[
                    {"label": "种子世界", "events": [], "seed_from_checkpoint": source},
                    {"label": "对照世界", "events": []},
                ],
            )
            manifest = prunner.prepare_experiment(spec_mod.normalize_experiment(payload), tmp)
            seeded = next(wid for wid, entry in manifest["worlds"].items() if entry.get("seeded_from"))
            entry = manifest["worlds"][seeded]
            self.assertEqual(entry["seeded_from"], source)
            world_abs = os.path.join(tmp, entry["dir"])
            # Checkpoint + history came from the source run; source untouched.
            self.assertTrue(os.path.isdir(os.path.join(world_abs, "checkpoints", "day_0002")))
            with open(os.path.join(world_abs, "state", "agent_state_history.csv")) as handle:
                self.assertIn("emotion", handle.read())
            self.assertTrue(os.path.exists(os.path.join(source, "state", "agent_state_history.csv")))

            stub = os.path.join(tmp, "stub_sim.py")
            with open(stub, "w", encoding="utf-8") as handle:
                handle.write("import sys; sys.exit(0)\n")  # reset must succeed here
            live = prunner.ExperimentRunner(
                manifest, tmp, python_bin=sys.executable, script_path=stub, reset=True
            )
            live._run_world(seeded)
            self.assertEqual(live._states[seeded]["status"], "done")
            self.assertFalse(os.path.exists(os.path.join(tmp, entry["reset_log"])))
            # A sibling world without a seed still gets the reset treatment.
            other = next(wid for wid in manifest["worlds"] if wid != seeded)
            live._run_world(other)
            self.assertEqual(live._states[other]["status"], "done")
            self.assertTrue(os.path.exists(os.path.join(tmp, manifest["worlds"][other]["reset_log"])))

    def test_unresolvable_seed_ref_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = dict(
                BASIC_PAYLOAD,
                worlds=[
                    {"label": "坏种子", "events": [], "seed_from_checkpoint": "no/such/ref"},
                    {"label": "对照世界", "events": []},
                ],
            )
            with self.assertRaises(FileNotFoundError):
                prunner.prepare_experiment(spec_mod.normalize_experiment(payload), tmp)
