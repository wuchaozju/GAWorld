"""On-disk layout and manifest for a city bundle.

Every city lives in its own directory so that "create a city" is a single,
reversible filesystem operation and two cities can never clobber each other::

    data/cities/<slug>/
        city.json          manifest (this module owns the schema)
        citymap.md         virtual map spec — always written
        map.geojson        real OSM bundle — only when the fetch succeeded
        environment.json    environment config fragment
        agents.csv         population state (utf-8-sig, simulator contract)
        profiles.md        population profiles

The registry is a directory scan rather than an index file: an index would be a
second source of truth that silently drifts the first time somebody copies or
deletes a folder by hand.
"""

from __future__ import annotations

import json
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Where bundles live, relative to the project root.
CITIES_DIRNAME = "data/cities"

#: Where a city's *runs* land, relative to the project root — memory, logs,
#: diaries, charts, the economy ledger. Deliberately outside the bundle: a
#: bundle is the city's definition and should stay copyable between machines
#: without dragging along somebody's twenty years of accumulated agent memory.
#: ``gaworld.city.config`` owns the mapping of individual config keys into it.
RUNS_DIRNAME = "output/cities"

MANIFEST_NAME = "city.json"
SCHEMA_VERSION = "1.0"

#: Fixed filenames inside a bundle. Callers should go through the ``CityBundle``
#: properties rather than re-deriving these.
VIRTUAL_MAP_NAME = "citymap.md"
REAL_MAP_NAME = "map.geojson"
ENVIRONMENT_NAME = "environment.json"
KNOWLEDGE_NAME = "knowledge.json"
NEWS_NAME = "news.json"
STATE_CSV_NAME = "agents.csv"
PROFILES_MD_NAME = "profiles.md"


class CityNotFoundError(LookupError):
    """Raised when a slug or name matches no bundle on disk."""


def city_root(root: Path | str | None = None) -> Path:
    """Absolute path of the cities directory."""
    base = Path(root) if root is not None else PROJECT_ROOT
    return base / CITIES_DIRNAME


def runs_root(root: Path | str | None = None) -> Path:
    """Absolute path of the directory holding every city's run artifacts."""
    base = Path(root) if root is not None else PROJECT_ROOT
    return base / RUNS_DIRNAME


def slugify(name: str) -> str:
    """A filesystem-safe, stable slug for a place name.

    Non-ASCII names (the common case here — most places are Chinese) have no
    meaningful ASCII transliteration available without a dependency, so their
    characters are kept verbatim after stripping path separators and
    whitespace.  The slug therefore stays human-readable as a directory name
    (``data/cities/绍兴柯桥/``) instead of degenerating to a hash.
    """
    text = unicodedata.normalize("NFKC", str(name or "")).strip()
    # Drop anything that would be awkward or unsafe in a path segment.
    text = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-.")
    if not text:
        raise ValueError(f"place name {name!r} has no usable characters for a slug")
    return text.lower() if text.isascii() else text


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class CityBundle:
    """A city on disk: the manifest plus the directory it lives in."""

    directory: Path
    manifest: dict[str, Any] = field(default_factory=dict)

    # -- identity ----------------------------------------------------------

    @property
    def slug(self) -> str:
        return str(self.manifest.get("slug") or self.directory.name)

    @property
    def name(self) -> str:
        return str(self.manifest.get("name") or self.slug)

    @property
    def display_name(self) -> str:
        return str(self.manifest.get("display_name") or self.name)

    # -- files -------------------------------------------------------------

    @property
    def manifest_path(self) -> Path:
        return self.directory / MANIFEST_NAME

    @property
    def virtual_map_path(self) -> Path:
        return self.directory / VIRTUAL_MAP_NAME

    @property
    def real_map_path(self) -> Path:
        return self.directory / REAL_MAP_NAME

    @property
    def environment_path(self) -> Path:
        return self.directory / ENVIRONMENT_NAME

    @property
    def knowledge_path(self) -> Path:
        """The city's economic / social profile (industries, priorities…)."""
        return self.directory / KNOWLEDGE_NAME

    @property
    def news_path(self) -> Path:
        """Recent local news, refreshed on real-world time, not sim time."""
        return self.directory / NEWS_NAME

    @property
    def state_csv_path(self) -> Path:
        return self.directory / STATE_CSV_NAME

    @property
    def profiles_md_path(self) -> Path:
        return self.directory / PROFILES_MD_NAME

    # -- derived state -----------------------------------------------------

    @property
    def map_mode(self) -> str:
        """``"real"`` only when a real bundle was fetched *and* still exists."""
        mode = str((self.manifest.get("map") or {}).get("mode", "virtual"))
        if mode == "real" and not self.real_map_path.exists():
            return "virtual"
        return mode

    @property
    def population_count(self) -> int:
        return int((self.manifest.get("population") or {}).get("count", 0))

    def paths_for_config(self) -> dict[str, Any]:
        """The ``map_path`` / ``csv_path`` / ``md_path`` overrides for this city.

        Returned as repo-relative POSIX strings because that is what the rest of
        the config uses and what ``_resolve_existing_path`` expects.
        """
        def rel(path: Path) -> str:
            try:
                return path.resolve().relative_to(PROJECT_ROOT).as_posix()
            except ValueError:
                return str(path)

        overrides: dict[str, Any] = {
            "map_mode": self.map_mode,
            "map_path": rel(self.virtual_map_path),
        }
        if self.map_mode == "real":
            overrides["real_map_path"] = rel(self.real_map_path)
        if self.state_csv_path.exists():
            overrides["csv_path"] = rel(self.state_csv_path)
        if self.profiles_md_path.exists():
            overrides["md_path"] = rel(self.profiles_md_path)
        return overrides

    # -- persistence -------------------------------------------------------

    def record(self, action: str, **details: Any) -> None:
        """Append an entry to the manifest's provenance log (not yet saved)."""
        history = self.manifest.setdefault("history", [])
        history.append({"at": _utcnow(), "action": action, **details})

    def save(self) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.manifest["updated_at"] = _utcnow()
        self.manifest_path.write_text(
            json.dumps(self.manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return self.manifest_path

    def summary(self) -> dict[str, Any]:
        """Compact, JSON-safe view for the CLI listing and the dashboard API."""
        return {
            "slug": self.slug,
            "name": self.name,
            "display_name": self.display_name,
            "scale": self.manifest.get("scale"),
            "map_mode": self.map_mode,
            "population": self.population_count,
            "place": self.manifest.get("place") or {},
            "created_at": self.manifest.get("created_at"),
            "updated_at": self.manifest.get("updated_at"),
            "directory": str(self.directory),
        }


def new_manifest(
    *,
    slug: str,
    name: str,
    display_name: str,
    place: dict[str, Any],
    scale: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "slug": slug,
        "name": name,
        "display_name": display_name,
        "created_at": _utcnow(),
        "place": place,
        "scale": scale,
        "map": {"mode": "virtual", "virtual": VIRTUAL_MAP_NAME},
        "environment": ENVIRONMENT_NAME,
        "population": {"count": 0},
        "history": [],
    }


def load_bundle(directory: Path | str) -> CityBundle:
    """Load a bundle from its directory; the manifest must exist."""
    path = Path(directory)
    manifest_path = path / MANIFEST_NAME
    if not manifest_path.exists():
        raise CityNotFoundError(f"no {MANIFEST_NAME} in {path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return CityBundle(directory=path, manifest=manifest)


def list_cities(root: Path | str | None = None) -> list[CityBundle]:
    """Every readable bundle under the cities directory, sorted by slug.

    A directory with a missing or corrupt manifest is skipped rather than
    fatal: one bad folder should not make the whole registry unusable.
    """
    base = city_root(root)
    if not base.is_dir():
        return []
    bundles = []
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        try:
            bundles.append(load_bundle(child))
        except (CityNotFoundError, json.JSONDecodeError, OSError):
            continue
    return bundles


def resolve_city(ref: str, root: Path | str | None = None) -> CityBundle:
    """Find a bundle by slug, by name, or by an explicit directory path."""
    if not ref:
        raise CityNotFoundError("no city reference given")
    candidate = Path(ref)
    if candidate.is_dir() and (candidate / MANIFEST_NAME).exists():
        return load_bundle(candidate)

    base = city_root(root)
    direct = base / ref
    if direct.is_dir():
        return load_bundle(direct)
    try:
        direct = base / slugify(ref)
    except ValueError:
        direct = base / ref
    if direct.is_dir():
        return load_bundle(direct)

    lowered = str(ref).strip().lower()
    for bundle in list_cities(root):
        if lowered in {bundle.slug.lower(), bundle.name.lower(), bundle.display_name.lower()}:
            return bundle
    raise CityNotFoundError(f"no city matching {ref!r} under {base}")


def delete_city(ref: str, root: Path | str | None = None) -> Path:
    """Remove a bundle directory entirely. Returns the path that was removed.

    The city's run artifacts go with it. Leaving them behind would make a city
    recreated under the same name silently inherit the deleted one's memory and
    world clock — the same cross-city bleed that per-city run roots exist to
    stop, just deferred.
    """
    bundle = resolve_city(ref, root)
    directory = bundle.directory.resolve()
    base = city_root(root).resolve()
    # Refuse to delete anything outside the registry — a mistyped path should
    # not be able to take out an unrelated directory.
    if base not in directory.parents:
        raise ValueError(f"refusing to delete {directory}: not inside {base}")
    shutil.rmtree(directory)
    runs_base = runs_root(root).resolve()
    run_dir = (runs_base / bundle.slug).resolve()
    if runs_base in run_dir.parents and run_dir.is_dir():
        shutil.rmtree(run_dir)
    return directory


__all__ = [
    "CITIES_DIRNAME",
    "RUNS_DIRNAME",
    "CityBundle",
    "CityNotFoundError",
    "city_root",
    "delete_city",
    "list_cities",
    "load_bundle",
    "new_manifest",
    "resolve_city",
    "runs_root",
    "slugify",
]
