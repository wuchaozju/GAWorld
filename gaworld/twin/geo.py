"""Map real GPS fixes onto GAWorld city-map nodes.

A thin wrapper over the canonical projection in :mod:`gaworld.world.city_map`,
so the twin subsystem never re-derives the lat/lng maths and cannot drift from
it. Coordinates farther than ``max_snap_km`` from every node are reported as
out of map rather than snapped to the nearest edge node: the map is anchored on
Hangzhou, and a fabricated position would silently corrupt both the mirror
channel and the offline calibration data.
"""

from __future__ import annotations

import math

from gaworld.world.city_map import KM_PER_GRID_X, KM_PER_GRID_Y, _lnglat_to_grid


DEFAULT_MAX_SNAP_KM = 3.0


def project(lng, lat):
    """Project WGS84 to the city map's grid and kilometre offsets."""
    grid_x, grid_y = _lnglat_to_grid(lng, lat)
    return {
        "grid_x": round(grid_x, 4),
        "grid_y": round(grid_y, 4),
        "x_km": round(grid_x * KM_PER_GRID_X, 4),
        "y_km": round(grid_y * KM_PER_GRID_Y, 4),
    }


def nearest_node(city_map, x_km, y_km):
    """Return ``(node_id, distance_km)``, or ``(None, inf)`` for an empty map."""
    nodes = (city_map or {}).get("nodes") or {}
    best_id = None
    best_dist = math.inf
    for node_id, node in nodes.items():
        try:
            dx = float(node["x_km"]) - float(x_km)
            dy = float(node["y_km"]) - float(y_km)
        except (KeyError, TypeError, ValueError):
            # A node without usable coordinates is skipped rather than fatal:
            # one malformed entry should not break every incoming report.
            continue
        dist = math.sqrt(dx * dx + dy * dy)
        if dist < best_dist:
            best_id = node_id
            best_dist = dist
    return best_id, best_dist


def locate(lng, lat, city_map=None, max_snap_km=DEFAULT_MAX_SNAP_KM):
    """Project a GPS fix and snap it to a node when one is close enough."""
    projected = project(lng, lat)
    node_id, dist_km = nearest_node(city_map, projected["x_km"], projected["y_km"])
    out_of_map = node_id is None or dist_km > float(max_snap_km)
    return {
        "grid": {"x": projected["grid_x"], "y": projected["grid_y"]},
        "node_id": None if out_of_map else node_id,
        "snap_km": None if node_id is None else round(dist_km, 3),
        "out_of_map": bool(out_of_map),
    }
