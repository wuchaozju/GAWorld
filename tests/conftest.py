"""Isolate the test suite from the developer's local dashboard config.

``gaworld.settings`` merges ``dashboard_config.json`` into ``CONFIG`` at import
time, so whatever city / horizon / randomness happens to be selected in the
dashboard panel silently becomes the configuration the tests run against. That
made results depend on what the developer last clicked: a ``"city": "wuzhen"``
sitting in that file was enough to turn the long-horizon E2E runs red, while CI
— where the file is untouched — stayed green.

The flag has to be set before anything imports ``gaworld.settings``, which is
why this runs at conftest import time rather than from a fixture. Exporting
``GAWORLD_IGNORE_LOCAL_CONFIG=0`` beforehand opts back in, for the rare case of
wanting to reproduce a run with the panel's own settings.
"""

import os

os.environ.setdefault("GAWORLD_IGNORE_LOCAL_CONFIG", "1")
