"""Tests for ``gaworld.infosources`` and its wiring into the news pipeline.

Covers, bottom up:

1. channel parsers from fixture strings (RSS 2.0 / RDF / Atom, Reddit, Hacker
   News, Weibo / Baidu / Bilibili hot lists, plain page) and the fetch
   dispatcher's failure modes;
2. the registry (validation, duplicates, missing file);
3. the feed cache (real-time TTL gating, dedupe, cap, roundtrip);
4. the media diet (job → topics, interests, openness, platform dependence,
   determinism) and item picking;
5. the search providers (DuckDuckGo parse, Brave / Tavily with fakes, no key);
6. ``gaworld.sim._news``: the source-list regex fix, the homepage-cache TTL,
   the ``ddg`` engine, the ``feed`` info-seek mode and its memory entry;
7. the plugin lifecycle on a real kernel.

No test touches the network: every fetch is a fake session or a patched
function, and every LLM call is mocked.
"""

from __future__ import annotations

import json
import random
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import requests

from gaworld.infosources import channels, diet, feed, registry, search
from gaworld.infosources.plugin import InfoSourcesPlugin
from gaworld.infosources.schema import InfoItem, Source
from gaworld.kernel import build_kernel
from gaworld.sim import _news

NOW = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)


def _src(sid="s", kind="news", channel="rss", url="https://example.com/feed", topics=(), lang="zh", **kw):
    return Source(id=sid, name=kw.pop("name", sid), kind=kind, channel=channel, url=url,
                  topics=tuple(topics), lang=lang, **kw)


class _FakeResponse:
    def __init__(self, text="", status=200, content_type="text/xml"):
        self.text = text
        self.status_code = status
        self.encoding = "utf-8"
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return json.loads(self.text)


class _FakeSession:
    def __init__(self, text="", status=200):
        self.text = text
        self.status = status
        self.calls = []

    def get(self, url, *, timeout=8, headers=None, allow_redirects=True):
        self.calls.append({"url": url, "timeout": timeout, "headers": dict(headers or {})})
        if self.status == 599:
            raise requests.ConnectionError("offline")
        return _FakeResponse(self.text, self.status)


# ---------------------------------------------------------------------------
# 1. Channel parsers
# ---------------------------------------------------------------------------

RSS2 = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Feed</title>
<item><title>第一条 &amp; 标题</title><link>https://example.com/a</link>
  <description><![CDATA[<p>正文 <b>摘要</b> 一</p>]]></description>
  <pubDate>Thu, 18 Sep 2026 08:00:00 GMT</pubDate></item>
<item><title>Second</title><link>https://example.com/b</link><description>Body two</description></item>
<item><title>   </title><link>https://example.com/empty</link></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>ArXiv Query</title>
<entry><id>http://arxiv.org/abs/2609.00001v1</id><title>A Paper</title>
  <summary>We study things.</summary><published>2026-09-18T00:00:00Z</published>
  <link title="pdf" href="http://arxiv.org/pdf/2609.00001v1" rel="related" type="application/pdf"/>
  <link href="http://arxiv.org/abs/2609.00001v1" rel="alternate" type="text/html"/>
</entry></feed>"""

RDF = """<?xml version="1.0"?>
<rdf:RDF xmlns="http://purl.org/rss/1.0/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
  xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel rdf:about="https://dw.com"><title>DW</title></channel>
<item rdf:about="https://dw.com/x"><title>RDF 条目</title><link>https://dw.com/x</link>
  <description>desc</description><dc:date>2026-09-18T01:00:00Z</dc:date></item>
</rdf:RDF>"""


class TestParsers(unittest.TestCase):
    def test_rss2_items_with_html_stripped_and_blank_title_skipped(self):
        items = channels.parse_rss(RSS2, _src(), fetched_at="t0")
        self.assertEqual([i.title for i in items], ["第一条 & 标题", "Second"])
        self.assertEqual(items[0].url, "https://example.com/a")
        self.assertEqual(items[0].excerpt, "正文 摘要 一")
        self.assertEqual(items[0].published_at, "Thu, 18 Sep 2026 08:00:00 GMT")
        self.assertEqual(items[0].fetched_at, "t0")
        self.assertEqual(items[0].kind, "news")

    def test_rss_limit(self):
        self.assertEqual(len(channels.parse_rss(RSS2, _src(), limit=1)), 1)

    def test_atom_prefers_alternate_link(self):
        items = channels.parse_rss(ATOM, _src(kind="professional"))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].url, "http://arxiv.org/abs/2609.00001v1")
        self.assertEqual(items[0].excerpt, "We study things.")
        self.assertEqual(items[0].published_at, "2026-09-18T00:00:00Z")

    def test_rdf_items(self):
        items = channels.parse_rss(RDF, _src())
        self.assertEqual([(i.title, i.url, i.published_at) for i in items],
                         [("RDF 条目", "https://dw.com/x", "2026-09-18T01:00:00Z")])

    def test_not_xml_is_empty(self):
        self.assertEqual(channels.parse_rss("<html><body>blocked</body>", _src()), [])
        self.assertEqual(channels.parse_rss("", _src()), [])

    def test_reddit_skips_stickied_and_builds_permalink(self):
        payload = {"data": {"children": [
            {"data": {"title": "Pinned", "permalink": "/r/x/1", "stickied": True}},
            {"data": {"title": "Self post", "permalink": "/r/x/2", "selftext": "<p>body</p>",
                      "created_utc": 1789000000, "score": 12, "subreddit": "x"}},
            {"data": {"title": "Link post", "permalink": "/r/x/3", "selftext": "",
                      "url": "https://news.example/story", "score": 3, "subreddit": "x"}},
        ]}}
        items = channels.parse_reddit(json.dumps(payload), _src(kind="social", channel="reddit"))
        self.assertEqual([i.title for i in items], ["Self post", "Link post"])
        self.assertEqual(items[0].url, "https://www.reddit.com/r/x/2")
        self.assertEqual(items[0].excerpt, "body")
        self.assertTrue(items[0].published_at.startswith("2026-"))
        self.assertIn("https://news.example/story", items[1].excerpt)
        self.assertIn("3 赞", items[1].excerpt)

    def test_hackernews_falls_back_to_item_page(self):
        payload = {"hits": [
            {"title": "Show HN", "url": "https://x.dev", "objectID": "1", "points": 100, "num_comments": 5},
            {"title": "Ask HN", "url": None, "objectID": "2", "story_text": "<p>question</p>"},
        ]}
        items = channels.parse_hackernews(json.dumps(payload), _src(kind="social", channel="hackernews"))
        self.assertEqual(items[0].url, "https://x.dev")
        self.assertEqual(items[0].excerpt, "Hacker News · 100 points · 5 comments")
        self.assertEqual(items[1].url, "https://news.ycombinator.com/item?id=2")
        self.assertEqual(items[1].excerpt, "question")

    def test_weibo_hot_skips_ads(self):
        payload = {"ok": 1, "data": {"realtime": [
            {"word": "广告", "is_ad": 1},
            {"word": "某地暴雨", "note": "某地暴雨 红色预警", "num": 1234567},
        ]}}
        items = channels.parse_weibo_hot(json.dumps(payload), _src(kind="social", channel="weibo_hot"))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "某地暴雨")
        self.assertIn("热度 1234567", items[0].excerpt)
        self.assertIn("红色预警", items[0].excerpt)
        self.assertTrue(items[0].url.startswith("https://s.weibo.com/weibo?q="))
        self.assertEqual(items[0].meta, {"heat": 1234567})

    def test_baidu_hot(self):
        payload = {"data": {"cards": [{"content": [
            {"word": "热词", "desc": "说明", "url": "https://www.baidu.com/s?wd=热词", "hotScore": "99"},
            {"word": "无链接"},
        ]}]}}
        items = channels.parse_baidu_hot(json.dumps(payload), _src(kind="social", channel="baidu_hot"))
        self.assertEqual([i.title for i in items], ["热词", "无链接"])
        self.assertEqual(items[0].excerpt, "说明")
        self.assertIn("baidu.com/s?wd=", items[1].url)
        self.assertEqual(items[1].excerpt, "百度热搜")

    def test_bilibili_popular(self):
        payload = {"code": 0, "data": {"list": [
            {"title": "视频", "desc": "简介", "bvid": "BV1", "owner": {"name": "UP"}, "pubdate": 1789000000},
        ]}}
        items = channels.parse_bilibili_popular(json.dumps(payload),
                                                _src(kind="social", channel="bilibili_popular"))
        self.assertEqual(items[0].url, "https://www.bilibili.com/video/BV1")
        self.assertEqual(items[0].excerpt, "UP主 UP · 简介")

    def test_page_is_one_item(self):
        html = "<html><head><title>澎湃</title></head><body><article>" + "".join(
            f"<p>这是第{n}段足够长的正文内容，用来通过段落长度的过滤条件，再补几个字。</p>" for n in range(8)
        ) + "</article></body></html>"
        items = channels.parse_page(html, _src(channel="page", url="https://www.thepaper.cn/"))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "澎湃")
        self.assertEqual(items[0].url, "https://www.thepaper.cn/")
        self.assertIn("第0段", items[0].excerpt)

    def test_bad_json_is_empty(self):
        for parser in (channels.parse_reddit, channels.parse_hackernews, channels.parse_weibo_hot,
                       channels.parse_baidu_hot, channels.parse_bilibili_popular):
            self.assertEqual(parser("<html>", _src()), [])


class TestFetchSource(unittest.TestCase):
    def test_dispatches_by_channel_and_sets_reddit_user_agent(self):
        sess = _FakeSession(json.dumps({"data": {"children": [{"data": {"title": "T", "permalink": "/r/a/1"}}]}}))
        items = channels.fetch_source(_src(channel="reddit", kind="social"), session=sess, now=NOW)
        self.assertEqual(items[0].title, "T")
        self.assertEqual(items[0].fetched_at, NOW.isoformat(timespec="seconds"))
        self.assertEqual(sess.calls[0]["headers"]["User-Agent"], channels.REDDIT_USER_AGENT)

    def test_rss_fetch_uses_rotator_user_agent(self):
        sess = _FakeSession(RSS2)
        channels.fetch_source(_src(), session=sess)
        self.assertNotIn("User-Agent", sess.calls[0]["headers"])
        self.assertIn("application/rss+xml", sess.calls[0]["headers"]["Accept"])

    def test_transport_and_http_errors_yield_empty(self):
        self.assertEqual(channels.fetch_source(_src(), session=_FakeSession(status=599)), [])
        self.assertEqual(channels.fetch_source(_src(), session=_FakeSession(status=403)), [])

    def test_unknown_channel_is_empty_without_network(self):
        sess = _FakeSession(RSS2)
        self.assertEqual(channels.fetch_source(_src(channel="carrier_pigeon"), session=sess), [])
        self.assertEqual(sess.calls, [])


# ---------------------------------------------------------------------------
# 2. Registry
# ---------------------------------------------------------------------------

class TestRegistry(unittest.TestCase):
    def test_parse_skips_invalid_and_duplicate_entries(self):
        data = {"sources": [
            {"id": "ok", "name": "OK", "kind": "news", "channel": "rss", "url": "https://a/f", "topics": "科技, 财经"},
            {"id": "bad_kind", "kind": "gossip", "channel": "rss", "url": "https://a/f"},
            {"id": "bad_url", "kind": "news", "channel": "rss", "url": "ftp://a/f"},
            {"id": "bad_channel", "kind": "news", "channel": "carrier_pigeon", "url": "https://a/f"},
            {"id": "ok", "kind": "news", "channel": "rss", "url": "https://a/dup"},
            "not an object",
        ]}
        sources = registry.parse_registry(data)
        self.assertEqual([s.id for s in sources], ["ok"])
        self.assertEqual(sources[0].topics, ("科技", "财经"))
        self.assertEqual(sources[0].domain, "a")

    def test_load_missing_or_corrupt_file_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(registry.load_registry(Path(tmp) / "nope.json"), [])
            bad = Path(tmp) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            self.assertEqual(registry.load_registry(bad), [])

    def test_shipped_registry_is_valid_and_typed(self):
        sources = registry.load_registry("data/info_sources.json")
        self.assertGreaterEqual(len(sources), 30)
        kinds = {s.kind for s in sources}
        self.assertEqual(kinds, {"news", "social", "professional"})
        self.assertTrue(all(s.topics for s in sources))
        self.assertTrue(any(s.channel == "weibo_hot" for s in sources))
        self.assertTrue(any("医疗" in s.topics for s in sources))


# ---------------------------------------------------------------------------
# 3. Feed cache
# ---------------------------------------------------------------------------

class TestFeedCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "feed.json"
        self.sources = [_src("a", topics=("综合",)), _src("b", topics=("科技",)), _src("off", enabled=False)]
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def _fetch(self, source):
        self.calls.append(source.id)
        return [InfoItem(source.id, source.kind, f"{source.id}-{n}", url=f"https://{source.id}/{n}") for n in range(3)]

    def test_ttl_gates_fetches_on_real_time(self):
        feed.refresh(self.sources, self.path, fetch_fn=self._fetch, ttl_hours=6, now=NOW)
        self.assertEqual(self.calls, ["a", "b"])  # disabled source never fetched
        feed.refresh(self.sources, self.path, fetch_fn=self._fetch, ttl_hours=6, now=NOW + timedelta(hours=1))
        self.assertEqual(self.calls, ["a", "b"])  # still fresh
        feed.refresh(self.sources, self.path, fetch_fn=self._fetch, ttl_hours=6, now=NOW + timedelta(hours=7))
        self.assertEqual(self.calls, ["a", "b", "a", "b"])
        feed.refresh(self.sources, self.path, fetch_fn=self._fetch, ttl_hours=6, now=NOW + timedelta(hours=7),
                     force=True)
        self.assertEqual(self.calls, ["a", "b", "a", "b", "a", "b"])

    def test_new_items_first_deduped_and_capped(self):
        cache = feed.refresh(self.sources[:1], self.path, fetch_fn=self._fetch, now=NOW)
        self.assertEqual([i.title for i in cache.items_for("a")], ["a-0", "a-1", "a-2"])

        def later(source):
            return [InfoItem("a", "news", "fresh", url="https://a/9"),
                    InfoItem("a", "news", "a-1 again", url="https://a/1")]

        cache = feed.refresh(self.sources[:1], self.path, fetch_fn=later, per_source_limit=3,
                             now=NOW + timedelta(hours=7))
        self.assertEqual([i.title for i in cache.items_for("a")], ["fresh", "a-1 again", "a-0"])

    def test_empty_fetch_still_stamps_and_raising_fetch_is_contained(self):
        def boom(source):
            if source.id == "a":
                raise RuntimeError("dead feed")
            return []

        cache = feed.refresh(self.sources, self.path, fetch_fn=boom, now=NOW)
        self.assertEqual(cache.items, {})
        self.assertEqual(set(cache.last_fetch), {"a", "b"})
        self.assertFalse(feed.is_stale(cache, "a", ttl_hours=6, now=NOW + timedelta(hours=1)))

    def test_roundtrip_and_corrupt_file(self):
        cache = feed.FeedCache(
            items={"a": [InfoItem("a", "news", "t", url="https://a/1", excerpt="e", meta={"heat": 3})]},
            last_fetch={"a": NOW.isoformat()},
        )
        feed.save(self.path, cache)
        loaded = feed.load(self.path)
        self.assertEqual(loaded.to_dict(), cache.to_dict())
        self.assertEqual(loaded.items_for("a")[0].meta, {"heat": 3})
        self.path.write_text("{oops", encoding="utf-8")
        self.assertEqual(feed.load(self.path).items, {})

    def test_runtime_holder(self):
        rt = feed.FeedRuntime(cache=feed.FeedCache(), sources={}, settings={"x": 1})
        feed.set_runtime(rt)
        try:
            self.assertIs(feed.runtime(), rt)
        finally:
            feed.set_runtime(None)
        self.assertIsNone(feed.runtime())


# ---------------------------------------------------------------------------
# 4. Media diet
# ---------------------------------------------------------------------------

REGISTRY = [
    _src("who", kind="professional", topics=("医疗", "健康"), lang="en", name="WHO News"),
    _src("hn", kind="social", channel="hackernews", topics=("科技", "编程"), lang="en", name="Hacker News"),
    _src("jiqi", kind="professional", topics=("人工智能", "科技"), name="机器之心"),
    _src("paper", kind="news", topics=("综合", "社会"), name="澎湃新闻"),
    _src("weibo", kind="social", channel="weibo_hot", topics=("热点", "社会"), name="微博热搜"),
    _src("edu", kind="professional", topics=("教育",), lang="en", name="EdSurge"),
]


def _agent(job, *, openness=0.0, platform=0.5, agent_id=1):
    return {
        "id": agent_id,
        "name": "测试",
        "job": job,
        "state": {"platform_dependence": platform},
        "ext": {"big_five": {"o": openness, "c": 0.0, "e": 0.0, "a": 0.0, "n": 0.0}},
    }


def _weight(rows, sid):
    return next((r["weight"] for r in rows if r["source_id"] == sid), 0.0)


class TestMediaDiet(unittest.TestCase):
    def test_profession_topics(self):
        self.assertIn("医疗", diet.profession_topics("社区医生"))
        self.assertIn("科技", diet.profession_topics("软件工程师"))
        self.assertIn("教育", diet.profession_topics("医学院教师"))
        self.assertIn("医疗", diet.profession_topics("医学院教师"))
        self.assertIn("民生", diet.profession_topics("退休"))
        self.assertEqual(diet.profession_topics("xyz"), [])
        self.assertEqual(diet.profession_topics(""), [])

    def test_doctor_reads_medicine_programmer_reads_tech(self):
        doctor = diet.build_media_diet(_agent("社区医生"), REGISTRY)
        coder = diet.build_media_diet(_agent("软件工程师"), REGISTRY)
        self.assertGreater(_weight(doctor, "who"), _weight(doctor, "hn"))
        self.assertGreater(_weight(coder, "hn"), _weight(coder, "who"))
        self.assertGreater(_weight(coder, "jiqi"), _weight(coder, "edu"))
        for rows in (doctor, coder):
            self.assertIn("paper", [r["source_id"] for r in rows])  # mainstream reach
            self.assertAlmostEqual(sum(r["weight"] for r in rows), 1.0, places=3)
        self.assertIn("职业:医疗/健康", next(r for r in doctor if r["source_id"] == "who")["reason"])

    def test_interests_pull_in_sources_by_alias_and_name(self):
        plain = diet.build_media_diet(_agent("退休"), REGISTRY)
        curious = diet.build_media_diet(_agent("退休"), REGISTRY, interests=["股票", "编程", "机器之心"])
        self.assertGreater(_weight(curious, "hn"), _weight(plain, "hn"))
        self.assertGreater(_weight(curious, "jiqi"), _weight(plain, "jiqi"))
        reason = next(r for r in curious if r["source_id"] == "jiqi")["reason"]
        self.assertIn("兴趣:", reason)
        self.assertIn("站名", reason)

    def test_platform_dependence_scales_social_share(self):
        low = diet.build_media_diet(_agent("退休", platform=0.1), REGISTRY)
        high = diet.build_media_diet(_agent("退休", platform=0.9), REGISTRY)
        self.assertGreater(_weight(high, "weibo"), _weight(low, "weibo"))

    def test_openness_widens_towards_foreign_and_unmatched_sources(self):
        closed = diet.build_media_diet(_agent("退休", openness=-2.0), REGISTRY)
        open_ = diet.build_media_diet(_agent("退休", openness=2.0), REGISTRY)
        self.assertGreater(_weight(open_, "who"), _weight(closed, "who"))
        self.assertGreater(_weight(open_, "hn"), _weight(closed, "hn"))

    def test_neutral_without_traits_and_deterministic(self):
        agent = {"id": 9, "job": "教师", "state": {}}
        first = diet.build_media_diet(agent, REGISTRY)
        second = diet.build_media_diet(agent, REGISTRY)
        self.assertEqual(first, second)
        # Mainstream Chinese sources outrank the one matching trade site, which
        # is English (en_weight 0.5); ties break by id, so 澎湃 before 微博.
        self.assertEqual([r["source_id"] for r in first][:3], ["paper", "weibo", "edu"])

    def test_max_sources_and_disabled(self):
        rows = diet.build_media_diet(_agent("社区医生"), [*REGISTRY, _src("off", enabled=False, topics=("医疗",))],
                                     config={"max_sources": 2})
        self.assertEqual(len(rows), 2)
        self.assertNotIn("off", [r["source_id"] for r in rows])

    def test_diet_of_reads_plugin_namespace(self):
        self.assertEqual(diet.diet_of({"id": 1}), [])
        agent = {"ext": {"infosources": {"diet": [{"source_id": "a", "weight": 1.0}]}}}
        self.assertEqual(diet.diet_of(agent), [{"source_id": "a", "weight": 1.0}])

    def test_pick_item_honours_seen_and_falls_through(self):
        cache = feed.FeedCache(items={
            "who": [InfoItem("who", "professional", "疫苗 指南", url="https://who/1"),
                    InfoItem("who", "professional", "其他", url="https://who/2")],
            "paper": [InfoItem("paper", "news", "本地新闻", url="https://paper/1")],
        })
        rows = [{"source_id": "who", "weight": 0.9, "name": "WHO"}, {"source_id": "paper", "weight": 0.1, "name": "澎湃"}]
        rng = random.Random(1)
        entry, item, _score, matched = diet.pick_item(rows, cache, interests=["疫苗"], rng=rng)
        self.assertEqual(item.url, "https://who/1")
        self.assertEqual(matched, ["疫苗"])
        seen = {"https://who/1", "https://who/2"}
        entry, item, _, _ = diet.pick_item(rows, cache, seen_urls=seen, rng=rng)
        self.assertEqual(entry["source_id"], "paper")
        seen.add("https://paper/1")
        self.assertIsNone(diet.pick_item(rows, cache, seen_urls=seen, rng=rng))
        self.assertIsNone(diet.pick_item([], cache, rng=rng))


# ---------------------------------------------------------------------------
# 5. Search providers
# ---------------------------------------------------------------------------

DDG_HTML = """
<div class="result"><a rel="nofollow" class="result__a"
 href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fstory&amp;rut=abc">Example <b>Story</b></a>
 <a class="result__snippet" href="//duckduckgo.com/l/?uddg=x">A snippet.</a></div>
<div class="result"><a class="result__a" href="https://direct.example/x">Direct link</a>
 <a class="result__snippet">Second snippet</a></div>
<div class="result"><a class="result__a" href="javascript:void(0)">no</a></div>
"""


class TestSearchProviders(unittest.TestCase):
    def test_parse_ddg_decodes_redirects(self):
        results = search.parse_ddg_results(DDG_HTML)
        self.assertEqual(results, [
            {"url": "https://example.com/story", "title": "Example Story", "snippet": "A snippet."},
            {"url": "https://direct.example/x", "title": "Direct link", "snippet": "Second snippet"},
        ])
        self.assertEqual(len(search.parse_ddg_results(DDG_HTML, max_results=1)), 1)

    def test_ddg_search_uses_session_and_degrades(self):
        sess = _FakeSession(DDG_HTML, status=200)
        results = search.ddg_search("测试 查询", session=sess)
        self.assertEqual(results[0]["url"], "https://example.com/story")
        self.assertIn("q=%E6%B5%8B%E8%AF%95+%E6%9F%A5%E8%AF%A2", sess.calls[0]["url"])
        self.assertEqual(search.ddg_search("q", session=_FakeSession(status=403)), [])

    def test_brave_search(self):
        payload = {"web": {"results": [
            {"title": "T1", "url": "https://a/1", "description": "<b>d</b>"},
            {"title": "", "url": "https://a/2"},
        ]}}
        sess = _FakeSession(json.dumps(payload))
        results = search.brave_search("q", api_key="k", session=sess)
        self.assertEqual(results, [{"url": "https://a/1", "title": "T1", "snippet": "d"}])
        self.assertEqual(sess.calls[0]["headers"]["X-Subscription-Token"], "k")
        self.assertEqual(search.brave_search("q", api_key="", session=sess), [])
        self.assertEqual(len(sess.calls), 1)

    def test_tavily_search(self):
        payload = {"results": [{"title": "T", "url": "https://t/1", "content": "body"}]}
        with mock.patch.object(search.requests, "post", return_value=_FakeResponse(json.dumps(payload))) as post:
            results = search.tavily_search("q", api_key="k")
        self.assertEqual(results, [{"url": "https://t/1", "title": "T", "snippet": "body"}])
        self.assertEqual(post.call_args.kwargs["json"]["query"], "q")
        with mock.patch.object(search.requests, "post", side_effect=requests.ConnectionError("x")):
            self.assertEqual(search.tavily_search("q", api_key="k"), [])

    def test_api_search_without_key_is_silent(self):
        cfg = {"search_api": {"brave_api_key_env": "GAWORLD_TEST_UNSET_BRAVE",
                              "tavily_api_key_env": "GAWORLD_TEST_UNSET_TAVILY"}}
        with mock.patch.object(search, "get_default_session", side_effect=AssertionError("no network")), \
             mock.patch.object(search.requests, "post", side_effect=AssertionError("no network")):
            self.assertEqual(search.api_search("brave", "q", config=cfg), [])
            self.assertEqual(search.api_search("tavily", "q", config=cfg), [])
            self.assertEqual(search.api_search("unknown", "q", config=cfg), [])


# ---------------------------------------------------------------------------
# 6. Wiring into gaworld.sim._news
# ---------------------------------------------------------------------------

def _news_agent():
    return {
        "id": 7,
        "name": "林素",
        "job": "社区医生",
        "personality": "细心",
        "daily_life": "白天坐诊",
        "values": "关心公共卫生政策",
        "state": {"platform_dependence": 0.4, "risk_preference": 0.5},
        "memory": [],
        "ext": {"infosources": {"diet": [
            {"source_id": "who", "name": "WHO News", "kind": "professional", "domain": "who.int", "weight": 0.7},
            {"source_id": "weibo", "name": "微博热搜", "kind": "social", "domain": "weibo.com", "weight": 0.3},
        ]}},
    }


def _runtime(**settings):
    cache = feed.FeedCache(items={
        "who": [InfoItem("who", "professional", "疫苗接种新指南", url="https://who.int/news/1", excerpt="简短。")],
    })
    sources = {
        "who": _src("who", kind="professional", url="https://who.int/rss", name="WHO News"),
        "weibo": _src("weibo", kind="social", channel="weibo_hot", url="https://weibo.com/hot", name="微博热搜"),
    }
    return feed.FeedRuntime(cache=cache, sources=sources, settings={"feed_visit_ratio": 1.0, **settings})


class TestNewsWiring(unittest.TestCase):
    def tearDown(self):
        feed.set_runtime(None)

    def test_load_news_sources_reads_whole_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "news_source.md"
            path.write_text(
                "https://news.baidu.com/\nhttps://www.bbc.com/news\n[早报](https://www.zaobao.com/rss)\n"
                "https://www.reddit.com/\nhttps://x.com/cnnbrk\n",
                encoding="utf-8",
            )
            self.assertEqual(_news.load_news_sources(str(path)), [
                "https://www.zaobao.com/rss",
                "https://news.baidu.com/",
                "https://www.bbc.com/news",
                "https://www.reddit.com/",
                "https://x.com/cnnbrk",
            ])

    def test_news_cache_ttl(self):
        fresh = [{"url": "u", "text": "t", "fetched_at": datetime.now(UTC).isoformat()}]
        stale = [{"url": "u", "text": "t", "fetched_at": "2026-09-16"}]
        self.assertTrue(_news._news_cache_is_fresh(fresh, 6.0))
        self.assertFalse(_news._news_cache_is_fresh(stale, 6.0))
        self.assertFalse(_news._news_cache_is_fresh(fresh, 0))
        self.assertFalse(_news._news_cache_is_fresh([{"url": "u", "text": "t", "fetched_at": "bad"}], 6.0))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            path.write_text(json.dumps(fresh), encoding="utf-8")
            with mock.patch.object(_news, "fetch_news_excerpt", side_effect=AssertionError("no network")):
                items = _news.update_news_cache(str(path), ["https://a/"], {"cache_ttl_hours": 6})
            self.assertEqual(items[0]["url"], "u")

    def test_web_search_ddg_engine_and_fall_through(self):
        fake = [{"url": "https://a/1", "title": "t", "snippet": "s"}]
        with mock.patch.object(_news, "api_search", return_value=fake) as api:
            self.assertEqual(_news.web_search("q", config={"engines": ["ddg"]}), ("ddg", fake))
        api.assert_called_once_with("ddg", "q", config={"engines": ["ddg"]})
        with mock.patch.object(_news, "api_search", return_value=[]), \
             mock.patch.object(_news.requests, "get", side_effect=requests.RequestException("offline")) as get:
            self.assertEqual(_news.web_search("q", config={"engines": ["brave", "bing"]}), ("", []))
        get.assert_called_once()  # bing was tried after brave returned nothing

    def test_choose_info_target_reads_from_diet(self):
        feed.set_runtime(_runtime(full_read=True, full_read_min_chars=200))
        with mock.patch.object(_news, "fetch_news_excerpt", return_value="正文全文" * 20) as fetch:
            target = _news._choose_info_target(_news_agent(), news_cache=[], news_sources=[], preferred_sites=[])
        self.assertEqual(target["mode"], "feed")
        self.assertEqual(target["source_name"], "WHO News")
        self.assertEqual(target["kind_label"], "专业网站")
        self.assertEqual(target["url"], "https://who.int/news/1")
        self.assertTrue(target["content"].startswith("正文全文"))
        fetch.assert_called_once()

    def test_feed_full_read_skips_hot_lists_and_short_excerpts_when_off(self):
        rt = _runtime(full_read=False)
        feed.set_runtime(rt)
        with mock.patch.object(_news, "fetch_news_excerpt", side_effect=AssertionError("no fetch")):
            target = _news._choose_info_target(_news_agent(), news_cache=[], news_sources=[], preferred_sites=[])
        self.assertEqual(target["content"], "简短。")
        rt.cache.items = {"weibo": [InfoItem("weibo", "social", "热搜词", url="https://s.weibo.com/weibo?q=x",
                                             excerpt="微博热搜 · 热度 9")]}
        rt.settings["full_read"] = True
        with mock.patch.object(_news, "fetch_news_excerpt", side_effect=AssertionError("no fetch")):
            target = _news._choose_info_target(_news_agent(), news_cache=[], news_sources=[], preferred_sites=[])
        self.assertEqual(target["source_name"], "微博热搜")
        self.assertEqual(target["kind_label"], "社交媒体")

    def test_legacy_path_without_runtime_or_diet(self):
        feed.set_runtime(None)
        with mock.patch.object(_news, "web_search", return_value=("", [])):
            self.assertIsNone(_news._choose_info_target(_news_agent(), news_cache=[], news_sources=[],
                                                        preferred_sites=[]))
        feed.set_runtime(_runtime())
        agent = _news_agent()
        agent["ext"] = {}
        with mock.patch.object(_news, "web_search", return_value=("", [])) as ws:
            self.assertIsNone(_news._choose_info_target(agent, news_cache=[], news_sources=[], preferred_sites=[]))
        ws.assert_called_once()

    def test_feed_visit_ratio_zero_never_reads_feed(self):
        feed.set_runtime(_runtime(feed_visit_ratio=0.0))
        with mock.patch.object(_news, "web_search", return_value=("", [])):
            self.assertIsNone(_news._choose_info_target(_news_agent(), news_cache=[], news_sources=[],
                                                        preferred_sites=[]))

    def test_info_seek_memory_records_channel(self):
        target = {
            "mode": "feed", "query": "", "engine": "", "url": "https://who.int/news/1",
            "title": "疫苗接种新指南", "content": "内容", "score": 1.3, "matched": ["疫苗"],
            "source_id": "who", "source_name": "WHO News", "kind": "professional",
            "kind_label": "专业网站", "channel": "rss",
        }
        agent = _news_agent()
        with mock.patch.object(_news, "_choose_info_target", return_value=target), \
             mock.patch.object(_news._llm_providers, "call_llm", return_value="值得转发给同事。") as llm, \
             mock.patch.object(_news, "save_agent_memory"), \
             mock.patch.object(_news, "vector_db_add_entry"):
            memory_entry, log, url, query = _news.info_seek_and_store(
                agent, day=2, time_str="09:30", preferred_sites=["who.int"], config={}
            )
        self.assertIn("渠道：专业网站 · WHO News", memory_entry)
        self.assertIn("信息获取：feed", memory_entry)
        self.assertIn("想法：值得转发给同事。", memory_entry)
        self.assertIn("Source: 专业网站 · WHO News", log)
        self.assertEqual((url, query), ("https://who.int/news/1", ""))
        prompt = llm.call_args.args[0]
        self.assertIn("浏览自己常看的信息源", prompt)
        self.assertIn("渠道：专业网站 · WHO News", prompt)
        self.assertEqual(agent["memory"], [memory_entry])

    def test_legacy_modes_keep_memory_format(self):
        target = {"mode": "web_search", "query": "q", "engine": "ddg", "url": "https://a/1",
                  "title": "t", "content": "c", "score": 0.0, "matched": []}
        with mock.patch.object(_news, "_choose_info_target", return_value=target), \
             mock.patch.object(_news._llm_providers, "call_llm", return_value="ok"), \
             mock.patch.object(_news, "save_agent_memory"), \
             mock.patch.object(_news, "vector_db_add_entry"):
            memory_entry, log, _, _ = _news.info_seek_and_store(_news_agent(), day=1, time_str="10:00", config={})
        self.assertNotIn("渠道：", memory_entry)
        self.assertIn("Source: N/A", log)

    def test_preferred_sites_include_diet_news_and_trade_domains_only(self):
        sites = _news._build_agent_preferred_sites(_news_agent(), max_sites=20)
        self.assertIn("who.int", sites)
        self.assertNotIn("weibo.com", sites[:1])
        plain = _news._build_agent_preferred_sites({"id": 1, "job": "x"}, max_sites=20)
        self.assertNotIn("who.int", plain)


# ---------------------------------------------------------------------------
# 7. Plugin lifecycle
# ---------------------------------------------------------------------------

class TestPlugin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        reg = root / "info_sources.json"
        reg.write_text(json.dumps({"sources": [s.to_dict() for s in REGISTRY]}), encoding="utf-8")
        self.config = {
            "output_root": str(root / "output"),
            "news": {"enabled": True, "sources": {
                "enabled": True,
                "registry_path": str(reg),
                "feed_cache_path": str(root / "feed.json"),
                "ttl_hours": 6,
                "diet": {"max_sources": 3},
            }},
        }

    def tearDown(self):
        feed.set_runtime(None)
        self.tmp.cleanup()

    def _fetch(self, source, **kw):
        return [InfoItem(source.id, source.kind, f"{source.id} headline", url=f"https://{source.id}/1")]

    def test_agents_built_refreshes_feed_and_builds_diets(self):
        ctx = build_kernel(self.config, load_entry_points=False)
        plugin = InfoSourcesPlugin()
        plugin.setup(ctx)
        agents = [_agent("社区医生", agent_id=1), _agent("软件工程师", agent_id=2)]
        with mock.patch.object(channels, "fetch_source", side_effect=self._fetch) as fetch:
            ctx.bus.emit("agents.built", agents=agents, config=self.config)
        self.assertEqual(fetch.call_count, len(REGISTRY))
        rt = feed.runtime()
        self.assertIsNotNone(rt)
        self.assertEqual(rt.cache.items_for("who")[0].title, "who headline")
        self.assertEqual(rt.settings["registry_path"], self.config["news"]["sources"]["registry_path"])
        doctor = diet.diet_of(agents[0])
        coder = diet.diet_of(agents[1])
        self.assertEqual(len(doctor), 3)
        self.assertEqual(doctor[0]["source_id"], "who")
        self.assertEqual(coder[0]["source_id"], "jiqi")  # Chinese trade site beats English HN
        report = json.loads((Path(self.config["output_root"]) / "infosources" / "diets.json").read_text("utf-8"))
        self.assertEqual(report["1"]["job"], "社区医生")
        self.assertEqual(report["1"]["diet"], doctor)

        # Day start: still fresh, so no refetch; diets rebuilt from current state.
        agents[0]["state"]["platform_dependence"] = 0.95
        with mock.patch.object(channels, "fetch_source", side_effect=self._fetch) as fetch:
            ctx.bus.emit("on_day_start", day=2, agents=agents)
        self.assertEqual(fetch.call_count, 0)
        self.assertIn("weibo", [r["source_id"] for r in diet.diet_of(agents[0])])

        ctx.bus.emit("on_simulation_end")
        self.assertIsNone(feed.runtime())

    def test_disabled_registers_nothing(self):
        self.config["news"]["sources"]["enabled"] = False
        ctx = build_kernel(self.config, load_entry_points=False)
        InfoSourcesPlugin().setup(ctx)
        agents = [_agent("社区医生")]
        with mock.patch.object(channels, "fetch_source", side_effect=AssertionError("must not fetch")):
            ctx.bus.emit("agents.built", agents=agents, config=self.config)
        self.assertEqual(diet.diet_of(agents[0]), [])
        self.assertIsNone(feed.runtime())

    def test_empty_registry_degrades_quietly(self):
        self.config["news"]["sources"]["registry_path"] = str(Path(self.tmp.name) / "missing.json")
        ctx = build_kernel(self.config, load_entry_points=False)
        InfoSourcesPlugin().setup(ctx)
        agents = [_agent("社区医生")]
        with mock.patch.object(channels, "fetch_source", side_effect=AssertionError("must not fetch")):
            ctx.bus.emit("agents.built", agents=agents, config=self.config)
            ctx.bus.emit("on_day_start", day=1, agents=agents)
        self.assertEqual(diet.diet_of(agents[0]), [])
        self.assertIsNone(feed.runtime())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
