"""The CI lint ratchet: changed files may not get worse.

Runs ``scripts/lint_ratchet.py`` against a throwaway git repository with its
own ruff config: a new finding in a changed file fails, an old unformatted
file may be edited without being reformatted, a new file must be formatted,
and the repo totals may not rise above the recorded baseline.
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import unittest

from scripts import lint_ratchet


def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class LintRatchetTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        original = lint_ratchet.ROOT
        self.addCleanup(setattr, lint_ratchet, "ROOT", original)
        self._write("pyproject.toml", '[tool.ruff]\nline-length = 100\n[tool.ruff.lint]\nselect = ["F"]\n')
        self._write("a.py", "import os\n\nX = 1\n")  # one finding: unused import
        self._write("legacy.py", "x=1\n")  # unformatted on the base
        os.makedirs(os.path.join(self.root, "scripts"))
        _git(self.root, "init", "-q")
        _git(self.root, "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
        _git(self.root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")

    def _write(self, name, text):
        with open(os.path.join(self.root, name), "w", encoding="utf-8") as fh:
            fh.write(text)

    def _ratchet(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = lint_ratchet.main(["--root", self.root, *args])
        return code, out.getvalue()

    def test_nothing_changed_passes(self):
        self.assertEqual(self._ratchet()[0], 0)

    def test_a_new_finding_in_a_changed_file_fails(self):
        self._write("a.py", "import os\nimport sys\n\nX = 1\n")
        code, out = self._ratchet()
        self.assertEqual(code, 1)
        self.assertIn("a.py: 2 ruff findings, was 1", out)

    def test_fixing_old_findings_passes(self):
        self._write("a.py", "X = 1\n")
        self.assertEqual(self._ratchet()[0], 0)

    def test_an_old_unformatted_file_may_be_edited_without_reformatting(self):
        self._write("legacy.py", "x=1\ny=2\n")
        self.assertEqual(self._ratchet()[0], 0)

    def test_a_new_file_must_be_clean_and_formatted(self):
        self._write("new.py", "import os\nz=3\n")
        code, out = self._ratchet()
        self.assertEqual(code, 1)
        self.assertIn("new.py: 1 ruff findings, was 0", out)
        self.assertIn("new.py: not formatted", out)

    def test_repo_totals_may_not_rise_above_the_baseline(self):
        self.assertEqual(self._ratchet("--update-baseline")[0], 0)
        _git(self.root, "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
        _git(self.root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "baseline")
        # a finding added in a file the diff does not see (committed) still counts in the total
        self._write("b.py", "import json\n")
        _git(self.root, "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
        _git(self.root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "sneak")
        code, out = self._ratchet()
        self.assertEqual(code, 1)
        self.assertIn("repo ruff_findings rose from 1 to 2", out)


if __name__ == "__main__":
    unittest.main()
