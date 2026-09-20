"""GAWorld: generative multi-agent simulator for urban social behavior.

The legacy flat layout still owns most of the codebase
(``generative_city_sim.py``, ``memory_store.py``, ``human_realism.py``…).
The ``gaworld`` package is the new home for cross-cutting concerns
introduced by the S1/S2 refactor:

* :mod:`gaworld.logging_setup` – structured logging
* :mod:`gaworld.env_loader`    – ``.env`` discovery
* :mod:`gaworld.settings`      – split legacy ``CONFIG`` assembly
* :mod:`gaworld.config`        – typed simulation configuration
* :mod:`gaworld.core.agent`    – ``Agent`` dataclass adapter
* :mod:`gaworld.io.web_scrape` – HTML / news content extraction
* :mod:`gaworld.llm.providers` – LLM provider wrappers and router

During the migration, legacy modules import from ``gaworld`` rather than
the other way around, so adopting one module at a time is safe.
"""

from __future__ import annotations

from pathlib import Path as _Path

from gaworld.env_loader import load_env_file as _load_env_file

__all__ = ["__version__"]

__version__ = "0.2.0"

# Load the project ``.env`` eagerly so LLM credentials (MINIMAX_API_KEY, …) and
# other settings are available to every entry point — including the legacy
# ``generative_city_sim.py`` which never called the loader itself. Resolved from
# this file's location so it works regardless of the current working directory.
# ``override=False`` (the default) means real environment variables still win.
_load_env_file(str(_Path(__file__).resolve().parent.parent / ".env"))
