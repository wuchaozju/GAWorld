"""Branch comparison API: the existing Parallel-Worlds analysis, exposed.

Phase 7 STAGE A (RED). The SimTree frontend needs quantitative branch
comparison, and the analysis already exists — ``gaworld/parallel`` — so the
contract under test is *reuse*:

* ``POST /api/analysis/compare`` takes a PW-compatible manifest and returns
  the same report ``analyze_experiment`` builds, with artifacts written under
  ``output/comparisons/<comparison-id>/`` using the existing artifact names.
* The request must not become an arbitrary file-read endpoint: manifest paths
  are jailed to the repo root (traversal, outside-root absolute, symlink
  escape), and a missing state CSV is a clear 4xx, not a silent empty report.
* Analysis must not mutate the branch run dirs it reads (checksum test).
* ``analyze_experiment(manifest, path_resolver=None)`` — the default keeps the
  existing repo-root-relative behavior EXACTLY; a resolver lets SimTree supply
  absolute branch paths without copying runs into the repo.
* Ragged series: the existing PW semantics (average over whichever agents
  reported, ``None`` gaps, divergence skips absent steps, split requires a
  sustained crossing) are pinned so reuse cannot silently change them.
* Golden fixture: the API report must equal a direct PW analysis of the same
  manifest (ignoring identity/timestamps/output path).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.apps import routes, world_paths
from gaworld.parallel import analysis, runner

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "pw_compare_golden")


def _copy_fixture(repo: str, root_rel: str = "cmp/golden") -> None:
    for world in ("base", "treat"):
        src = os.path.join(FIXTURE, world, "state", "agent_state_history.csv")
        dst = os.path.join(repo, root_rel, world, "state", "agent_state_history.csv")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy(src, dst)


def _manifest(root_rel: str = "cmp/golden") -> dict:
    return {
        "id": "golden",
        "root": root_rel,
        "created_at": "2026-10-15 00:00:00",
        "spec": {
            "name": "golden",
            "seed": 1,
            "baseline_id": "base",
            "worlds": [
                {"id": "base", "label": "基准", "events": [], "config": {}},
                {"id": "treat", "label": "干预", "events": [], "config": {}},
            ],
        },
        "worlds": {
            "base": {
                "dir": f"{root_rel}/base",
                "state_csv": f"{root_rel}/base/state/agent_state_history.csv",
            },
            "treat": {
                "dir": f"{root_rel}/treat",
                "state_csv": f"{root_rel}/treat/state/agent_state_history.csv",
            },
        },
    }


def _tree_checksums(root: str) -> dict:
    """Checksum every file under ``root`` (source-integrity guard)."""
    found = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(dirpath, name)
            with open(path, "rb") as handle:
                found[os.path.relpath(path, root)] = hashlib.sha256(handle.read()).hexdigest()
    return found


class _TempRepo:
    """Swap ``world_paths.REPO_ROOT`` for a throwaway repo, as the PW tests do."""

    def __enter__(self):
        self.root = tempfile.mkdtemp(prefix="pw-compare-")
        self._saved = world_paths.REPO_ROOT
        world_paths.REPO_ROOT = self.root
        return self.root

    def __exit__(self, *exc):
        world_paths.REPO_ROOT = self._saved
        shutil.rmtree(self.root, ignore_errors=True)
        return False


def _post_compare(manifest: dict):
    """The single HTTP entry under test — routed like every other prefix API."""
    return routes.dispatch_post("/api/analysis/compare", {"manifest": manifest})


class CompareApiTests(unittest.TestCase):
    def test_valid_manifest_returns_report_and_writes_artifacts(self):
        with _TempRepo() as repo:
            _copy_fixture(repo)
            replied = _post_compare(_manifest())
            self.assertIsNotNone(
                replied, "POST /api/analysis/compare is not routed",
            )
            body, status = replied
            self.assertEqual(status, 200, body)
            self.assertIn("report", body)
            self.assertIn("artifacts_dir", body)
            report = body["report"]
            self.assertEqual(report["baseline_id"], "base")
            treat = next(w for w in report["worlds"] if w["id"] == "treat")
            self.assertTrue(treat["has_data"])

            artifacts = os.path.join(repo, "output", "comparisons")
            written = [
                name
                for name in os.listdir(artifacts)
                if os.path.isdir(os.path.join(artifacts, name))
            ]
            self.assertEqual(len(written), 1, written)
            out = os.path.join(artifacts, written[0])
            for name in ("report.json", "divergence_metrics.csv", "divergence_summary.md"):
                self.assertTrue(os.path.exists(os.path.join(out, name)), name)

    def test_invalid_manifest_is_a_client_error(self):
        with _TempRepo():
            bad = {"id": "x", "root": "x", "spec": {"baseline_id": "base", "worlds": []}, "worlds": {}}
            replied = _post_compare(bad)
            self.assertIsNotNone(replied, "POST /api/analysis/compare is not routed")
            _body, status = replied
            self.assertGreaterEqual(status, 400)
            self.assertLess(status, 500)

    def test_missing_state_csv_is_a_clear_error(self):
        with _TempRepo() as repo:
            _copy_fixture(repo)
            os.remove(
                os.path.join(repo, "cmp/golden/treat/state/agent_state_history.csv")
            )
            body, status = _post_compare(_manifest())
            self.assertGreaterEqual(status, 400)
            self.assertLess(status, 500)
            # The error must name the offending world, not vanish into an
            # empty-looking report.
            self.assertIn("treat", json.dumps(body, ensure_ascii=False))

    def test_path_traversal_in_state_csv_is_rejected(self):
        with _TempRepo() as repo:
            _copy_fixture(repo)
            manifest = _manifest("cmp/golden")
            manifest["worlds"]["treat"]["state_csv"] = "../../etc/passwd"
            body, status = _post_compare(manifest)
            self.assertGreaterEqual(status, 400, body)

    def test_absolute_path_outside_root_is_rejected(self):
        with _TempRepo():
            manifest = _manifest("cmp/golden")
            manifest["worlds"]["treat"]["state_csv"] = "/tmp/evil/state.csv"
            body, status = _post_compare(manifest)
            self.assertGreaterEqual(status, 400, body)

    def test_symlink_escape_is_rejected(self):
        with _TempRepo() as repo:
            _copy_fixture(repo)
            outside = tempfile.mkdtemp(prefix="pw-outside-")
            try:
                victim = os.path.join(outside, "secret.csv")
                with open(victim, "w", encoding="utf-8") as handle:
                    handle.write("agent_id,step,metric,value\n1,0,emotion,1.0\n")
                link_dir = os.path.join(repo, "cmp/golden/link")
                os.symlink(outside, link_dir)
                manifest = _manifest("cmp/golden")
                manifest["worlds"]["treat"]["state_csv"] = "cmp/golden/link/secret.csv"
                body, status = _post_compare(manifest)
                self.assertGreaterEqual(status, 400, body)
            finally:
                shutil.rmtree(outside, ignore_errors=True)

    def test_analysis_does_not_mutate_source_branch_dirs(self):
        with _TempRepo() as repo:
            _copy_fixture(repo)
            branch_root = os.path.join(repo, "cmp/golden")
            before = _tree_checksums(branch_root)
            body, _status = _post_compare(_manifest())
            self.assertIsNotNone(body)
            self.assertEqual(_tree_checksums(branch_root), before)


class AnalyzerResolverTests(unittest.TestCase):
    """``analyze_experiment`` gains an optional ``path_resolver``; the default
    is a regression lock on the existing repo-root-relative behavior."""

    def _with_fixture_repo(self):
        return _TempRepo()

    def test_default_resolver_preserves_existing_behavior(self):
        with self._with_fixture_repo() as repo:
            _copy_fixture(repo)
            report = runner.analyze_experiment(repo, _manifest())
            treat = next(w for w in report["worlds"] if w["id"] == "treat")
            self.assertTrue(treat["has_data"])
            self.assertEqual(treat["split_step"], 3)

    def test_path_resolver_keyword_is_accepted_and_used(self):
        with self._with_fixture_repo() as repo:
            _copy_fixture(repo)

            def resolver(entry: dict, repo_root: str) -> dict:
                resolved = dict(entry)
                resolved["state_csv"] = os.path.join(repo_root, entry["state_csv"])
                resolved["dir"] = os.path.join(repo_root, entry["dir"])
                return resolved

            report = runner.analyze_experiment(
                "<must-not-be-joined>", _manifest(), path_resolver=resolver
            )
            treat = next(w for w in report["worlds"] if w["id"] == "treat")
            self.assertTrue(treat["has_data"])
            self.assertEqual(treat["split_step"], 3)


class RaggedSeriesGuardTests(unittest.TestCase):
    """Pin the existing ragged/unequal-length semantics before reuse."""

    def _write(self, path: str, agents, steps):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        import csv

        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["agent_id", "step", "metric", "value"])
            for agent in agents:
                for step in range(steps):
                    writer.writerow([agent, step, "emotion", 0.5])

    def test_shorter_world_reported_not_dropped_and_steps_do_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "base.csv")
            short = os.path.join(tmp, "short.csv")
            self._write(base, (1, 2), 6)
            self._write(short, (1, 2), 3)
            manifest = _manifest()
            manifest["spec"]["worlds"][1]["id"] = "short"
            series = {
                "base": analysis.read_state_series(base),
                "short": analysis.read_state_series(short),
            }
            report = analysis.build_report(manifest, series)
            self.assertEqual(report["steps"], 6)
            short_world = next(w for w in report["worlds"] if w["id"] == "short")
            self.assertTrue(short_world["has_data"])
            self.assertEqual(short_world["steps"], 3)
            # The divergence curve for the short world only covers its own
            # steps; the rest is None (gap), never zero.
            curve = report["divergence"]["short"]
            self.assertEqual(len(curve), 6)
            self.assertIsNone(curve[5])

    def test_split_requires_a_sustained_crossing(self):
        # One tick above threshold is noise; three in a row is a split.
        curve = [0.5, 0.0, 0.5, 0.0]
        self.assertIsNone(analysis._split_step(curve, 0.02))
        self.assertEqual(analysis._split_step([0.0, 0.5, 0.5, 0.5], 0.02), 1)


class GoldenFixtureTests(unittest.TestCase):
    """Known-by-construction divergence: direct PW analysis == compare API."""

    def test_direct_analysis_matches_known_numbers(self):
        with _TempRepo() as repo:
            _copy_fixture(repo)
            report = runner.analyze_experiment(repo, _manifest())
            treat = next(w for w in report["worlds"] if w["id"] == "treat")
            self.assertEqual(treat["split_step"], 3)
            self.assertAlmostEqual(treat["divergence_final"], 0.1125, places=6)
            deltas = {(d["metric"]): d for d in report["deltas"]}
            self.assertAlmostEqual(deltas["emotion"]["delta_final"], 0.15, places=6)
            self.assertAlmostEqual(deltas["stress"]["delta_final"], 0.075, places=6)
            movers = report["movers"]["treat"]
            # Agent 2 carries the real shift; agent 1 is listed with distance 0.
            self.assertEqual(movers[0]["agent_id"], "2")
            self.assertAlmostEqual(movers[0]["top_delta"], 0.3, places=6)
            self.assertAlmostEqual(movers[0]["distance"], 0.225, places=6)

    def test_api_report_equals_direct_analysis(self):
        with _TempRepo() as repo:
            _copy_fixture(repo)
            direct = runner.analyze_experiment(repo, _manifest())
            replied = _post_compare(_manifest())
            self.assertIsNotNone(replied, "POST /api/analysis/compare is not routed")
            body, status = replied
            self.assertEqual(status, 200, body)
            api_report = body["report"]
            for key in ("id", "created_at", "root", "experiment_id", "summary"):
                direct.pop(key, None)
                api_report.pop(key, None)
            self.assertEqual(
                json.dumps(direct, sort_keys=True, default=str),
                json.dumps(api_report, sort_keys=True, default=str),
            )


if __name__ == "__main__":
    unittest.main()
