"""Tests for the JavaScript i18n module — static validation."""

from __future__ import annotations

import json
import os
import re
import subprocess
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_DASHBOARD_DIR = os.path.normpath(os.path.join(_HERE, "..", "site", "dashboard"))
_LOCALE_DIR = os.path.join(_DASHBOARD_DIR, "locales")


class TestJSModuleStaticChecks(unittest.TestCase):
    """Static analysis of the JS i18n module and locale files."""

    def test_i18n_js_exists(self):
        path = os.path.join(_DASHBOARD_DIR, "i18n.js")
        self.assertTrue(os.path.isfile(path), f"i18n.js not found at {path}")

    def test_i18n_js_contains_required_functions(self):
        path = os.path.join(_DASHBOARD_DIR, "i18n.js")
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("window.__", content)
        self.assertIn("window.__f", content)
        self.assertIn("window.setLocale", content)
        self.assertIn("window.getLocale", content)
        self.assertIn("window.applyTranslations", content)

    def test_i18n_js_has_locale_loading(self):
        path = os.path.join(_DASHBOARD_DIR, "i18n.js")
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("loadLocale", content)
        self.assertIn("fetch", content)

    def test_i18n_js_has_localstorage_persistence(self):
        path = os.path.join(_DASHBOARD_DIR, "i18n.js")
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("localStorage", content)
        self.assertIn("gaworld-lang", content)

    def test_i18n_js_syntax_valid(self):
        path = os.path.join(_DASHBOARD_DIR, "i18n.js")
        try:
            result = subprocess.run(
                ["node", "--check", path],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(0, result.returncode, f"node --check failed:\n{result.stderr}")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self.skipTest("Node.js not available for syntax check")

    def test_app_js_imports_i18n(self):
        html_path = os.path.join(_DASHBOARD_DIR, "index.html")
        with open(html_path, encoding="utf-8") as fh:
            content = fh.read()
        scripts = re.findall(r'<script[^>]*src="([^"]*)"', content)
        i18n_idx = next((i for i, s in enumerate(scripts) if "i18n.js" in s), None)
        app_idx = next((i for i, s in enumerate(scripts) if "app.js" in s), None)
        self.assertIsNotNone(i18n_idx, "i18n.js script tag not found in index.html")
        self.assertIsNotNone(app_idx, "app.js script tag not found in index.html")
        self.assertLess(i18n_idx, app_idx, "i18n.js must be loaded before app.js")


class TestLocaleFilesJS(unittest.TestCase):
    """Validate the locale JSON files."""

    def test_en_json_valid(self):
        path = os.path.join(_LOCALE_DIR, "en.json")
        self.assertTrue(os.path.isfile(path))
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIsInstance(data, dict)

    def test_zh_json_valid(self):
        path = os.path.join(_LOCALE_DIR, "zh-CN.json")
        self.assertTrue(os.path.isfile(path))
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIsInstance(data, dict)

    def test_locale_files_have_same_keys(self):
        with open(os.path.join(_LOCALE_DIR, "en.json"), encoding="utf-8") as f:
            en = json.load(f)
        with open(os.path.join(_LOCALE_DIR, "zh-CN.json"), encoding="utf-8") as f:
            zh = json.load(f)
        self.assertEqual(set(en.keys()), set(zh.keys()))


if __name__ == "__main__":
    unittest.main()
