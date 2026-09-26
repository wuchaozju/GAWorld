"""Injecting an item into the information layer, and the read-only HTTP view.

Failure modes guarded:

* **An injected item that the next refresh silently drops.** The plugin
  reloads the feed cache from disk on every day start; an injection held only
  in the in-memory cache would last until the next morning.
* **An injected item that leaks into later runs** by being written to the
  shared disk cache.
* **An injection nobody can trace.** The point is to watch spread, so every
  feed read must land on ``infosources.read`` — and the synthetic URL must not
  trigger a page fetch.
* **A routing branch that is never hit** (the dashboard's if-chain).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.apps import dashboard_server as ds
from gaworld.infosources import channels, feed
from gaworld.infosources.plugin import InfoSourcesPlugin
from gaworld.infosources.schema import InfoItem, Source
from gaworld.kernel import build_kernel
from gaworld.sim import _news

SOURCES = [
    Source(id="who", name="WHO News", kind="professional", channel="rss",
           url="https://who.int/rss", topics=("医疗", "健康")),
    Source(id="paper", name="澎湃新闻", kind="news", channel="rss",
           url="https://thepaper.cn/rss", topics=("综合", "社会")),
]


def _doctor():
    return {"id": 7, "name": "林医生", "job": "社区医生", "memory": [],
            "state": {"platform_dependence": 0.5}, "ext": {}}


def _fetch(source, **kw):
    return [InfoItem(source.id, source.kind, f"{source.id} headline", url=f"https://{source.id}/1")]


class _Env:
    """A plugin wired to a scratch registry, feed cache and output root."""

    def __init__(self, tmp):
        root = Path(tmp)
        reg = root / "info_sources.json"
        reg.write_text(json.dumps({"sources": [s.to_dict() for s in SOURCES]}), encoding="utf-8")
        self.cache_path = root / "feed.json"
        self.config = {
            "output_root": str(root / "output"),
            "records": {"output_dir": str(root / "records")},
            "news": {"enabled": True, "sources": {
                "enabled": True, "registry_path": str(reg), "feed_cache_path": str(self.cache_path),
                "ttl_hours": 6, "feed_visit_ratio": 1.0, "diet": {"max_sources": 1},
            }},
        }
        self.ctx = build_kernel(self.config, load_entry_points=False)
        InfoSourcesPlugin().setup(self.ctx)
        self.agents = [_doctor()]
        with mock.patch.object(channels, "fetch_source", side_effect=_fetch):
            self.ctx.bus.emit("agents.built", agents=self.agents, config=self.config)
        self.ctx.clock.start_day(2)


class InjectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = _Env(self.tmp.name)
        self.ctx = self.env.ctx

    def tearDown(self):
        feed.set_runtime(None)
        self.ctx.recorder.close()
        self.tmp.cleanup()

    def _inject(self, **kw):
        return self.ctx.controller.intervene("inject_info_item", self.ctx, **kw)

    def test_item_goes_on_top_and_survives_refreshes_but_not_the_disk_cache(self):
        self._inject(source_id="who", title="本市出现新型流感病例", excerpt="卫健委通报")
        self.assertEqual(feed.runtime().cache.items_for("who")[0].title, "本市出现新型流感病例")
        # Day start without refetch, then with one (TTL forced stale).
        for stale in (False, True):
            with mock.patch.object(feed, "is_stale", return_value=stale), \
                 mock.patch.object(channels, "fetch_source", side_effect=_fetch):
                self.ctx.bus.emit("on_day_start", day=3, agents=self.env.agents)
            top = feed.runtime().cache.items_for("who")
            self.assertEqual(top[0].title, "本市出现新型流感病例")
            self.assertEqual(sum(1 for i in top if i.meta.get("injected")), 1)
        on_disk = json.loads(self.env.cache_path.read_text("utf-8"))
        self.assertNotIn("本市出现新型流感病例", json.dumps(on_disk, ensure_ascii=False))
        with open(os.path.join(self.tmp.name, "records", "infosources.injected.jsonl")) as f:
            self.assertEqual(json.loads(f.readline())["url"], "gaworld://injected/1")

    def test_bad_requests_are_refused(self):
        with self.assertRaisesRegex(ValueError, "unknown source_id"):
            self._inject(source_id="nope", title="x")
        with self.assertRaisesRegex(ValueError, "title"):
            self._inject(source_id="who", title=" ")

    def test_a_reader_of_that_source_reads_it_and_the_read_is_recorded(self):
        self._inject(source_id="who", title="本市出现新型流感病例", excerpt="卫健委通报")
        agent = self.env.agents[0]
        with mock.patch.object(_news, "fetch_news_excerpt", side_effect=AssertionError("no page fetch")), \
             mock.patch.object(_news._llm_providers, "call_llm", return_value="得提醒病人打疫苗。"), \
             mock.patch.object(_news, "save_agent_memory"), \
             mock.patch.object(_news, "vector_db_add_entry"):
            memory, _, url, _ = _news.info_seek_and_store(agent, day=2, time_str="09:00", config={})
        self.assertIn("本市出现新型流感病例", memory)
        self.assertEqual(url, "gaworld://injected/1")
        with open(os.path.join(self.tmp.name, "records", "infosources.read.jsonl")) as f:
            row = json.loads(f.readline())
        self.assertEqual((row["agent_id"], row["source_id"], row["thought"]), (7, "who", "得提醒病人打疫苗。"))


class HttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = _Env(self.tmp.name)
        self.env.ctx.controller.intervene("inject_info_item", self.env.ctx, source_id="who", title="注入")
        self.env.ctx.recorder.record("infosources.read", {"agent_id": 7, "source_id": "who", "url": "u1"})
        self.env.ctx.recorder.record("infosources.read", {"agent_id": 8, "source_id": "paper", "url": "u2"})
        self.env.ctx.recorder.close()
        feed.save(self.env.cache_path, feed.runtime().cache)  # what a refresh would have left on disk
        self._saved = (ds.REPO_ROOT, ds.RECORDS_DIR, ds.CONFIG)
        ds.REPO_ROOT = self.tmp.name
        ds.RECORDS_DIR = os.path.join(self.tmp.name, "records")
        ds.CONFIG = self.env.config
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        ds.REPO_ROOT, ds.RECORDS_DIR, ds.CONFIG = self._saved
        feed.set_runtime(None)
        self.tmp.cleanup()

    def _get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_endpoints(self):
        status, body = self._get("/api/infosources/sources")
        self.assertEqual(status, 200)
        self.assertEqual([s["id"] for s in body["sources"]], ["who", "paper"])
        self.assertEqual(body["sources"][0]["items"], 2)

        _, body = self._get("/api/infosources/feed?source_id=who&limit=1")
        self.assertEqual([i["title"] for i in body["items"]], ["注入"])

        _, body = self._get("/api/infosources/diets?agent_id=7")
        self.assertEqual(body["diet"][0]["source_id"], "who")
        self.assertEqual(self._get("/api/infosources/diets?agent_id=99")[0], 404)

        _, body = self._get("/api/infosources/reads?source_id=paper")
        self.assertEqual([r["agent_id"] for r in body["reads"]], [8])
        self.assertEqual(self._get("/api/infosources/nope")[0], 404)


if __name__ == "__main__":
    unittest.main()
