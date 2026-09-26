"""Tests for :mod:`gaworld.core.run_manifest` and :mod:`gaworld.core.run_report`.

These tests deliberately avoid touching git / network / the wider
simulator: the manifest builder must be usable and testable in
isolation.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from gaworld.core.run_manifest import (
    SCHEMA_VERSION,
    ManifestBuilder,
    load_manifest,
    start_manifest,
)
from gaworld.core.run_report import render_report
from gaworld.llm.stats import LLMCallStats


CONFIG = {
    "agent_ids": [1, 2, 3],
    "sim_days": 2,
    "seconds_per_day": 5,
    "stateful": False,
    "random_seed": 42,
    "run_manifest": {"enabled": True, "output_dir": "output/run_manifests", "html_report": True},
    "concurrency": {"enabled": True, "day_routine_workers": 4},
    "human_realism": {"enabled": True},
    "llm": {
        "providers": {
            "p1": {
                "type": "ollama",
                "model": "qwen3.5",
                "url": "http://localhost:11434",
                # A shape that used to end up verbatim in the manifest;
                # the redaction test below asserts this never appears.
                "api_key": "super-secret",
            }
        },
        "routing": {"default": "p1", "fallback": ["p1"], "tasks": {"schedule": "p1"}},
    },
}


class TestManifestBuilder(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.orig_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self.orig_cwd)

    def test_shape_and_schema_version(self):
        builder = start_manifest(config=CONFIG)
        path = builder.finalise(outcome="ok")
        m = load_manifest(path)
        self.assertEqual(SCHEMA_VERSION, m["schema_version"])
        for key in (
            "run_id", "slug", "started_at", "finished_at", "duration_s",
            "outcome", "environment", "git", "dependencies", "config",
            "run", "llm", "artefacts", "notes", "events",
        ):
            self.assertIn(key, m, f"missing key: {key}")
        self.assertEqual("ok", m["outcome"])
        self.assertEqual(2, m["run"]["sim_days"])
        self.assertEqual([1, 2, 3], m["run"]["agent_ids"])
        self.assertEqual(42, m["run"]["random_seed"])

    def test_api_keys_are_redacted(self):
        builder = start_manifest(config=CONFIG)
        path = builder.finalise(outcome="ok")
        with open(path, encoding="utf-8") as fh:
            blob = fh.read()
        self.assertNotIn("super-secret", blob,
                         "api_key leaked into manifest JSON")
        m = load_manifest(path)
        # But the provider name and model must still be there.
        self.assertIn("p1", m["config"]["llm"]["providers"])
        self.assertEqual("qwen3.5", m["config"]["llm"]["providers"]["p1"]["model"])

    def test_llm_stats_folded_in(self):
        stats = LLMCallStats()
        stats.record(task="schedule", provider="p1", latency_ms=120, ok=True)
        stats.record(task="schedule", provider="p1", latency_ms=90, ok=False)
        stats.record(task="planning", provider="p1", latency_ms=200, ok=True)
        builder = start_manifest(config=CONFIG)
        builder.bind_llm_stats(stats)
        path = builder.finalise(outcome="ok")
        m = load_manifest(path)
        llm = m["llm"]
        self.assertEqual(3, llm["call_count"])
        self.assertEqual(1, llm["failure_count"])
        self.assertEqual(2, llm["by_task"]["schedule"]["calls"])
        self.assertEqual(1, llm["by_task"]["schedule"]["failures"])
        self.assertEqual(1, llm["by_task"]["planning"]["calls"])
        self.assertEqual(3, llm["by_provider"]["p1"]["calls"])

    def test_partial_written_at_start_and_cleaned_on_success(self):
        builder = start_manifest(config=CONFIG)
        listing_before = os.listdir(builder.manifest_dir)
        self.assertTrue(any(n.endswith(".partial.json") for n in listing_before),
                        f"expected .partial.json in {listing_before}")
        builder.finalise(outcome="ok")
        listing_after = os.listdir(builder.manifest_dir)
        self.assertFalse(any(n.endswith(".partial.json") for n in listing_after),
                         f"partial not cleaned: {listing_after}")

    def test_partial_survives_when_finalise_skipped(self):
        # Simulate a crash: we never call finalise().
        builder = start_manifest(config=CONFIG)
        listing = os.listdir(builder.manifest_dir)
        self.assertTrue(any(n.endswith(".partial.json") for n in listing))

    def test_events_and_notes(self):
        builder = start_manifest(config=CONFIG)
        builder.event("day_end", day=1, agents=3)
        builder.event("day_end", day=2, agents=3)
        builder.note("first smoke test")
        m = load_manifest(builder.finalise(outcome="ok"))
        self.assertEqual(2, len(m["events"]))
        self.assertEqual("day_end", m["events"][0]["kind"])
        self.assertEqual(1, m["events"][0]["payload"]["day"])
        self.assertEqual(["first smoke test"], m["notes"])

    def test_manifest_does_not_crash_on_missing_git(self):
        # We are in a tempdir with no .git — _git_info must return {}
        # without exploding.
        builder = start_manifest(config=CONFIG)
        m = load_manifest(builder.finalise(outcome="ok"))
        self.assertIsInstance(m["git"], dict)  # {} or populated

    def test_bind_stats_error_is_survived(self):
        class Bomb:
            def snapshot(self):
                raise RuntimeError("boom")

        builder = start_manifest(config=CONFIG)
        builder.bind_llm_stats(Bomb())
        # Must not raise.
        path = builder.finalise(outcome="ok")
        m = load_manifest(path)
        self.assertIn("error", m["llm"])


class TestRunReport(unittest.TestCase):
    def _sample_manifest(self, **overrides):
        m = {
            "schema_version": 1,
            "run_id": "deadbeef",
            "slug": "20260101_120000",
            "started_at": "2026-01-01T12:00:00+00:00",
            "finished_at": "2026-01-01T12:05:00+00:00",
            "duration_s": 300.0,
            "outcome": "ok",
            "error": "",
            "environment": {"python": "3.12.0", "platform": "Linux-6.8", "hostname": "ci"},
            "git": {"commit": "abcdef1234567890", "branch": "main", "dirty": False},
            "dependencies": {"pandas": "2.0.3", "numpy": "1.26.4"},
            "config": {
                "agent_ids": [1, 2],
                "sim_days": 2,
                "concurrency": {"enabled": False, "day_routine_workers": 1},
                "llm": {
                    "providers": {"p1": {"type": "ollama", "model": "qwen", "base_url": ""}},
                    "routing": {"default": "p1", "fallback": [], "tasks": {}},
                },
            },
            "run": {"sim_days": 2, "agent_ids": [1, 2], "random_seed": 7, "stateful": False},
            "llm": {
                "call_count": 12,
                "failure_count": 1,
                "by_task": {
                    "schedule": {"calls": 5, "failures": 0, "total_latency_ms": 500},
                    "planning": {"calls": 7, "failures": 1, "total_latency_ms": 1400},
                },
                "by_provider": {"p1": {"calls": 12, "failures": 1, "total_latency_ms": 1900}},
            },
            "artefacts": {
                "output/logs": [
                    {"path": "output/logs/agent_1.log", "size": 4096, "mtime": 0},
                    {"path": "output/logs/agent_2.log", "size": 2048, "mtime": 0},
                ]
            },
            "notes": ["ran during CI"],
            "events": [{"ts": "2026-01-01T12:03:00+00:00", "kind": "day_end", "payload": {"day": 1}}],
        }
        m.update(overrides)
        return m

    def test_renders_valid_html(self):
        html = render_report(self._sample_manifest())
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn("<title>", html)
        self.assertIn("</html>", html)
        # Key sections present.
        for needle in ("LLM", "Artefacts", "python", "agents = 2", "sim_days = 2",
                       "abcdef123456", "qwen", "12"):
            self.assertIn(needle, html, f"missing in HTML: {needle}")

    def test_dirty_git_is_flagged(self):
        m = self._sample_manifest()
        m["git"]["dirty"] = True
        html = render_report(m)
        self.assertIn("dirty", html)

    def test_failed_outcome_uses_red_badge(self):
        m = self._sample_manifest(outcome="failed")
        html = render_report(m)
        self.assertIn("failed", html)
        self.assertIn("#b32424", html)

    def test_html_escapes_hostile_config(self):
        m = self._sample_manifest()
        m["environment"]["hostname"] = "<script>bad</script>"
        html = render_report(m)
        self.assertNotIn("<script>bad</script>", html)
        self.assertIn("&lt;script&gt;bad&lt;/script&gt;", html)


class TestStartManifestConfigKnobs(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.orig_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self.orig_cwd)

    def test_output_dir_from_config(self):
        cfg = dict(CONFIG)
        cfg["run_manifest"] = {"enabled": True, "output_dir": "custom/dir"}
        b = start_manifest(config=cfg)
        self.assertEqual("custom/dir", b.manifest_dir)

    def test_partial_write_disabled(self):
        cfg = dict(CONFIG)
        cfg["run_manifest"] = {"enabled": True, "output_dir": "out2", "partial_write": False}
        b = start_manifest(config=cfg)
        self.assertFalse(os.path.exists(os.path.join("out2", f"{b.slug}.partial.json")))


class TestLLMStats(unittest.TestCase):
    def test_snapshot_counts(self):
        s = LLMCallStats()
        s.record(task="a", provider="p", latency_ms=100, ok=True)
        s.record(task="a", provider="p", latency_ms=200, ok=True)
        s.record(task="b", provider="q", latency_ms=50, ok=False)
        snap = s.snapshot()
        self.assertEqual(3, snap["call_count"])
        self.assertEqual(1, snap["failure_count"])
        self.assertEqual(350, snap["total_latency_ms"])
        self.assertEqual(116, snap["avg_latency_ms"])
        self.assertEqual({"calls": 2, "failures": 0, "total_latency_ms": 300}, snap["by_task"]["a"])
        self.assertEqual({"calls": 1, "failures": 1, "total_latency_ms": 50}, snap["by_task"]["b"])
        self.assertEqual({"calls": 2, "failures": 0, "total_latency_ms": 300}, snap["by_provider"]["p"])

    def test_mark_run_start_isolates_run(self):
        s = LLMCallStats()
        s.record(task="warmup", provider="p", latency_ms=10, ok=True)
        s.mark_run_start()
        s.record(task="run", provider="p", latency_ms=20, ok=True)
        snap = s.snapshot()
        self.assertEqual(2, snap["call_count"])       # includes warmup
        self.assertEqual(1, snap["calls_in_run"])     # since mark

    def test_reset(self):
        s = LLMCallStats()
        s.record(task="a", provider="p", latency_ms=10, ok=True)
        s.reset()
        self.assertEqual(0, s.snapshot()["call_count"])
        self.assertEqual({}, s.snapshot()["by_task"])


class TestBuilderNeverCrashes(unittest.TestCase):
    def test_builder_accepts_non_mapping_config(self):
        # start_manifest coerces cfg to a dict; make sure ManifestBuilder
        # doesn't die if someone hands it something oddly shaped.
        b = ManifestBuilder(repo_root=".", manifest_dir=tempfile.mkdtemp(), config={})
        m = b.build(outcome="ok")
        self.assertEqual({}, m["config"])


if __name__ == "__main__":
    unittest.main()
