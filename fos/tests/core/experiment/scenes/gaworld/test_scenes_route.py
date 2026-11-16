"""This file tests the scenes route behavior for GAWorld-safe listing.

- test_list_scenes_route_returns_gaworld_without_server_error checks the route stays healthy when gaworld_scene is registered.
- test_scene_config_template_builds_gaworld_without_legacy_constructor checks GAWorld uses experiment-style config building.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from litestar import Litestar
from litestar.testing import TestClient

from fos.core.experiment.scenes.gaworld.scene import GAWorldScene


def _load_scenes_module():
    module_path = (
        Path(__file__).resolve().parents[5]
        / "src"
        / "fos"
        / "backend"
        / "api"
        / "routes"
        / "scenes.py"
    )
    spec = importlib.util.spec_from_file_location("test_scenes_route_module", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_list_scenes_route_returns_gaworld_without_server_error() -> None:
    scenes_module = _load_scenes_module()
    app = Litestar(route_handlers=[scenes_module.router])

    with TestClient(app=app) as client:
        response = client.get("/scenes")

    assert response.status_code == 200
    payload = response.json()
    assert any(item["type"] == "gaworld_scene" for item in payload)


def test_scene_config_template_builds_gaworld_without_legacy_constructor() -> None:
    scenes_module = _load_scenes_module()
    template = scenes_module.scene_config_template("gaworld_scene", GAWorldScene)

    assert template["type"] == "gaworld_scene"
    assert template["name"] == "GAWorldScene"
    assert template["config_schema"]["config"]["scenario_id"] == "gaworld_scene"
