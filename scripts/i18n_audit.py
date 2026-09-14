#!/usr/bin/env python3
"""Report how much of the dashboard's JS-rendered UI text is translatable.

The console's language switch only reaches strings that go through ``__()`` /
``__f()`` or a ``data-i18n`` attribute. Anything a script writes as a literal
stays in whatever language it was typed in, which is why English mode still
renders a mostly-Chinese UI on the JS-heavy pages.

This counts what is left, per file, so the conversion has a burn-down rather
than a vibe. Run it from the repo root::

    python scripts/i18n_audit.py            # summary table
    python scripts/i18n_audit.py worlds.js  # every remaining literal in a file

A literal is "remaining" when a Chinese string appears directly in the source
rather than as a locale key. Comments, the locale files themselves, the test
files and i18n.js are all skipped.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_DIR = REPO_ROOT / "site" / "dashboard"
LOCALES = JS_DIR / "locales"

#: A run of Chinese text. Matching the *text* rather than a quoted string is
#: deliberate: most of this UI is built from multi-line template literals, and
#: a markup line like ``<h2 class="section-title">身份</h2>`` has no quote after
#: the Chinese, so a quote-delimited pattern scored it zero. Locale keys are
#: ASCII, so anything matched here is still a hardcoded literal.
LITERAL = re.compile(r"[一-鿿][一-鿿0-9A-Za-z，。、；：！？“”‘’（）《》「」【】…—·％\-/ ]*")
SKIP = {"i18n.js"}

#: Not every Chinese literal is untranslated interface text. Content *about*
#: Chinese material — the docs catalogue's titles and summaries, say — is data,
#: and pretending otherwise would make this burn-down lie. Mark such a region::
#:
#:     /* i18n-exempt-start: these name Chinese documents in the repo */
#:     ...
#:     /* i18n-exempt-end */
EXEMPT_START = "i18n-exempt-start"
EXEMPT_END = "i18n-exempt-end"


def literals(path: Path) -> list[tuple[int, str]]:
    """Chinese string literals in ``path``, as ``(line number, text)``.

    Skips comments and anything inside an ``i18n-exempt`` region.
    """
    found: list[tuple[int, str]] = []
    exempt = False
    state = _Scanner()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if EXEMPT_START in line:
            exempt = True
            continue
        if EXEMPT_END in line:
            exempt = False
            continue
        code = state.strip_comments(line)
        if exempt or not code.strip():
            continue
        found.extend((number, match.group(0).strip()) for match in LITERAL.finditer(code))
    return found


class _Scanner:
    """Strips JS comments while remembering block-comment state across lines.

    Counting ``/*`` per line is not good enough: ``// the /api/analytics/*
    payloads`` opens a block comment that never closes, and everything after it
    silently stops being counted. Under-reporting is the worst failure mode for
    a burn-down, so this walks the characters and tracks string literals too —
    a ``"//"`` inside a string is not a comment.
    """

    def __init__(self) -> None:
        self.in_block = False

    def strip_comments(self, line: str) -> str:
        out: list[str] = []
        quote: str | None = None
        index = 0
        while index < len(line):
            char = line[index]
            pair = line[index:index + 2]
            if self.in_block:
                if pair == "*/":
                    self.in_block = False
                    index += 2
                    continue
                index += 1
                continue
            if quote:
                out.append(char)
                if char == "\\":
                    if index + 1 < len(line):
                        out.append(line[index + 1])
                    index += 2
                    continue
                if char == quote:
                    quote = None
                index += 1
                continue
            if char in "\"'`":
                quote = char
                out.append(char)
                index += 1
                continue
            if pair == "//":
                break
            if pair == "/*":
                self.in_block = True
                index += 2
                continue
            out.append(char)
            index += 1
        return "".join(out)


def exempt_count(path: Path) -> int:
    """How many literals a file has deliberately set aside, for reporting."""
    text = path.read_text(encoding="utf-8")
    if EXEMPT_START not in text:
        return 0
    total = 0
    exempt = False
    state = _Scanner()
    for line in text.splitlines():
        if EXEMPT_START in line:
            exempt = True
            continue
        if EXEMPT_END in line:
            exempt = False
            continue
        code = state.strip_comments(line)
        if exempt:
            total += len(LITERAL.findall(code))
    return total


def sources() -> list[Path]:
    return sorted(
        p for p in JS_DIR.glob("*.js")
        if not p.name.endswith(".test.js") and p.name not in SKIP
    )


def locale_keys() -> dict[str, int]:
    return {
        path.stem: len(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(LOCALES.glob("*.json"))
    }


def main() -> int:
    if len(sys.argv) > 1:
        target = JS_DIR / sys.argv[1]
        if not target.exists():
            print(f"no such file: {target}")
            return 1
        rows = literals(target)
        for number, text in rows:
            print(f"{number:5}  {text}")
        print(f"\n{len(rows)} remaining in {target.name}")
        return 0

    rows = [(p.name, len(literals(p)), exempt_count(p)) for p in sources()]
    rows.sort(key=lambda r: -r[1])
    total = sum(n for _, n, _ in rows)
    exempt_total = sum(e for _, _, e in rows)
    width = max(len(name) for name, _, _ in rows)

    print(f"{'file':<{width}}  remaining     exempt")
    print("-" * (width + 22))
    for name, count, exempt in rows:
        if count or exempt:
            print(f"{name:<{width}}  {count:>9}  {exempt or '':>9}")
    print("-" * (width + 22))
    print(f"{'TOTAL':<{width}}  {total:>9}  {exempt_total or '':>9}")

    keys = locale_keys()
    print("\nlocale files: " + ", ".join(f"{k} ({v} keys)" for k, v in keys.items()))
    if len(set(keys.values())) > 1:
        print("  WARNING: locale files disagree on key count")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
