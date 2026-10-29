"""This file tests backend startup behavior when Celery is missing.

- test_celery_app_falls_back_when_celery_is_not_installed checks local startup can continue without the celery package.
"""

from __future__ import annotations

import builtins
import importlib.util
import sys
from pathlib import Path


def test_celery_app_falls_back_when_celery_is_not_installed(monkeypatch) -> None:
    module_path = Path(__file__).resolve().parents[3] / "src" / "fos" / "backend" / "celery_app.py"
    spec = importlib.util.spec_from_file_location("test_backend_celery_app", module_path)
    assert spec is not None
    assert spec.loader is not None

    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "celery":
            raise ModuleNotFoundError("No module named 'celery'")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    celery_app = module.celery_app
    assert getattr(celery_app, "is_available", False) is False
    assert hasattr(celery_app, "control")
    assert hasattr(celery_app.control, "revoke")
    celery_app.control.revoke("task-id", terminate=True)
