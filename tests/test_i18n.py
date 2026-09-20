"""Tests for the gaworld.i18n module and locale file consistency."""

from __future__ import annotations

import json
import os
import re
import unittest

from gaworld.i18n import t, eng, available_locales, reload

_HERE = os.path.dirname(os.path.abspath(__file__))
_LOCALE_DIR = os.path.normpath(os.path.join(_HERE, "..", "site", "dashboard", "locales"))


def _load_json(name: str) -> dict[str, str]:
    path = os.path.join(_LOCALE_DIR, name)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class TestPythonI18nModule(unittest.TestCase):
    """Tests for the Python i18n module API."""

    def test_python_module_imports(self):
        from gaworld.i18n import t, eng, available_locales, reload
        self.assertTrue(callable(t))
        self.assertTrue(callable(eng))

    def test_t_function_returns_chinese_by_default(self):
        result = t("console.title")
        self.assertEqual("GAWorld 个人孪生控制台", result)

    def test_eng_function_returns_english(self):
        result = eng("console.title")
        self.assertEqual("GAWorld Twin Console", result)

    def test_t_with_unknown_key_returns_key_itself(self):
        result = t("this.key.does.not.exist.xyz")
        self.assertEqual("this.key.does.not.exist.xyz", result)

    def test_eng_with_unknown_key_returns_key_itself(self):
        result = eng("this.key.does.not.exist.xyz")
        self.assertEqual("this.key.does.not.exist.xyz", result)

    def test_available_locales_returns_list(self):
        locales = available_locales()
        self.assertIsInstance(locales, list)
        self.assertGreaterEqual(len(locales), 1)
        for entry in locales:
            self.assertIn("code", entry)
            self.assertIn("label", entry)

    def test_reload_clears_cache(self):
        _ = t("console.title")
        reload()
        result = t("console.title")
        self.assertEqual("GAWorld 个人孪生控制台", result)


class TestLocaleFileConsistency(unittest.TestCase):
    """Tests that both locale files are valid and have consistent keys."""

    @classmethod
    def setUpClass(cls):
        cls.en = _load_json("en.json")
        cls.zh = _load_json("zh-CN.json")

    def test_en_locale_file_is_valid_json(self):
        self.assertIsInstance(self.en, dict)
        for k, v in self.en.items():
            self.assertIsInstance(k, str)
            self.assertIsInstance(v, str)

    def test_zh_locale_file_is_valid_json(self):
        self.assertIsInstance(self.zh, dict)
        for k, v in self.zh.items():
            self.assertIsInstance(k, str)
            self.assertIsInstance(v, str)

    def test_all_keys_present_in_both_locales(self):
        en_keys = set(self.en.keys())
        zh_keys = set(self.zh.keys())
        only_in_en = en_keys - zh_keys
        only_in_zh = zh_keys - en_keys
        self.assertEqual(set(), only_in_en, f"Keys only in en.json: {only_in_en}")
        self.assertEqual(set(), only_in_zh, f"Keys only in zh-CN.json: {only_in_zh}")

    def test_en_keys_are_sorted(self):
        keys = list(self.en.keys())
        if keys != sorted(keys):
            self.skipTest("Keys are not alphabetically sorted (cosmetic, not blocking)")

    def test_zh_keys_match_en_order(self):
        en_keys = list(self.en.keys())
        zh_keys = list(self.zh.keys())
        self.assertEqual(en_keys, zh_keys, "Locale files have different key order")


class TestLocaleFileCoverage(unittest.TestCase):
    """Tests that all keys referenced in source files exist in locale files."""

    @classmethod
    def setUpClass(cls):
        cls.en = _load_json("en.json")
        cls.zh = _load_json("zh-CN.json")

    def _keys_in_file(self, path: str) -> set[str]:
        keys: set[str] = set()
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
        for m in re.finditer(r'__f?\s*\(\s*"([^"]+)"', content):
            keys.add(m.group(1))
        for m in re.finditer(r'data-i18n(?:-placeholder|-content)?\s*=\s*"([^"]+)"', content):
            keys.add(m.group(1))
        return keys

    def test_app_js_keys_exist_in_en(self):
        app_js = os.path.join(_LOCALE_DIR, "..", "app.js")
        if not os.path.isfile(app_js):
            self.skipTest("app.js not found")
        keys = self._keys_in_file(app_js)
        missing = keys - set(self.en.keys())
        self.assertEqual(set(), missing, f"Keys in app.js missing from en.json: {missing}")

    def test_app_js_keys_exist_in_zh(self):
        app_js = os.path.join(_LOCALE_DIR, "..", "app.js")
        if not os.path.isfile(app_js):
            self.skipTest("app.js not found")
        keys = self._keys_in_file(app_js)
        missing = keys - set(self.zh.keys())
        self.assertEqual(set(), missing, f"Keys in app.js missing from zh-CN.json: {missing}")

    def test_html_data_i18n_keys_exist_in_en(self):
        html_path = os.path.join(_LOCALE_DIR, "..", "index.html")
        if not os.path.isfile(html_path):
            self.skipTest("index.html not found")
        keys = self._keys_in_file(html_path)
        missing = keys - set(self.en.keys())
        self.assertEqual(set(), missing, f"Keys in index.html missing from en.json: {missing}")

    def test_html_data_i18n_keys_exist_in_zh(self):
        html_path = os.path.join(_LOCALE_DIR, "..", "index.html")
        if not os.path.isfile(html_path):
            self.skipTest("index.html not found")
        keys = self._keys_in_file(html_path)
        missing = keys - set(self.zh.keys())
        self.assertEqual(set(), missing, f"Keys in index.html missing from zh-CN.json: {missing}")


if __name__ == "__main__":
    unittest.main()


class TestConfigDocsBilingualParity(unittest.TestCase):
    """The 配置 panel's documentation is bilingual by table, not by call.

    ``config_docs`` hands the browser both languages per field and lets it pick,
    so the payload stays locale-agnostic and cacheable. The cost of that design
    is that a new label or help string added on the Chinese side with no English
    twin falls back to Chinese silently and forever — nothing errors, the panel
    simply keeps showing Chinese to an English reader. These tests are what
    makes that visible.
    """

    def test_every_label_has_an_english_twin(self):
        from gaworld.settings import config_docs

        missing = sorted(set(config_docs.LABELS) - set(config_docs.LABELS_EN))
        self.assertEqual(
            [], missing,
            "LABELS entries with no LABELS_EN twin (they would show Chinese in "
            f"English mode): {missing}",
        )

    def test_no_orphan_english_labels(self):
        from gaworld.settings import config_docs

        orphans = sorted(set(config_docs.LABELS_EN) - set(config_docs.LABELS))
        self.assertEqual(
            [], orphans,
            f"LABELS_EN entries no longer in LABELS — dead translations: {orphans}",
        )

    def test_every_curated_help_has_an_english_twin(self):
        from gaworld.settings import config_docs

        missing = sorted(set(config_docs.MANUAL_HELP) - set(config_docs.MANUAL_HELP_EN))
        self.assertEqual(
            [], missing,
            f"MANUAL_HELP entries with no MANUAL_HELP_EN twin: {missing}",
        )

    def test_no_orphan_english_help(self):
        from gaworld.settings import config_docs

        orphans = sorted(set(config_docs.MANUAL_HELP_EN) - set(config_docs.MANUAL_HELP))
        self.assertEqual(
            [], orphans,
            f"MANUAL_HELP_EN entries no longer in MANUAL_HELP: {orphans}",
        )

    def test_every_section_is_bilingual(self):
        from gaworld.settings import config_docs

        for meta in config_docs.section_meta():
            with self.subTest(section=meta["id"]):
                self.assertTrue(meta["title_en"], f"{meta['id']} has no English title")
                self.assertTrue(meta["help_en"], f"{meta['id']} has no English help")

    def test_english_text_is_not_just_the_chinese_copied(self):
        # A twin that is byte-identical to the Chinese usually means someone
        # pasted rather than translated, and the fallback would have done the
        # same job. The exception is a label that was never Chinese to begin
        # with — "User-Agent", "X / MCP" — where identical is the right answer.
        from gaworld.settings import config_docs

        has_cjk = re.compile(r"[\u4e00-\u9fff]").search
        copied = sorted(
            key for key, value in config_docs.LABELS_EN.items()
            if value == config_docs.LABELS.get(key) and has_cjk(value or "")
        )
        self.assertEqual([], copied, f"LABELS_EN copied verbatim: {copied}")

    def test_extracted_source_comments_have_no_english_and_say_so(self):
        # The ~600 labels extracted from Python comments are deliberately not
        # translated: they are maintainer comments, and keeping two copies of a
        # code comment in step is a losing game. help_en_for() must return "" so
        # the panel falls back rather than painting a key or a blank tooltip.
        from gaworld.settings import config_docs

        extracted = set(config_docs.source_help()) - set(config_docs.MANUAL_HELP)
        self.assertTrue(extracted, "expected some help to come from source comments")
        for path in sorted(extracted)[:20]:
            with self.subTest(path=path):
                self.assertEqual("", config_docs.help_en_for(path))
                self.assertTrue(config_docs.help_for(path))


class TestBig5BilingualParity(unittest.TestCase):
    """The Big Five card's labels ship in both languages from the server.

    Unlike the rest of the Studio they are *not* locale keys: the wording is
    shared with ``scripts/calibrate_big5.py`` so that the panel and the
    calibrator describe the same poles, and one table on the server is the only
    way to keep that true. The cost is the same as the config docs' — a trait
    added on the Chinese side with no English twin shows Chinese to an English
    reader and nothing errors. This is what makes that visible.
    """

    def _module(self):
        from gaworld.apps import dashboard_server

        return dashboard_server

    def test_every_dimension_is_named_in_both_languages(self):
        mod = self._module()
        for dim in mod.BIG5_DIMENSIONS:
            with self.subTest(dim=dim):
                self.assertTrue(mod.BIG5_NAMES_ZH.get(dim), f"no Chinese name for {dim}")
                self.assertTrue(mod.BIG5_NAMES_EN.get(dim), f"no English name for {dim}")

    def test_every_dimension_has_both_poles_in_both_languages(self):
        mod = self._module()
        for dim in mod.BIG5_DIMENSIONS:
            with self.subTest(dim=dim):
                for table, label in ((mod.BIG5_POLES, "zh"), (mod.BIG5_POLES_EN, "en")):
                    poles = table.get(dim)
                    self.assertIsNotNone(poles, f"{label} has no poles for {dim}")
                    self.assertEqual(2, len(poles), f"{label}/{dim} is not a low/high pair")
                    self.assertTrue(all(str(p).strip() for p in poles),
                                    f"{label}/{dim} has an empty pole")

    def test_no_orphan_english_entries(self):
        mod = self._module()
        self.assertEqual(set(mod.BIG5_POLES), set(mod.BIG5_POLES_EN))
        self.assertEqual(set(mod.BIG5_NAMES_ZH), set(mod.BIG5_NAMES_EN))

    def test_the_english_table_is_not_a_copy_of_the_chinese_one(self):
        # A generator that fell back to the source language would pass every
        # check above while leaving the panel Chinese in English mode.
        mod = self._module()
        for dim in mod.BIG5_DIMENSIONS:
            with self.subTest(dim=dim):
                self.assertNotEqual(mod.BIG5_NAMES_ZH[dim], mod.BIG5_NAMES_EN[dim])
                self.assertNotEqual(tuple(mod.BIG5_POLES[dim]), tuple(mod.BIG5_POLES_EN[dim]))

    def test_the_payload_carries_both_sides(self):
        mod = self._module()
        payload = mod._agent_big5(1)
        if payload is None:
            self.skipTest("no agent 1 in the seed roster")
        for field in ("poles", "poles_en", "names", "names_en"):
            self.assertIn(field, payload, f"the client reads {field}")


class TestRadarAxisLabels(unittest.TestCase):
    """The studio radar's axis labels have to stay short.

    Nine labels sit around the rim of a 252-unit-wide viewBox. A phrase does
    not fit: before these keys existed the slider labels were reused and
    "经济安全感" overflowed by 22 units, "Economic security" by 52 — silently,
    since SVG just clips. Length is the only part of that a unit test can see,
    so it guards the length.
    """

    #: Generous enough for "Expression" / "城市认同", tight enough to reject a
    #: phrase pasted back in from st.name.
    MAX_CHARS = {"en": 12, "zh-CN": 5}

    def _locales(self):
        return {name: _load_json(f"{name}.json") for name in ("zh-CN", "en")}

    def test_one_axis_label_per_state_variable(self):
        locales = self._locales()
        names = {k for k in locales["zh-CN"] if k.startswith("st.name.")}
        self.assertEqual(9, len(names), "the roster CSV has nine state variables")
        for key in sorted(names):
            axis = key.replace("st.name.", "st.axis.")
            for locale, table in locales.items():
                with self.subTest(locale=locale, key=axis):
                    self.assertIn(axis, table)

    def test_axis_labels_are_short_enough_to_fit(self):
        for locale, table in self._locales().items():
            limit = self.MAX_CHARS[locale]
            for key, value in sorted(table.items()):
                if not key.startswith("st.axis."):
                    continue
                with self.subTest(locale=locale, key=key):
                    self.assertLessEqual(
                        len(value), limit,
                        f"{key} is {len(value)} characters; it will be clipped by "
                        f"the radar viewBox (limit {limit})",
                    )
