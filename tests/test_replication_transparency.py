"""Tests for the reproducibility surface of 社会调查/实验拟合度.

What we defend:

* the generation parameters (temperature, max tokens) are visible, adjustable
  and checked — a temperature that never reached the model would be worse than
  one that is refused;
* a run records the model that answered, its endpoint and config fingerprints,
  and the parameters it was asked with;
* every model call is logged and can be joined to the resident who asked;
* the exported data package holds the raw material — the answers, the personas,
  the call log, the charts — not only the summary.

No LLM is reached and no city bundle is read.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import re
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from gaworld.apps import replication_api, research_api
from gaworld.research import model_provenance as mp
from gaworld.research import replication as rp

PEOPLE = [
    {
        "id": i,
        "name": f"居民{i}",
        "age": age,
        "gender": "女" if i % 2 else "男",
        "hukou": "本地",
        "job": "职员",
        "education": "本科",
    }
    for i, age in enumerate([25, 30, 45, 50, 70, 68, 12, 38, 41, 22, 33, 59], start=1)
]

RAW_SPEC = {
    "title": "框架效应",
    "kind": "experiment",
    "population": "美国成年人",
    "conditions": [
        {"id": "C1", "label": "收益框架", "stimulus": "可以救 200 人"},
        {"id": "C2", "label": "损失框架", "stimulus": "会死 400 人"},
    ],
    "items": [
        {"id": "Q1", "text": "你支持方案 A 吗", "kind": "scale", "min": 1, "max": 7},
        {"id": "Q2", "text": "选哪个方案", "kind": "choice", "options": ["方案A", "方案B"]},
    ],
    "results": [
        {"item": "Q1", "condition": "C1", "mean": 5.0, "sd": 1.0, "n": 50, "source": "表1"},
        {"item": "Q1", "condition": "C2", "mean": 3.0, "sd": 1.0, "n": 50, "source": "表1"},
        {"item": "Q2", "condition": "C1", "distribution": {"方案A": 72}, "n": 50},
        {"item": "Q2", "condition": "C2", "distribution": {"方案A": 22, "方案B": 78}, "n": 50},
    ],
}


def framed_answer(prompt: str) -> str:
    """Gain frame: support 5, pick A; loss frame: support 3, pick B."""
    gain = "可以救 200 人" in prompt
    return json.dumps({"Q1": 5 if gain else 3, "Q2": 1 if gain else 2})


def extract_llm(prompt: str) -> str:
    return "好的：\n```json\n" + json.dumps(RAW_SPEC, ensure_ascii=False) + "\n```"


class GenerationParameterTest(unittest.TestCase):
    """The parameters are part of the protocol, so they are checked."""

    def test_defaults_are_filled_in_for_every_stage(self) -> None:
        defaults = {
            "extract": {"temperature": 0.1, "max_tokens": 6000},
            "answer": {"temperature": 0.9, "max_tokens": 2000},
        }
        out = mp.normalize_generation(None, defaults)
        self.assertEqual(out["extract"], {"temperature": 0.1, "max_tokens": 6000})
        self.assertEqual(out["answer"], {"temperature": 0.9, "max_tokens": 2000})
        # A stage nobody asked about is not invented: only the stages the
        # caller knows about come back.
        self.assertNotIn("interpret", out)

    def test_the_api_knows_all_three_stages(self) -> None:
        self.assertEqual(sorted(replication_api.GENERATION_DEFAULTS), ["answer", "extract", "interpret"])

    def test_a_value_out_of_range_is_refused_not_ignored(self) -> None:
        defaults = {"answer": {"temperature": 0.9, "max_tokens": 2000}}
        with self.assertRaises(mp.GenerationError):
            mp.normalize_generation({"answer": {"temperature": 9}}, defaults)
        with self.assertRaises(mp.GenerationError):
            mp.normalize_generation({"answer": {"max_tokens": 5}}, defaults)
        with self.assertRaises(mp.GenerationError):
            mp.normalize_generation({"answer": {"temperature": "热"}}, defaults)

    def test_a_value_in_range_is_kept_as_asked(self) -> None:
        defaults = {"answer": {"temperature": 0.9, "max_tokens": 2000}}
        out = mp.normalize_generation({"answer": {"temperature": 0.2, "max_tokens": 512}}, defaults)
        self.assertEqual(out["answer"], {"temperature": 0.2, "max_tokens": 512})


class CallJournalTest(unittest.TestCase):
    def test_entries_are_numbered_in_order(self) -> None:
        journal = mp.CallJournal()
        for _index in range(3):
            journal.record(task="answer", ok=True)
        self.assertEqual([entry["seq"] for entry in journal.entries()], [1, 2, 3])

    def test_a_call_is_joined_to_the_resident_who_asked(self) -> None:
        run = {
            "responses": [
                {
                    "agent_id": 7,
                    "condition": "C1",
                    "prompt_hash": "hash-main",
                    "probes": {"stability": {"prompt_hash": "hash-probe"}},
                }
            ]
        }
        linked = mp.link_calls(
            [
                {"seq": 1, "prompt_hash": "hash-main"},
                {"seq": 2, "prompt_hash": "hash-probe"},
                {"seq": 3, "prompt_hash": "hash-unknown"},
            ],
            run,
        )
        self.assertEqual((linked[0]["agent_id"], linked[0]["variant"]), (7, "main"))
        self.assertEqual((linked[1]["agent_id"], linked[1]["variant"]), (7, "stability"))
        self.assertIsNone(linked[2]["agent_id"])


class Harness:
    """The HTTP harness: no model is reached and no city bundle is read."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        replication_api.reset()

        def llm(prompt: str, task: str, provider: str) -> str:
            if task == "interpret":
                return json.dumps({"summary": "读完了", "findings": []}, ensure_ascii=False)
            return extract_llm(prompt) if task == "extract" else framed_answer(prompt)

        for target in (
            mock.patch.object(rp, "replication_root", return_value=Path(self.tmp.name)),
            mock.patch.object(replication_api, "_LLM_OVERRIDE", llm),
            mock.patch("gaworld.interview.roster.load_population", return_value=PEOPLE),
            mock.patch("gaworld.interview.roster.profile_block", return_value=""),
        ):
            target.start()
            self.addCleanup(target.stop)

    def _wait(self, job_id: str) -> dict:
        for _ in range(200):
            record, status = research_api.handle_get(f"/api/research/replication/jobs/{job_id}")
            self.assertEqual(status, 200)
            if record["status"] != "running":
                self.assertEqual(record["status"], "done", record.get("error"))
                return record["result"]
            time.sleep(0.02)
        self.fail("job did not finish")

    def _run(self, payload: dict | None = None) -> dict:
        body, status = research_api.handle_post(
            "/api/research/replication/run",
            {"spec": RAW_SPEC, "sample_size": 6, "seed": 2, **(payload or {})},
        )
        self.assertEqual(status, 202)
        return self._wait(body["job_id"])


class HttpTest(Harness, unittest.TestCase):
    def test_the_listing_says_what_may_be_set_and_which_model_would_answer(self) -> None:
        listing, status = research_api.handle_get("/api/research/replication")
        self.assertEqual(status, 200)
        self.assertIn("answer", listing["generation"])
        self.assertEqual(listing["generation"]["answer"]["temperature"], 0.9)
        self.assertIn("providers", listing)
        self.assertIn("stage_labels", listing)

    def test_a_run_records_the_parameters_it_used(self) -> None:
        run = self._run(
            {
                "generation": {
                    "answer": {"temperature": 0.35, "max_tokens": 700},
                    "extract": {"temperature": 0.05, "max_tokens": 4000},
                }
            }
        )
        record, _ = research_api.handle_get(f"/api/research/replication/{run['run_id']}")
        self.assertEqual(record["generation"]["answer"], {"temperature": 0.35, "max_tokens": 700})
        self.assertEqual(record["generation"]["extract"], {"temperature": 0.05, "max_tokens": 4000})
        # The stage that was not asked for still gets its default, so the record
        # says what every stage would have used.
        self.assertEqual(record["generation"]["interpret"]["temperature"], 0.3)

    def test_a_run_without_parameters_uses_the_defaults(self) -> None:
        run = self._run()
        record, _ = research_api.handle_get(f"/api/research/replication/{run['run_id']}")
        self.assertEqual(record["generation"]["answer"]["temperature"], 0.9)

    def test_an_impossible_parameter_is_refused_with_a_reason(self) -> None:
        body, status = research_api.handle_post(
            "/api/research/replication/run",
            {"spec": RAW_SPEC, "generation": {"answer": {"temperature": 12}}},
        )
        self.assertEqual(status, 400)
        self.assertIn("温度", body["error"])

    def test_the_run_records_which_model_read_the_paper_too(self) -> None:
        run = self._run({"extraction_model": {"provider": "reader", "model": "reader-1"}})
        record, _ = research_api.handle_get(f"/api/research/replication/{run['run_id']}")
        self.assertEqual(record["extraction_model"]["model"], "reader-1")

    def test_the_reading_is_on_the_call_log_as_well(self) -> None:
        run = self._run()
        record, _ = research_api.handle_get(f"/api/research/replication/{run['run_id']}")
        tasks = {call["task"] for call in record["model_calls"]}
        self.assertIn("research.replication.answer", tasks)
        self.assertIn("research.replication.interpret", tasks)

    def test_the_run_records_the_model_and_its_fingerprints(self) -> None:
        run = self._run()
        record, _ = research_api.handle_get(f"/api/research/replication/{run['run_id']}")
        self.assertEqual(record["model"]["kind"], "injected")
        self.assertIn("temperature", record["model"])
        # The check protocol keeps the model version next to the seed.
        self.assertEqual(record["check_protocol"]["model"]["provider"], record["model"]["provider"])

    def test_every_model_call_is_logged_and_joined_to_its_resident(self) -> None:
        run = self._run()
        record, _ = research_api.handle_get(f"/api/research/replication/{run['run_id']}")
        calls = record["model_calls"]
        answers = [call for call in calls if call["task"].endswith("answer")]
        self.assertEqual(len(answers), len(record["responses"]))
        self.assertTrue(all(call["ok"] for call in calls))
        self.assertTrue(all(call["agent_id"] for call in answers))
        self.assertTrue(all(call["condition"] for call in answers))
        hashes = {call["prompt_hash"] for call in answers}
        self.assertTrue(hashes <= {response["prompt_hash"] for response in record["responses"]})

    def test_a_failed_call_is_logged_as_failed(self) -> None:
        def broken(prompt: str, task: str, provider: str) -> str:
            raise TimeoutError("provider down")

        with mock.patch.object(replication_api, "_LLM_OVERRIDE", broken):
            run = self._run()
        record, _ = research_api.handle_get(f"/api/research/replication/{run['run_id']}")
        self.assertTrue(record["model_calls"])
        self.assertFalse(any(call["ok"] for call in record["model_calls"]))
        self.assertIn("provider down", record["model_calls"][0]["error"])


class DataPackageTest(Harness, unittest.TestCase):
    """The package holds the raw material, not only the summary."""

    def _bundle(self) -> tuple[dict, zipfile.ZipFile]:
        run = self._run()
        body, status = research_api.handle_get(f"/api/research/replication/{run['run_id']}/bundle")
        self.assertEqual(status, 200)
        archive = zipfile.ZipFile(io.BytesIO(base64.b64decode(body["bytes_base64"])))
        return body, archive

    def test_the_package_has_the_parts_a_reader_needs(self) -> None:
        body, archive = self._bundle()
        names = set(archive.namelist())
        for expected in (
            "README.md",
            "manifest.json",
            "summary.md",
            "spec.json",
            "responses.csv",
            "raw_answers.json",
            "personas.csv",
            "model_calls.csv",
            "checks.json",
            "distributions.html",
        ):
            self.assertIn(expected, names)
        self.assertTrue(body["filename"].endswith("-data.zip"))

    def test_the_manifest_checksums_match_the_files(self) -> None:
        _body, archive = self._bundle()
        manifest = json.loads(archive.read("manifest.json"))
        import hashlib

        for entry in manifest["files"]:
            data = archive.read(entry["name"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry["sha256"], entry["name"])
            self.assertEqual(len(data), entry["bytes"])

    def test_the_manifest_carries_the_model_the_parameters_and_the_scope(self) -> None:
        _body, archive = self._bundle()
        manifest = json.loads(archive.read("manifest.json"))
        self.assertIn("provider", manifest["model"])
        self.assertIn("answer", manifest["generation"])
        self.assertEqual(manifest["generation"]["answer"]["temperature"], 0.9)
        self.assertEqual(manifest["score"]["score"], manifest["score"]["score"])
        self.assertIn("cells_possible", manifest["score"]["coverage"])

    def test_the_answers_are_there_row_by_row(self) -> None:
        _body, archive = self._bundle()
        rows = list(csv.DictReader(io.StringIO(archive.read("responses.csv").decode("utf-8-sig"))))
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row["name"] for row in rows))
        self.assertTrue(all(row["answers"] for row in rows))
        self.assertIn("Q1", rows[0]["answers"])

    def test_the_residents_carry_the_card_the_model_saw(self) -> None:
        _body, archive = self._bundle()
        rows = list(csv.DictReader(io.StringIO(archive.read("personas.csv").decode("utf-8-sig"))))
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row["education"] == "本科" for row in rows))

    def test_the_call_log_is_in_the_package(self) -> None:
        _body, archive = self._bundle()
        rows = list(csv.DictReader(io.StringIO(archive.read("model_calls.csv").decode("utf-8-sig"))))
        # One row per answer, plus the reading of the deviations.
        self.assertEqual(len(rows), 7)
        self.assertTrue(all(row["model"] for row in rows))
        self.assertTrue(all(row["temperature"] for row in rows))
        self.assertTrue(any(row["task"].endswith("interpret") for row in rows))

    def test_the_charts_are_svg_a_browser_can_open(self) -> None:
        _body, archive = self._bundle()
        page = archive.read("distributions.html").decode("utf-8")
        self.assertIn("<svg", page)
        self.assertIn("真人均值", page)
        self.assertEqual(page.count("<figure"), 4)  # two questions × two conditions


class SurveyScrollTest(unittest.TestCase):
    """The interview history scrolls on its own instead of pushing the page."""

    def setUp(self) -> None:
        self.css = Path("site/dashboard/survey.css").read_text(encoding="utf-8")
        self.js = Path("site/dashboard/survey.js").read_text(encoding="utf-8")

    def test_the_history_list_has_its_own_scroll(self) -> None:
        rule = re.search(r"\.sv-history\s*\{([^}]*)\}", self.css)
        self.assertIsNotNone(rule)
        self.assertIn("max-height", rule.group(1))
        self.assertIn("overflow-y: auto", rule.group(1))

    def test_the_sticky_rail_is_capped_to_the_window(self) -> None:
        rule = re.search(r"\.sv-side\s*\{([^}]*)\}", self.css)
        self.assertIsNotNone(rule)
        self.assertIn("max-height", rule.group(1))
        self.assertIn("overflow-y: auto", rule.group(1))

    def test_the_history_is_not_cut_to_a_handful_of_sessions(self) -> None:
        self.assertNotIn("state.history.slice(0, 8)", self.js)
        self.assertIn("state.history.map", self.js)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
