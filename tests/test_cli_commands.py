"""CLI subcommands that had no coverage: ``reset``, ``rag-add`` and ``interview``.

Each test drives ``generative_city_sim._main`` with a stubbed parser result, so
the dispatch in ``_main`` is exercised, while the storage it would touch is
patched out or pointed at a temporary directory.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import generative_city_sim as sim


def _run_main(args):
    with patch.object(sim, "_build_arg_parser") as build_parser:
        build_parser.return_value.parse_args.return_value = args
        sim._main()
        return build_parser.return_value


class TestResetCommand(unittest.TestCase):
    def test_reset_clears_every_stateful_dir_and_rewinds_the_calendar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vector_db = os.path.join(tmp, "vectors.db")
            with open(vector_db, "w", encoding="utf-8") as fh:
                fh.write("x")
            config = dict(sim.CONFIG)
            config.update(
                memory_dir=os.path.join(tmp, "memory"),
                log_dir=os.path.join(tmp, "logs"),
                vector_db_path=vector_db,
            )
            with (
                patch.object(sim, "CONFIG", config),
                patch.object(sim, "_clear_dir") as clear_dir,
                patch.object(sim, "save_sim_state") as save_state,
            ):
                _run_main(SimpleNamespace(command="reset"))

            cleared = {call.args[0] for call in clear_dir.call_args_list}
            self.assertIn(config["memory_dir"], cleared)
            self.assertIn(config["log_dir"], cleared)
            self.assertIn(sim.STATE_OUTPUT_DIR, cleared)
            self.assertIn(sim.ENV_OUTPUT_DIR, cleared)
            self.assertFalse(os.path.exists(vector_db))

            state = save_state.call_args.args[0]
            self.assertEqual(0, state["last_day"])
            self.assertEqual({}, state["agent_last_day"])
            self.assertEqual(sim.MEMORY_MODEL_VERSION, state["memory_model_version"])


class TestRagAddCommand(unittest.TestCase):
    def test_rag_add_writes_the_text_to_vector_db_and_memory(self) -> None:
        memory = ["earlier note"]
        with (
            patch.object(sim, "vector_db_add_entry") as add_entry,
            patch.object(sim, "load_agent_memory", return_value=list(memory)),
            patch.object(sim, "save_agent_memory") as save_memory,
        ):
            _run_main(
                SimpleNamespace(
                    command="rag-add",
                    agent_id=7,
                    text="地铁三号线下周停运",
                    timestamp="2026-02-18 09:30",
                    source="unit-test",
                )
            )

        agent_id, entry_type, payload = add_entry.call_args.args
        self.assertEqual((7, "external_info"), (agent_id, entry_type))
        self.assertIn("地铁三号线下周停运", payload)
        saved = save_memory.call_args.args[0]
        self.assertEqual(7, saved["id"])
        self.assertEqual(["earlier note", payload], saved["memory"])

    def test_rag_add_refuses_blank_text(self) -> None:
        with (
            patch.object(sim, "vector_db_add_entry") as add_entry,
            patch.object(sim, "save_agent_memory") as save_memory,
        ):
            with self.assertRaises(ValueError):
                _run_main(
                    SimpleNamespace(command="rag-add", agent_id=7, text="   ", timestamp=None, source="cli")
                )
        add_entry.assert_not_called()
        save_memory.assert_not_called()


class TestInterviewCommand(unittest.TestCase):
    def test_questions_from_flags_and_file_are_merged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            qfile = os.path.join(tmp, "q.txt")
            with open(qfile, "w", encoding="utf-8") as fh:
                fh.write("你最近压力大吗？\n\n周末一般做什么？\n")
            with patch.object(sim, "_cli_interview_agent") as interview:
                _run_main(
                    SimpleNamespace(
                        command="interview",
                        agent_id=31,
                        questions=["你住在哪里？"],
                        questions_file=qfile,
                        context=None,
                    )
                )

        agent_id, questions = interview.call_args.args
        self.assertEqual(31, agent_id)
        self.assertEqual(["你住在哪里？", "你最近压力大吗？", "周末一般做什么？"], questions)

    def test_no_question_is_a_usage_error(self) -> None:
        with (
            patch.object(sim, "_cli_interview_agent") as interview,
            patch.object(sim, "_build_arg_parser") as build_parser,
        ):
            parser = build_parser.return_value
            parser.parse_args.return_value = SimpleNamespace(
                command="interview", agent_id=31, questions=None, questions_file=None, context=None
            )
            parser.error.side_effect = SystemExit(2)
            with self.assertRaises(SystemExit):
                sim._main()
        interview.assert_not_called()


class TestArgParser(unittest.TestCase):
    def test_every_documented_subcommand_parses(self) -> None:
        parser = sim._build_arg_parser()
        cases = [
            ["run", "--sim-days", "2"],
            ["run", "--sim-years", "10"],
            ["run", "--sim-months", "24", "--time-unit", "month"],
            ["run", "--sim-days", "600", "--fast-forward"],
            ["reset"],
            ["interview", "--agent-id", "31", "--question", "Q"],
            ["rag-add", "--agent-id", "31", "--text", "T"],
            ["create-agent-from-social", "--text", "T"],
            ["serve-viz", "--port", "8000"],
            ["dashboard", "--port", "8766"],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                self.assertEqual(argv[0], parser.parse_args(argv).command)

    def test_unknown_time_unit_is_rejected(self) -> None:
        parser = sim._build_arg_parser()
        with patch("sys.stderr"), self.assertRaises(SystemExit):
            parser.parse_args(["run", "--time-unit", "week"])


if __name__ == "__main__":
    unittest.main()
