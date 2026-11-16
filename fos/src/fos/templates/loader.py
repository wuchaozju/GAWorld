"""Template loader for the generic template system.

Loads simulation templates from JSON/YAML files.
Legacy template loader (loading only, no scene building).

Contains: TemplateLoader
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from fos.i18n import T

from fos.templates.schema import GenericTemplate


class TemplateLoader:
    """Loads simulation templates from files.

    Attributes:
        template_dir: Optional directory path for template files.
    """

    def __init__(self, template_dir: str | Path | None = None):
        self.template_dir = Path(template_dir) if template_dir else None

    def load_from_file(self, path: str | Path) -> GenericTemplate:
        """Load a template from a JSON or YAML file."""
        path = Path(path)
        if not path.is_absolute() and self.template_dir:
            path = self.template_dir / path
        if not path.exists():
            raise FileNotFoundError(f"Template file not found: {path}")

        suffix = path.suffix.lower()
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        if suffix == ".json":
            data = json.loads(content)
        elif suffix in (".yaml", ".yml"):
            data = yaml.safe_load(content)
        else:
            raise ValueError(T("Unsupported file format: {suffix}", suffix=suffix))

        return self.load_from_dict(data)

    def load_from_dict(self, data: dict[str, Any]) -> GenericTemplate:
        """Load a template from a dictionary."""
        try:
            return GenericTemplate.model_validate(data)
        except Exception as e:
            raise ValueError(T("Invalid template data: {e}", e=str(e))) from e

    def load_from_directory(self, directory: str | Path) -> list[GenericTemplate]:
        """Load all templates from a directory."""
        dir_path = Path(directory)
        if not dir_path.is_absolute() and self.template_dir:
            dir_path = self.template_dir / dir_path
        if not dir_path.exists() or not dir_path.is_dir():
            raise FileNotFoundError(f"Directory not found: {dir_path}")

        templates = []
        for pattern in ("*.json", "*.yaml", "*.yml"):
            for file_path in dir_path.glob(pattern):
                try:
                    templates.append(self.load_from_file(file_path))
                except Exception as e:
                    print(f"Warning: Failed to load {file_path}: {e}")
        return templates
