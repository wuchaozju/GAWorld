"""The 运行输出 panel: show the whole log, and let it leave as Markdown.

The panel used to render whatever ``/api/run/status`` handed it, and status only
ever carried the last 16 KB of the log — so a long run silently lost its
beginning, which is exactly where a startup error lives. Status now streams the
log incrementally (the client sends the byte offset it already holds) and the
export endpoint writes the file out in full. Two things are worth pinning down:

* the incremental reads must be lossless and must not split a multi-byte
  character at a chunk boundary (the logs are full of Chinese), and
* a restarted run truncates the log file, so a stale offset must fall back to a
  full reload instead of appending onto text that no longer exists.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.apps import dashboard_server as ds

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DASHBOARD = os.path.join(REPO_ROOT, "site", "dashboard")


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class RunLogSliceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "run.log")

    def _write(self, data, mode="wb"):
        with open(self.path, mode) as handle:
            handle.write(data)

    def test_missing_log_is_empty_not_an_error(self):
        chunk = ds._run_log_slice(os.path.join(self.tmp.name, "nope.log"))
        self.assertEqual("", chunk["text"])
        self.assertEqual(0, chunk["size"])
        self.assertFalse(chunk["append"])

    def test_first_read_returns_the_whole_log(self):
        self._write("day 1\nday 2\n".encode("utf-8"))
        chunk = ds._run_log_slice(self.path)
        self.assertEqual("day 1\nday 2\n", chunk["text"])
        self.assertFalse(chunk["append"])
        self.assertEqual(0, chunk["skipped"])
        self.assertEqual(chunk["size"], chunk["offset"])

    def test_later_reads_only_carry_what_was_appended(self):
        self._write("day 1\n".encode("utf-8"))
        first = ds._run_log_slice(self.path)
        self._write("day 2\n".encode("utf-8"), mode="ab")
        second = ds._run_log_slice(self.path, first["offset"])
        self.assertTrue(second["append"])
        self.assertEqual("day 2\n", second["text"])
        self.assertEqual(first["text"] + second["text"], "day 1\nday 2\n")

    def test_an_idle_log_appends_nothing(self):
        self._write("day 1\n".encode("utf-8"))
        offset = ds._run_log_slice(self.path)["offset"]
        chunk = ds._run_log_slice(self.path, offset)
        self.assertTrue(chunk["append"])
        self.assertEqual("", chunk["text"])
        self.assertEqual(offset, chunk["offset"])

    def test_an_append_reports_nothing_skipped(self):
        # `skipped` drives a "the head was omitted" notice in the panel, so an
        # append must not report the client's own offset as omitted bytes.
        self._write("day 1\n".encode("utf-8"))
        offset = ds._run_log_slice(self.path)["offset"]
        self._write("day 2\n".encode("utf-8"), mode="ab")
        self.assertEqual(0, ds._run_log_slice(self.path, offset)["skipped"])

    def test_a_restarted_run_forces_a_full_reload(self):
        self._write("a long first run\n".encode("utf-8"))
        stale = ds._run_log_slice(self.path)["offset"]
        self._write("new run\n".encode("utf-8"))  # truncates, as /api/run/start does
        chunk = ds._run_log_slice(self.path, stale)
        self.assertFalse(chunk["append"], "a stale offset must not append onto a rotated log")
        self.assertEqual("new run\n", chunk["text"])

    def test_a_half_written_character_waits_for_its_remaining_bytes(self):
        # The simulator writes while we read, so a poll can land mid-character.
        self._write("你好".encode("utf-8")[:-1])
        first = ds._run_log_slice(self.path)
        self.assertEqual("你", first["text"], "an incomplete character is held back, not mangled")
        self.assertEqual(3, first["offset"])
        self._write("你好".encode("utf-8")[-1:], mode="ab")
        second = ds._run_log_slice(self.path, first["offset"])
        self.assertEqual("好", second["text"])

    def test_an_oversized_log_drops_whole_characters_from_the_front(self):
        self._write("城市仿真日志".encode("utf-8"))
        original = ds.RUN_LOG_VIEW_MAX_BYTES
        ds.RUN_LOG_VIEW_MAX_BYTES = 10  # cuts inside a 3-byte character
        try:
            chunk = ds._run_log_slice(self.path)
        finally:
            ds.RUN_LOG_VIEW_MAX_BYTES = original
        self.assertNotIn("�", chunk["text"], "a truncated head must not leave a broken char")
        self.assertTrue(chunk["text"].endswith("日志"))
        self.assertGreater(chunk["skipped"], 0, "the client is told bytes were skipped")


class RunLogStatusPayloadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "run.log")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("booting\n")
        original = ds.RUN_STATE.get("log_path")
        ds.RUN_STATE["log_path"] = self.path
        self.addCleanup(lambda: ds.RUN_STATE.__setitem__("log_path", original))

    def test_status_reports_the_offset_and_size_the_client_needs(self):
        status = ds._run_status()
        self.assertEqual("booting\n", status["log_tail"])
        self.assertFalse(status["log_append"])
        self.assertEqual(len("booting\n"), status["log_size"])
        self.assertEqual(status["log_size"], status["log_offset"])

    def test_status_with_an_offset_is_an_append(self):
        offset = ds._run_status()["log_offset"]
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write("day 1 done\n")
        status = ds._run_status(offset)
        self.assertTrue(status["log_append"])
        self.assertEqual("day 1 done\n", status["log_tail"])


class RunLogMarkdownTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "run.log")
        original = ds.RUN_STATE.get("log_path")
        ds.RUN_STATE["log_path"] = self.path
        self.addCleanup(lambda: ds.RUN_STATE.__setitem__("log_path", original))

    def _write(self, text):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_export_holds_the_whole_log_not_a_tail(self):
        body = "".join(f"line {i}\n" for i in range(5000))
        self._write(body)
        markdown, filename = ds._run_log_markdown()
        self.assertTrue(filename.endswith(".md"))
        self.assertIn("# GAWorld Run Log", markdown)
        self.assertIn("line 0", markdown, "the export must keep the start of the run")
        self.assertIn("line 4999", markdown)

    def test_backticks_in_the_log_cannot_break_out_of_the_fence(self):
        self._write("traceback ``` inside\n")
        markdown, _ = ds._run_log_markdown()
        fences = re.findall(r"^`{3,}", markdown, flags=re.MULTILINE)
        self.assertEqual(2, len(fences), "exactly one code fence should open and close")
        self.assertGreaterEqual(len(fences[0]), 4, "the fence must outrun the backticks in the log")

    def test_an_empty_log_still_exports_a_readable_document(self):
        self._write("")
        markdown, _ = ds._run_log_markdown()
        self.assertIn("(empty)", markdown)


class RunLogEndpointTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "run.log")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("第 1 天开始\n")
        original = ds.RUN_STATE.get("log_path")
        ds.RUN_STATE["log_path"] = self.path
        self.addCleanup(lambda: ds.RUN_STATE.__setitem__("log_path", original))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def _get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url, timeout=10) as res:
            return res, res.read().decode("utf-8")

    def test_status_accepts_a_log_offset(self):
        _, body = self._get("/api/run/status")
        status = json.loads(body)
        self.assertEqual("第 1 天开始\n", status["log_tail"])
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write("第 2 天开始\n")
        _, body = self._get(f"/api/run/status?log_offset={status['log_offset']}")
        follow_up = json.loads(body)
        self.assertTrue(follow_up["log_append"])
        self.assertEqual("第 2 天开始\n", follow_up["log_tail"])

    def test_a_bad_offset_is_a_client_error(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._get("/api/run/status?log_offset=abc")
        self.assertEqual(400, caught.exception.code)

    def test_export_downloads_markdown_as_an_attachment(self):
        res, body = self._get("/api/run/log/export")
        self.assertEqual(200, res.status)
        self.assertIn("text/markdown", res.headers.get("Content-Type", ""))
        disposition = res.headers.get("Content-Disposition", "")
        self.assertIn("attachment", disposition)
        self.assertIn(".md", disposition)
        self.assertIn("第 1 天开始", body)


class RunLogPanelWiringTest(unittest.TestCase):
    """The panel is only fixed if the page actually asks for the new behaviour."""

    def test_the_page_offers_the_export_button(self):
        page = _read(os.path.join(DASHBOARD, "index.html"))
        self.assertIn('id="exportRunLogBtn"', page)
        self.assertIn('data-i18n="btn.export_run_log"', page)
        self.assertIn('id="runLogMeta"', page)

    def test_the_client_polls_with_an_offset_and_appends(self):
        app = _read(os.path.join(DASHBOARD, "app.js"))
        self.assertIn("log_offset=${offset}", app)
        self.assertIn("state.runLog.text += text", app)
        self.assertIn("/api/run/log/export", app)

    def test_both_locales_describe_the_export(self):
        for name in ("zh-CN.json", "en.json"):
            with self.subTest(locale=name):
                with open(os.path.join(DASHBOARD, "locales", name), encoding="utf-8") as handle:
                    locale = json.load(handle)
                for key in ("btn.export_run_log", "run_log.meta", "run_log.truncated", "run_log.exported"):
                    self.assertIn(key, locale)


if __name__ == "__main__":
    unittest.main()
