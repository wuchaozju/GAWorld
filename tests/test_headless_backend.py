"""Regression: GAWorld processes must never load a GUI matplotlib backend.

A Tk app created via TkAgg (auto-selected when ``DISPLAY`` is set) was later
destroyed by a cyclic-GC pass on the dashboard's HTTP worker thread, crashing
the interpreter with ``Tcl_AsyncDelete`` → SIGILL. ``gaworld/__init__.py``
selects the headless Agg backend before pyplot can be imported; these
subprocess tests prove the dashboard and plotting import chains stay
Tk-free in a fresh interpreter (matplotlib backend state is process-global).
"""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PROBE = textwrap.dedent("""
    import sys
    import gaworld                       # early backend selection happens here
    import gaworld.apps.dashboard_server  # dashboard import chain
    import matplotlib

    assert matplotlib.get_backend().lower() == "agg", matplotlib.get_backend()
    assert "tkinter" not in sys.modules and "_tkinter" not in sys.modules

    import gaworld.sim._plots            # the runtime plotting module
    import matplotlib.pyplot             # the plotting path itself

    assert matplotlib.get_backend().lower() == "agg", matplotlib.get_backend()
    assert "tkinter" not in sys.modules and "_tkinter" not in sys.modules
    print("OK")
    """)

PLOT_PROBE = textwrap.dedent("""
    import sys
    import gaworld
    import matplotlib
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(2, 2))
    ax.plot([0, 1], [0, 1])
    fig.savefig(sys.argv[1])
    plt.close(fig)

    assert matplotlib.get_backend().lower() == "agg", matplotlib.get_backend()
    assert "tkinter" not in sys.modules and "_tkinter" not in sys.modules
    print("OK")
    """)


def _child_env() -> dict:
    env = os.environ.copy()
    env.pop("MPLBACKEND", None)  # prove gaworld itself selects Agg
    return env


class HeadlessBackendTest(unittest.TestCase):
    def test_dashboard_and_plotting_chain_stay_agg_without_tk(self):
        proc = subprocess.run(
            [sys.executable, "-c", PROBE],
            cwd=REPO_ROOT,
            env=_child_env(),
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("OK", proc.stdout)

    def test_plot_output_written_headless(self):
        with tempfile.TemporaryDirectory() as tmp:
            png = os.path.join(tmp, "probe.png")
            proc = subprocess.run(
                [sys.executable, "-c", PLOT_PROBE, png],
                cwd=REPO_ROOT,
                env=_child_env(),
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("OK", proc.stdout)
            self.assertTrue(os.path.exists(png) and os.path.getsize(png) > 0)


if __name__ == "__main__":
    unittest.main()
