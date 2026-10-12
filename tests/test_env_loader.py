"""Tests for gaworld.env_loader — lightweight .env loader."""

from __future__ import annotations

import os
import tempfile

import pytest

from gaworld.env_loader import _strip_quotes, load_default_env_files, load_env_file


@pytest.fixture(autouse=True)
def isolate_test_environment(monkeypatch):
    """Restore pre-existing environment values after every loader test."""
    for key in ("FOO", "EXPORTED", "GREETING", "EXISTING_VAR", "OVERRIDE_ME", "A", "B", "C"):
        monkeypatch.delenv(key, raising=False)


class TestStripQuotes:
    def test_no_quotes_returns_unchanged(self):
        assert _strip_quotes("hello") == "hello"

    def test_single_quotes_stripped(self):
        assert _strip_quotes("'hello world'") == "hello world"

    def test_double_quotes_stripped(self):
        assert _strip_quotes('"hello world"') == "hello world"

    def test_mismatched_quotes_not_stripped(self):
        assert _strip_quotes("'hello") == "'hello"

    def test_single_char_no_quotes(self):
        assert _strip_quotes("a") == "a"

    def test_quoted_empty(self):
        assert _strip_quotes('""') == ""


class TestLoadEnvFile:
    def test_missing_file_returns_empty(self):
        assert load_env_file("/nonexistent/.env.file") == {}

    def test_empty_file_returns_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            path = f.name
        try:
            assert load_env_file(path) == {}
        finally:
            os.unlink(path)

    def test_simple_key_value(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("FOO=bar\n")
            path = f.name
        try:
            result = load_env_file(path, override=True)
            assert result == {"FOO": "bar"}
            assert os.environ.get("FOO") == "bar"
        finally:
            os.environ.pop("FOO", None)
            os.unlink(path)

    def test_skips_comments_and_blanks(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("# comment\n\nFOO=bar\n")
            path = f.name
        try:
            result = load_env_file(path, override=True)
            assert result == {"FOO": "bar"}
        finally:
            os.environ.pop("FOO", None)
            os.unlink(path)

    def test_export_prefix_stripped(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("export EXPORTED=val\n")
            path = f.name
        try:
            result = load_env_file(path, override=True)
            assert result == {"EXPORTED": "val"}
        finally:
            os.environ.pop("EXPORTED", None)
            os.unlink(path)

    def test_line_without_equals_skipped(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("JUST_A_KEY\n")
            path = f.name
        try:
            result = load_env_file(path, override=True)
            assert result == {}
        finally:
            os.unlink(path)

    def test_quoted_value_stripped(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write('GREETING="hello world"\n')
            path = f.name
        try:
            result = load_env_file(path, override=True)
            assert result == {"GREETING": "hello world"}
        finally:
            os.environ.pop("GREETING", None)
            os.unlink(path)

    def test_does_not_override_existing_by_default(self):
        os.environ["EXISTING_VAR"] = "original"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("EXISTING_VAR=overwritten\n")
            path = f.name
        try:
            result = load_env_file(path)
            assert result == {}
            assert os.environ["EXISTING_VAR"] == "original"
        finally:
            os.environ.pop("EXISTING_VAR", None)
            os.unlink(path)

    def test_override_flag_works(self):
        os.environ["OVERRIDE_ME"] = "original"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("OVERRIDE_ME=new\n")
            path = f.name
        try:
            result = load_env_file(path, override=True)
            assert result == {"OVERRIDE_ME": "new"}
            assert os.environ["OVERRIDE_ME"] == "new"
        finally:
            os.environ.pop("OVERRIDE_ME", None)
            os.unlink(path)

    def test_multiple_lines(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("A=1\nB=2\nC=3\n")
            path = f.name
        try:
            result = load_env_file(path, override=True)
            assert result == {"A": "1", "B": "2", "C": "3"}
        finally:
            for k in ("A", "B", "C"):
                os.environ.pop(k, None)
            os.unlink(path)

    def test_path_is_none_returns_empty(self):
        assert load_env_file(None) == {}

    def test_path_is_empty_string_returns_empty(self):
        assert load_env_file("") == {}

    def test_oserror_on_unreadable_file(self, monkeypatch):
        def _bad_open(*args, **kwargs):
            raise OSError("permission denied")

        monkeypatch.setattr("builtins.open", _bad_open)
        # Create a real file path that exists so we pass the exists check
        with tempfile.NamedTemporaryFile(suffix=".env", delete=False) as f:
            path = f.name
        try:
            result = load_env_file(path, override=True)
            assert result == {}
        finally:
            os.unlink(path)


class TestLoadDefaultEnvFiles:
    def test_empty_iterable(self):
        assert load_default_env_files([]) == {}

    def test_multiple_files_merged(self):
        with (
            tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f1,
            tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f2,
        ):
            f1.write("A=1\nB=2\n")
            f2.write("C=3\n")
            path1, path2 = f1.name, f2.name
        try:
            result = load_default_env_files([path1, path2])
            assert result == {"A": "1", "B": "2", "C": "3"}
        finally:
            for k in ("A", "B", "C"):
                os.environ.pop(k, None)
            os.unlink(path1)
            os.unlink(path2)
