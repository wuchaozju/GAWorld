"""The feature registry (docs/features.toml) and the lists it must agree with.

Adding a subsystem used to mean updating about a dozen hand-kept lists, and
they drifted (the map said 79 features while listing 89; two docs never made
it into the docs panel). The registry is now the one list of features; this
test holds the others to it:

* ``docs/FEATURE_MAP.html`` is generated from it and must be up to date;
* every registry feature points at a row (or ``##`` heading) of
  ``docs/FEATURES.md``, and every FEATURES.md row is on the map;
* every tutorial the registry links is listed in the docs panel
  (``site/dashboard/docs.js``), in both READMEs and in FEATURES.md.

Config sections, locale parity and the docs panel's own files have their own
tests (``test_dashboard_family``, ``test_i18n*``, ``test_dashboard_docs``).
"""

from __future__ import annotations

import os
import re
import unittest

from scripts import build_feature_map as fm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def _features_md_titles():
    """(table rows' first cells, ## headings) of docs/FEATURES.md."""
    rows, headings = [], []
    for line in _read("docs", "FEATURES.md").splitlines():
        if line.startswith("## "):
            headings.append(line[3:].strip())
        elif line.startswith("| ") and not line.startswith("| 功能特性 |"):
            rows.append(line.split("|")[1].strip())
    return rows, headings


class FeatureRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = fm.load_registry()
        cls.features = list(fm.features(cls.registry))

    def test_the_registry_is_well_formed(self):
        for axis in self.registry["axis"]:
            for key in ("id", "name", "emoji", "tagline"):
                self.assertTrue(axis.get(key), f"axis {axis.get('name')!r} has no {key}")
            self.assertTrue(axis["group"], f"axis {axis['name']} has no groups")
            names = [f["name"] for g in axis["group"] for f in g["feature"]]
            self.assertEqual(len(names), len(set(names)), f"duplicate feature names under {axis['name']}")
        for axis, group, feature in self.features:
            where = f"{axis['name']} / {group['name']} / {feature.get('name')}"
            self.assertTrue(feature.get("name") and feature.get("desc"), where)
            self.assertTrue(feature.get("features"), f"{where}: no FEATURES.md row")

    def test_the_feature_map_is_generated_from_the_registry(self):
        current = _read("docs", "FEATURE_MAP.html")
        self.assertEqual(
            fm.render(self.registry, current),
            current,
            "docs/FEATURE_MAP.html is out of date: python scripts/build_feature_map.py",
        )

    def test_mind_map_labels_cannot_break_mermaid(self):
        for _axis, group, feature in self.features:
            for label in (
                fm.mind_label(group["name"]),
                fm.mind_label(feature.get("mind") or feature["name"]),
            ):
                self.assertTrue(label)
                self.assertIsNone(re.search(r"[()\[\]{}]", label), label)

    def test_every_feature_points_at_a_features_md_entry(self):
        rows, headings = _features_md_titles()
        known = set(rows) | set(headings)
        for _axis, _group, feature in self.features:
            for title in feature["features"]:
                self.assertIn(title, known, f"{feature['name']}: no FEATURES.md row or heading {title!r}")

    def test_every_features_md_row_is_on_the_map(self):
        rows, _headings = _features_md_titles()
        on_map = {title for _a, _g, f in self.features for title in f["features"]}
        missing = [row for row in rows if row not in on_map]
        self.assertEqual(missing, [], "FEATURES.md rows with no feature in docs/features.toml")

    def test_linked_tutorials_are_listed_everywhere(self):
        docs_panel = _read("site", "dashboard", "docs.js")
        lists = {
            "README.md": _read("README.md"),
            "README.zh-CN.md": _read("README.zh-CN.md"),
            "docs/FEATURES.md": _read("docs", "FEATURES.md"),
        }
        for _axis, _group, feature in self.features:
            doc = feature.get("doc")
            if not doc:
                continue
            self.assertTrue(
                os.path.exists(os.path.join(ROOT, doc)), f"{feature['name']}: {doc} does not exist"
            )
            self.assertIn(f'"/{doc}"', docs_panel, f"{doc} is not in the docs panel (site/dashboard/docs.js)")
            for name, text in lists.items():
                self.assertIn(os.path.basename(doc), text, f"{doc} is not linked from {name}")


if __name__ == "__main__":
    unittest.main()
