# Locked tests for the persona-pool UNDERDRAW warning in
# scripts/launch_support.py (TASK-2160, RED phase; tests ONLY - no
# implementation lives here).
#
# WHAT THIS FILE DOES: pins the contract for the error the pool phase
# raises when products are STILL short of K accepted personas after every
# top-up retry round ("error: persona pools still incomplete after
# retries; short products: ..."). The live twin2k10 smoke crashed while
# BUILDING that message: the builder sliced each short product as if it
# were a plain string (name[:50]), but product entries are DICTS whose
# name lives in the "product" field (see scripts/twin2k10/serving.py
# write_products_file and data/configs/unblinding_products.json), so the
# message construction itself died with KeyError: slice(None, 50, None)
# and masked the real underdraw error.
#
# THE CONTRACT THESE TESTS PIN (TASK-2160):
#   1. When every retry round is exhausted with a product still short,
#      the pool phase raises SystemExit - not KeyError, not TypeError.
#      The abort itself stays (a still-short pool cannot be subsampled;
#      _subsample_pools would fail anyway), it must just stop crashing.
#   2. The message names each short product via its dict name field
#      (the "product" entry), so the operator sees WHICH pools are short.
#   3. Each name is truncated to 50 characters, exactly as the message
#      always did for plain-string entries.
#   4. Every short product appears in the message (comma-separated).
#
# WHY THERE IS NO STRING-PRODUCT TEST HERE: plain-string entries cannot
# reach this warning at all today - _short_products reads
# item["product"] and would raise TypeError long before the message is
# built. The string-entries-unchanged guarantee (str(entry)[:50]) binds
# the formatting the implementer adds; it is unverifiable through
# _generate_pools without inventing a helper API, which this RED phase
# must not do.
#
# All offline: the persona generator subprocess is stubbed to accept
# nothing, so every top-up round comes up short exactly like the live
# smoke with the model server down (exit 3, zero parsed personas).
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from launch_support import Settings, _generate_pools  # noqa: E402

# The product the live twin2k10 smoke crashed on (the synthetic single
# product its products file carries) plus two more, all in the exact
# schema every caller passes: category / product / regular_price.
TWIN2K10_PRODUCT = {
    "category": "grocery item",
    "product": "twin2k_respondent",
    "regular_price": 1.0,
}
CHIPS_PRODUCT = {
    "category": "Chips",
    "product": "Potato Chips",
    "regular_price": 2.99,
}
CANDY_PRODUCT = {
    "category": "Candy",
    "product": "Gummy Bears",
    "regular_price": 0.99,
}
LONG_NAME_PRODUCT = {
    "category": "Fruit Juice",
    "product": (
        "Capri Sun Variety Pack with Fruit Punch, Strawberry Kiwi "
        "& Pacific Cooler Juice Box Pouches"
    ),
    "regular_price": 9.43,
}


def _settings(tmp_path: Path) -> Settings:
    """One launch configuration pointed at a throwaway directory."""
    return Settings(
        model="vendor/model",
        port=8080,
        manager_url="http://127.0.0.1:9",  # nothing listens here; never called
        base_url="http://127.0.0.1:9",
        out=tmp_path,
        run_name="underdraw-probe",
        pool_seed=42,
        pool_overdraw=1.2,
        seed=7,
        draws=1,
        progress_every=10,
        products_path="data/configs/unblinding_products.json",
    )


def _stub_generator_accepts_nothing(commands: list) -> Callable[..., Any]:
    """A subprocess.run stand-in: the generator runs, accepts nothing.

    Mirrors the live crash: the model server was down, so every draw was
    skipped and generate_personas exited 3 (some product short) with zero
    accepted personas written to disk.
    """

    def fake_run(cmd: list, **_kwargs: Any) -> subprocess.CompletedProcess:
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode=3)

    return fake_run


def _underdraw_message(
    tmp_path: Path, products: list[dict[str, Any]], k: int
) -> tuple[str, list]:
    """Drive _generate_pools with a generator that never accepts a persona.

    Every retry round comes up short, so the underdraw warning fires.
    Returns (warning message, recorded generator commands). Fails if the
    pool phase raises anything but SystemExit, or loses the warning text.
    """
    import launch_support as support_module

    commands: list = []
    original_run = support_module.subprocess.run
    support_module.subprocess.run = _stub_generator_accepts_nothing(commands)
    try:
        with pytest.raises(SystemExit) as excinfo:
            _generate_pools(
                _settings(tmp_path),
                products,
                tmp_path / "products.json",
                tmp_path / "pools_work",
                k,
                lambda _text: None,
            )
    finally:
        support_module.subprocess.run = original_run
    message = str(excinfo.value)
    assert "persona pools still incomplete" in message, (
        f"expected the underdraw warning, got: {excinfo.value!r}"
    )
    return message, commands


def test_underdraw_warning_names_dict_products_instead_of_crashing():
    """The live twin2k10 smoke crash: after all retries with a generator
    that accepts nothing, the warning must name the short products from
    their dict entries instead of dying with KeyError on the slice."""
    with tempfile.TemporaryDirectory() as tmp:
        message, commands = _underdraw_message(
            Path(tmp), [dict(TWIN2K10_PRODUCT), dict(CHIPS_PRODUCT)], k=3
        )
    # The retries really ran (initial batch + per-product top-ups); the
    # failure is a clean underdraw report, not a silent skip.
    assert commands, "generator was never invoked"
    assert "twin2k_respondent" in message, f"short product missing from: {message!r}"
    assert "Potato Chips" in message, f"short product missing from: {message!r}"


def test_underdraw_warning_truncates_long_dict_name_to_50_characters():
    """A dict product whose name exceeds 50 chars is reported truncated to
    the first 50 characters - same as the message always did for strings."""
    long_name = LONG_NAME_PRODUCT["product"]
    with tempfile.TemporaryDirectory() as tmp:
        message, _commands = _underdraw_message(
            Path(tmp), [dict(LONG_NAME_PRODUCT)], k=3
        )
    assert message.endswith(long_name[:50]), (
        f"message must end with the name truncated to 50 chars, got: {message!r}"
    )
    assert long_name[50:] not in message, (
        f"message must not carry the name beyond 50 chars: {message!r}"
    )


def test_underdraw_warning_lists_every_short_dict_product():
    """Every short dict product appears in the warning, comma-separated,
    so the operator sees the full short list at a glance."""
    with tempfile.TemporaryDirectory() as tmp:
        message, _commands = _underdraw_message(
            Path(tmp),
            [dict(TWIN2K10_PRODUCT), dict(CHIPS_PRODUCT), dict(CANDY_PRODUCT)],
            k=3,
        )
    for name in ("twin2k_respondent", "Potato Chips", "Gummy Bears"):
        assert name in message, f"short product {name!r} missing from: {message!r}"
    assert ", " in message, f"short products must be comma-separated: {message!r}"
