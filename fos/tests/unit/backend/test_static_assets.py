"""
This file tests how built frontend files are picked for delivery.

- test_choose_precompressed_variant_picks_brotli_first checks the smallest encoded file wins when the browser accepts Brotli.
- test_choose_precompressed_variant_falls_back_to_gzip checks gzip is used when Brotli is not allowed.
- test_choose_precompressed_variant_uses_plain_file_when_needed checks the original file is kept when no encoded file can be used.
"""

from __future__ import annotations

from pathlib import Path

from fos.backend.static_assets import choose_static_variant


def test_choose_precompressed_variant_picks_brotli_first(tmp_path: Path) -> None:
    source_file = tmp_path / "index.js"
    source_file.write_text("console.log('hello')", encoding="utf-8")
    source_file.with_suffix(".js.gz").write_bytes(b"gzip")
    source_file.with_suffix(".js.br").write_bytes(b"brotli")

    variant = choose_static_variant(source_file, "br, gzip")

    assert variant.path.suffix == ".br"
    assert variant.content_encoding == "br"


def test_choose_precompressed_variant_falls_back_to_gzip(tmp_path: Path) -> None:
    source_file = tmp_path / "index.css"
    source_file.write_text("body{}", encoding="utf-8")
    source_file.with_suffix(".css.gz").write_bytes(b"gzip")

    variant = choose_static_variant(source_file, "gzip, deflate")

    assert variant.path.suffix == ".gz"
    assert variant.content_encoding == "gzip"


def test_choose_precompressed_variant_uses_plain_file_when_needed(tmp_path: Path) -> None:
    source_file = tmp_path / "index.html"
    source_file.write_text("<html></html>", encoding="utf-8")

    variant = choose_static_variant(source_file, "")

    assert variant.path == source_file
    assert variant.content_encoding is None
