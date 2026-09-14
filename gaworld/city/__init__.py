"""City layer — create, register and populate whole cities from a place name.

A *city* here is a self-contained bundle on disk (``data/cities/<slug>/``)
holding everything one simulation world needs: a map spec, an environment
config and a population.  The simulator stays single-city at runtime — it just
reads its ``map_path`` / ``csv_path`` / ``md_path`` out of the selected bundle
instead of the fixed ``data/`` files.

Entry points
------------

``create_city``     place name → geocode → map (real OSM, procedural fallback)
                    → environment → bundle on disk
``add_population``  bulk-synthesise residents into an existing bundle
``add_agent``       append one agent to an existing bundle
``migrate_agent``   move an existing agent into a bundle, re-homing it on the
                    destination map
"""

from __future__ import annotations

from gaworld.city.agents import add_agent, add_population, migrate_agent
from gaworld.city.bundle import (
    CityBundle,
    city_root,
    delete_city,
    list_cities,
    load_bundle,
    resolve_city,
    slugify,
)
from gaworld.city.create import CityCreationError, create_city

__all__ = [
    "CityBundle",
    "CityCreationError",
    "add_agent",
    "add_population",
    "city_root",
    "create_city",
    "delete_city",
    "list_cities",
    "load_bundle",
    "migrate_agent",
    "resolve_city",
    "slugify",
]
