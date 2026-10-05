"""Indoor spatial tree: building → room → object, plus who is in which room.

A generative-agents–style spatial memory (``world:sector:arena:object``)
that used to live only in the pixel-town renderer (``site/simviz/
spatial-tree.js``). The blueprints here are the same data — a test runs the
JS file under node and compares — so the renderer and the simulation agree
on what rooms a building has.

Two layers:

* **The tree** (:class:`SpatialTree`, :func:`build_building_tree`): store and
  index — find an object, list a room's objects, resolve an address, pick the
  room that hosts an activity. Pure data, no simulation state.
* **Placement helpers** used by :class:`gaworld.world.plugin.RoomsPlugin`
  (``local_physical.rooms``, default off): which rooms an activity may use
  (:func:`rooms_for`), each room's share of the venue's capacity
  (:func:`room_share`), which flat a household lives in
  (:func:`assign_units`), and whether two residents are in the same room
  (:func:`same_room`).

Design invariants (change them knowingly):

* **One layout per kind of place.** Every café has the same rooms. The
  place's use picks one of 18 layouts — ``interior_type``, then OSM-style
  ``amenity`` / ``shop`` / ``office`` / ``tourism`` / ``leisure`` tags, then the
  building shell, its name, and finally the map ``category`` (the renderer's
  ``layoutFor``, ported as :func:`layout_type`). Rooms are the layout's, not
  the city's. The renderer also mirrors a layout per place; that is display
  only and changes no room.
* **A residential building is many flats with one layout.** Flats come from
  the citymap's ``- Floor: / - Flat:`` lines (``city_map["interiors"]``);
  when a building has none, or fewer than its households, floors are added
  on top. Each household gets its own flat, so neighbours at home are not in
  the same room.
* **Capacity follows floor area.** A room holds ``node capacity × its share
  of the plan`` (rooms tile the unit square, so the shares sum to 1). An
  activity can only use the rooms that host it, so a full dining room fills
  a café for diners even while the counter has space.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any

WORLD = "GAWorld Village"


# ---- tiny builders so blueprints stay terse + uniform (mirror spatial-tree.js) ----
def _obj(name, kind, x, y, w, h, slot=None):
    return {"name": name, "kind": kind, "x": x, "y": y, "w": w, "h": h, "slot": slot or None}


def _room(name, type_, x, y, w, h, door, objects):
    return {
        "name": name,
        "type": type_,
        "x": x,
        "y": y,
        "w": w,
        "h": h,
        "door": door or "S",
        "objects": objects or [],
    }


# ===== room furniture kits (object x,y,w,h are 0..1 of the room) =====
def _bedroom_kit():
    return [
        _obj("bed", "bed", 0.08, 0.10, 0.46, 0.34, "sleep"),
        _obj("nightstand", "nightstand", 0.58, 0.12, 0.14, 0.14),
        _obj("wardrobe", "wardrobe", 0.76, 0.10, 0.18, 0.30),
        _obj("desk", "desk", 0.10, 0.64, 0.32, 0.18, "study"),
        _obj("chair", "chair", 0.18, 0.83, 0.14, 0.12, "sit"),
        _obj("plant", "plant", 0.80, 0.74, 0.12, 0.18),
    ]


def _bathroom_kit():
    return [
        _obj("sink", "sink", 0.12, 0.08, 0.30, 0.18, "wash"),
        _obj("toilet", "toilet", 0.12, 0.60, 0.28, 0.30, "toilet"),
        _obj("bathtub", "bathtub", 0.52, 0.18, 0.40, 0.64, "wash"),
    ]


def _kitchen_kit():
    return [
        _obj("counter", "counter", 0.06, 0.08, 0.60, 0.16),
        _obj("stove", "stove", 0.22, 0.10, 0.16, 0.12, "cook"),
        _obj("fridge", "fridge", 0.74, 0.10, 0.16, 0.30),
        _obj("sink", "sink", 0.06, 0.32, 0.20, 0.16, "wash"),
        _obj("table", "table", 0.42, 0.56, 0.26, 0.26, "eat"),
        _obj("chair", "chair", 0.40, 0.84, 0.10, 0.10, "sit"),
        _obj("chair", "chair", 0.62, 0.84, 0.10, 0.10, "sit"),
    ]


def _living_kit():
    return [
        _obj("plant", "plant", 0.05, 0.06, 0.12, 0.18),
        _obj("tv", "tv", 0.06, 0.40, 0.30, 0.10),
        _obj("sofa", "sofa", 0.06, 0.60, 0.34, 0.18, "watch"),
        _obj("coffee_table", "coffee_table", 0.12, 0.82, 0.20, 0.10),
        _obj("dining_table", "table", 0.46, 0.30, 0.24, 0.24, "eat"),
        _obj("chair", "chair", 0.45, 0.17, 0.10, 0.10, "sit"),
        _obj("chair", "chair", 0.62, 0.17, 0.10, 0.10, "sit"),
        _obj("chair", "chair", 0.45, 0.56, 0.10, 0.10, "sit"),
        _obj("chair", "chair", 0.62, 0.56, 0.10, 0.10, "sit"),
        _obj("bookshelf", "bookshelf", 0.78, 0.06, 0.18, 0.16, "read"),
        _obj("piano", "piano", 0.78, 0.30, 0.18, 0.36, "music"),
    ]


def _study_kit():
    return [
        _obj("desk", "desk", 0.12, 0.20, 0.44, 0.22, "work"),
        _obj("chair", "chair", 0.28, 0.46, 0.14, 0.14, "sit"),
        _obj("bookshelf", "bookshelf", 0.10, 0.04, 0.80, 0.10, "read"),
        _obj("plant", "plant", 0.80, 0.20, 0.12, 0.20),
    ]


def _restroom_kit():
    return [
        _obj("sink", "sink", 0.14, 0.10, 0.30, 0.20, "wash"),
        _obj("toilet", "toilet", 0.16, 0.55, 0.28, 0.32, "toilet"),
        _obj("sink", "sink", 0.58, 0.10, 0.30, 0.20, "wash"),
        _obj("toilet", "toilet", 0.58, 0.55, 0.28, 0.32, "toilet"),
    ]


def _ward_kit(n):
    """Beds stacked down the left, a shelf + plant on the right (hospital ward)."""
    out = []
    gap = 0.9 / n
    for i in range(n):
        out.append(_obj("bed", "bed", 0.06, 0.06 + i * gap, 0.46, gap * 0.78, "rest"))
    out.append(_obj("shelf", "shelf", 0.80, 0.10, 0.14, 0.7))
    out.append(_obj("plant", "plant", 0.62, 0.82, 0.12, 0.16))
    return out


def _consult_kit():
    return [
        _obj("desk", "desk", 0.10, 0.18, 0.40, 0.20, "consult"),
        _obj("chair", "chair", 0.24, 0.42, 0.14, 0.12, "sit"),
        _obj("bed", "bed", 0.10, 0.62, 0.44, 0.26, "rest"),
        _obj("shelf", "shelf", 0.78, 0.16, 0.16, 0.66),
    ]


def _shelf_floor(cols):
    """A row of shelves, used for shops + pharmacies (slot: shop)."""
    out = []
    span = 0.92 / cols
    for c in range(cols):
        out.append(_obj("shelf", "shelf", 0.06 + c * span, 0.14, span * 0.6, 0.6, "shop"))
    out.append(_obj("fridge", "fridge", 0.06, 0.82, 0.16, 0.14))
    return out


def _classroom_kit():
    out = [
        _obj("chalkboard", "chalkboard", 0.14, 0.04, 0.72, 0.08),
        _obj("podium", "podium", 0.46, 0.16, 0.10, 0.10),
    ]
    for r in range(2):
        for c in range(3):
            out.append(_obj("desk", "desk", 0.12 + c * 0.26, 0.34 + r * 0.28, 0.18, 0.12, "study"))
            out.append(_obj("chair", "chair", 0.16 + c * 0.26, 0.48 + r * 0.28, 0.09, 0.09, "sit"))
    return out


def _library_kit():
    out = []
    for c in range(4):
        out.append(_obj("bookshelf", "bookshelf", 0.06 + c * 0.16, 0.08, 0.12, 0.5, "read"))
    out.append(_obj("desk", "desk", 0.30, 0.66, 0.40, 0.18, "read"))
    out.append(_obj("chair", "chair", 0.36, 0.86, 0.10, 0.10, "sit"))
    out.append(_obj("chair", "chair", 0.54, 0.86, 0.10, 0.10, "sit"))
    return out


def _cafe_counter_kit():
    return [
        _obj("counter", "counter", 0.06, 0.16, 0.66, 0.14, "order"),
        _obj("coffee_machine", "coffee_machine", 0.10, 0.04, 0.12, 0.12),
        _obj("shelf", "shelf", 0.80, 0.12, 0.14, 0.7),
    ]


def _seating_kit():
    out = []
    for r in range(2):
        for c in range(3):
            out.append(_obj("table", "table", 0.10 + c * 0.28, 0.16 + r * 0.42, 0.14, 0.16, "eat"))
            out.append(_obj("chair", "chair", 0.08 + c * 0.28, 0.34 + r * 0.42, 0.08, 0.08, "sit"))
            out.append(_obj("chair", "chair", 0.20 + c * 0.28, 0.34 + r * 0.42, 0.08, 0.08, "sit"))
    return out


def _reception_kit():
    return [
        _obj("desk", "desk", 0.16, 0.20, 0.52, 0.18, "work"),
        _obj("chair", "chair", 0.36, 0.44, 0.14, 0.12, "sit"),
        _obj("bench", "bench", 0.14, 0.74, 0.30, 0.10, "rest"),
        _obj("plant", "plant", 0.80, 0.20, 0.12, 0.22),
    ]


def _office_kit():
    out = []
    for i in range(2):
        out.append(_obj("desk", "desk", 0.12, 0.16 + i * 0.42, 0.42, 0.18, "work"))
        out.append(_obj("chair", "chair", 0.28, 0.40 + i * 0.42, 0.14, 0.12, "sit"))
    out.append(_obj("plant", "plant", 0.80, 0.30, 0.12, 0.24))
    return out


def _meeting_kit():
    out = [_obj("table", "table", 0.22, 0.30, 0.56, 0.40, "meeting")]
    for c in range(3):
        out.append(_obj("chair", "chair", 0.26 + c * 0.18, 0.16, 0.10, 0.10, "sit"))
        out.append(_obj("chair", "chair", 0.26 + c * 0.18, 0.76, 0.10, 0.10, "sit"))
    return out


def _pharmacy_kit():
    out = []
    for c in range(3):
        out.append(_obj("shelf", "shelf", 0.08 + c * 0.22, 0.12, 0.14, 0.6, "shop"))
    out.append(_obj("counter", "counter", 0.08, 0.80, 0.6, 0.12, "shop"))
    return out


def _park_kit():
    return [
        _obj("tree", "tree", 0.08, 0.16, 0.16, 0.30),
        _obj("tree", "tree", 0.78, 0.16, 0.16, 0.30),
        _obj("tree", "tree", 0.10, 0.62, 0.16, 0.30),
        _obj("fountain", "fountain", 0.42, 0.38, 0.18, 0.24, "rest"),
        _obj("bench", "bench", 0.30, 0.74, 0.16, 0.06, "rest"),
        _obj("bench", "bench", 0.58, 0.74, 0.16, 0.06, "rest"),
    ]


def _reslot(objects, old, new):
    return [{**o, "slot": new if o["slot"] == old else o["slot"]} for o in objects]


def _without(objects, *kinds):
    return [o for o in objects if o["kind"] not in kinds]


# ===== building blueprints (room x,y,w,h are 0..1 of the interior) =====
# ``rooms`` is the renderer's data, kept equal to spatial-tree.js by a test.
# ``default`` / ``staff`` / ``staff_only`` are the simulation's additions:
# where someone with nothing room-specific to do stands, where the people who
# work here go, and which rooms a visitor never enters.
def _bp(category, rooms, default, staff, staff_only=(), outdoor=False):
    out = {
        "category": category,
        "rooms": rooms,
        "default": default,
        "staff": staff,
        "staff_only": list(staff_only),
    }
    if outdoor:
        out["outdoor"] = True
    return out


BLUEPRINTS: dict[str, dict[str, Any]] = {
    "residential": _bp(
        "residential",
        [
            _room("Bedroom 1", "bedroom", 0.00, 0.00, 0.28, 0.56, "S", _bedroom_kit()),
            _room("Bathroom 1", "bathroom", 0.28, 0.00, 0.16, 0.56, "S", _bathroom_kit()),
            _room("Bedroom 2", "bedroom", 0.44, 0.00, 0.28, 0.56, "S", _bedroom_kit()),
            _room("Study", "study", 0.72, 0.00, 0.28, 0.56, "S", _study_kit()),
            _room("Kitchen", "kitchen", 0.00, 0.56, 0.26, 0.44, "N", _kitchen_kit()),
            _room("Living Room", "living", 0.26, 0.56, 0.46, 0.44, "N", _living_kit()),
            _room("Bedroom 3", "bedroom", 0.72, 0.56, 0.28, 0.44, "N", _bedroom_kit()),
        ],
        "Living Room",
        "Study",
    ),
    "medical": _bp(
        "medical",
        [
            _room("Reception", "reception", 0.00, 0.00, 0.34, 0.50, "S", _reception_kit()),
            _room("Ward A", "ward", 0.34, 0.00, 0.33, 0.50, "S", _ward_kit(3)),
            _room("Ward B", "ward", 0.67, 0.00, 0.33, 0.50, "S", _ward_kit(3)),
            _room("Consulting Room", "consult", 0.00, 0.50, 0.34, 0.50, "N", _consult_kit()),
            _room("Pharmacy", "pharmacy", 0.34, 0.50, 0.33, 0.50, "N", _pharmacy_kit()),
            _room("Restroom", "bathroom", 0.67, 0.50, 0.33, 0.50, "N", _restroom_kit()),
        ],
        "Reception",
        "Consulting Room",
    ),
    "education": _bp(
        "education",
        [
            _room("Classroom 1", "classroom", 0.00, 0.00, 0.50, 0.55, "S", _classroom_kit()),
            _room("Classroom 2", "classroom", 0.50, 0.00, 0.50, 0.55, "S", _classroom_kit()),
            _room("Library", "library", 0.00, 0.55, 0.40, 0.45, "N", _library_kit()),
            _room("Office", "office", 0.40, 0.55, 0.30, 0.45, "N", _office_kit()),
            _room("Restroom", "bathroom", 0.70, 0.55, 0.30, 0.45, "N", _restroom_kit()),
        ],
        "Classroom 1",
        "Office",
        ["Office"],
    ),
    "commerce": _bp(
        "commerce",
        [
            _room("Shop Floor", "shop", 0.00, 0.00, 0.72, 0.60, "S", _shelf_floor(4)),
            _room("Storeroom", "storeroom", 0.72, 0.00, 0.28, 0.60, "S", _shelf_floor(2)),
            _room(
                "Checkout",
                "checkout",
                0.00,
                0.60,
                0.40,
                0.40,
                "N",
                [
                    _obj("checkout", "checkout", 0.16, 0.30, 0.30, 0.34, "shop"),
                    _obj("plant", "plant", 0.70, 0.30, 0.14, 0.34),
                ],
            ),
            _room(
                "Cafe Corner",
                "seating",
                0.40,
                0.60,
                0.32,
                0.40,
                "N",
                [
                    _obj("table", "table", 0.20, 0.26, 0.24, 0.28, "eat"),
                    _obj("chair", "chair", 0.16, 0.60, 0.12, 0.12, "sit"),
                    _obj("chair", "chair", 0.40, 0.60, 0.12, 0.12, "sit"),
                ],
            ),
            _room("Restroom", "bathroom", 0.72, 0.60, 0.28, 0.40, "N", _restroom_kit()),
        ],
        "Shop Floor",
        "Checkout",
        ["Storeroom"],
    ),
    "leisure": _bp(
        "leisure",
        [
            _room("Counter", "counter", 0.00, 0.00, 0.40, 0.55, "S", _cafe_counter_kit()),
            _room("Kitchen", "kitchen", 0.40, 0.00, 0.30, 0.55, "S", _kitchen_kit()),
            _room("Restroom", "bathroom", 0.70, 0.00, 0.30, 0.55, "S", _restroom_kit()),
            _room("Seating", "seating", 0.00, 0.55, 1.00, 0.45, "N", _seating_kit()),
        ],
        "Seating",
        "Counter",
        ["Kitchen"],
    ),
    "government": _bp(
        "government",
        [
            _room("Reception", "reception", 0.00, 0.00, 0.34, 0.50, "S", _reception_kit()),
            _room("Office 1", "office", 0.34, 0.00, 0.33, 0.50, "S", _office_kit()),
            _room("Office 2", "office", 0.67, 0.00, 0.33, 0.50, "S", _office_kit()),
            _room("Meeting Room", "meeting", 0.00, 0.50, 0.50, 0.50, "N", _meeting_kit()),
            _room("Archive", "library", 0.50, 0.50, 0.25, 0.50, "N", _library_kit()),
            _room("Restroom", "bathroom", 0.75, 0.50, 0.25, 0.50, "N", _restroom_kit()),
        ],
        "Reception",
        "Office 1",
        ["Office 1", "Office 2", "Archive"],
    ),
    "park": _bp(
        "leisure",
        [
            _room("Park", "park", 0.00, 0.00, 1.00, 1.00, None, _park_kit()),
        ],
        "Park",
        "Park",
        outdoor=True,
    ),
    # Specific place uses share furniture kits, but have their own room plans.
    "apartment": _bp(
        "residential",
        [
            _room("Bedroom", "bedroom", 0, 0, 0.62, 0.5, "S", _bedroom_kit()),
            _room("Bathroom", "bathroom", 0.62, 0, 0.38, 0.5, "S", _bathroom_kit()),
            _room("Living Room", "living", 0, 0.5, 0.62, 0.5, "N", _living_kit()),
            _room("Kitchen", "kitchen", 0.62, 0.5, 0.38, 0.5, "N", _kitchen_kit()),
        ],
        "Living Room",
        "Living Room",
    ),
    "hotel": _bp(
        "commerce",
        [
            _room("Guest Room 1", "guestroom", 0, 0, 0.35, 0.55, "S", _bedroom_kit()),
            _room("Guest Room 2", "guestroom", 0.35, 0, 0.35, 0.55, "S", _bedroom_kit()),
            _room("Bathroom", "bathroom", 0.7, 0, 0.3, 0.55, "S", _bathroom_kit()),
            _room("Reception", "reception", 0, 0.55, 0.35, 0.45, "N", _reception_kit()),
            _room("Lounge", "lounge", 0.35, 0.55, 0.35, 0.45, "N", _without(_living_kit(), "piano", "tv")),
            _room("Breakfast Room", "seating", 0.7, 0.55, 0.3, 0.45, "N", _seating_kit()),
        ],
        "Lounge",
        "Reception",
    ),
    "clinic": _bp(
        "medical",
        [
            _room("Waiting Room", "waiting", 0, 0, 0.5, 0.55, "S", _reception_kit()),
            _room("Consulting Room", "consult", 0.5, 0, 0.5, 0.55, "S", _consult_kit()),
            _room("Treatment Room", "treatment", 0, 0.55, 0.5, 0.45, "N", _ward_kit(2)),
            _room("Pharmacy", "pharmacy", 0.5, 0.55, 0.25, 0.45, "N", _pharmacy_kit()),
            _room("Restroom", "bathroom", 0.75, 0.55, 0.25, 0.45, "N", _restroom_kit()),
        ],
        "Waiting Room",
        "Consulting Room",
    ),
    "pharmacy": _bp(
        "medical",
        [
            _room("Medicine Shelves", "pharmacy", 0, 0, 0.7, 0.65, "S", _pharmacy_kit()),
            _room("Stockroom", "storeroom", 0.7, 0, 0.3, 0.65, "S", _shelf_floor(2)),
            _room(
                "Service Counter",
                "checkout",
                0,
                0.65,
                0.7,
                0.35,
                "N",
                [
                    _obj("checkout", "checkout", 0.1, 0.15, 0.65, 0.32, "shop"),
                    _obj("chair", "chair", 0.3, 0.52, 0.12, 0.18, "consult"),
                ],
            ),
            _room("Restroom", "bathroom", 0.7, 0.65, 0.3, 0.35, "N", _restroom_kit()),
        ],
        "Medicine Shelves",
        "Service Counter",
        ["Stockroom"],
    ),
    "library": _bp(
        "education",
        [
            _room("Book Stacks", "library", 0, 0, 0.65, 0.6, "S", _library_kit()),
            _room(
                "Reading Room",
                "reading",
                0.65,
                0,
                0.35,
                0.6,
                "S",
                _reslot(_without(_classroom_kit(), "chalkboard", "podium"), "study", "read"),
            ),
            _room("Borrowing Counter", "counter", 0, 0.6, 0.3, 0.4, "N", _reception_kit()),
            _room("Quiet Study", "study", 0.3, 0.6, 0.4, 0.4, "N", _study_kit()),
            _room("Restroom", "bathroom", 0.7, 0.6, 0.3, 0.4, "N", _restroom_kit()),
        ],
        "Reading Room",
        "Borrowing Counter",
    ),
    "office": _bp(
        "commerce",
        [
            _room(
                "Open Office",
                "office",
                0,
                0,
                0.65,
                0.6,
                "S",
                _reslot(_without(_classroom_kit(), "chalkboard", "podium"), "study", "work"),
            ),
            _room("Meeting Room", "meeting", 0.65, 0, 0.35, 0.6, "S", _meeting_kit()),
            _room("Reception", "reception", 0, 0.6, 0.3, 0.4, "N", _reception_kit()),
            _room(
                "Break Room",
                "lounge",
                0.3,
                0.6,
                0.4,
                0.4,
                "N",
                [
                    *_cafe_counter_kit(),
                    _obj("sofa", "sofa", 0.1, 0.55, 0.55, 0.25, "rest"),
                ],
            ),
            _room("Restroom", "bathroom", 0.7, 0.6, 0.3, 0.4, "N", _restroom_kit()),
        ],
        "Reception",
        "Open Office",
        ["Open Office"],
    ),
    "restaurant": _bp(
        "leisure",
        [
            _room("Dining Hall", "seating", 0, 0, 0.65, 0.65, "S", _seating_kit()),
            _room("Kitchen", "kitchen", 0.65, 0, 0.35, 0.65, "S", _kitchen_kit()),
            _room("Checkout", "checkout", 0, 0.65, 0.25, 0.35, "N", _cafe_counter_kit()),
            _room(
                "Private Dining",
                "seating",
                0.25,
                0.65,
                0.4,
                0.35,
                "N",
                _reslot(_meeting_kit(), "meeting", "eat"),
            ),
            _room("Restroom", "bathroom", 0.65, 0.65, 0.35, 0.35, "N", _restroom_kit()),
        ],
        "Dining Hall",
        "Kitchen",
        ["Kitchen"],
    ),
    "industry": _bp(
        "industry",
        [
            _room(
                "Workshop",
                "workshop",
                0,
                0,
                0.7,
                0.6,
                "S",
                [
                    _obj("machine", "machine", 0.08, 0.12, 0.3, 0.28, "work"),
                    _obj("machine", "machine", 0.54, 0.12, 0.3, 0.28, "work"),
                    _obj("workbench", "workbench", 0.12, 0.64, 0.6, 0.2, "work"),
                ],
            ),
            _room(
                "Warehouse",
                "warehouse",
                0.7,
                0,
                0.3,
                0.6,
                "S",
                [
                    _obj("crate", "crate", 0.1, 0.12, 0.32, 0.28),
                    _obj("crate", "crate", 0.55, 0.12, 0.32, 0.28),
                    _obj("crate", "crate", 0.1, 0.6, 0.32, 0.28),
                    _obj("crate", "crate", 0.55, 0.6, 0.32, 0.28),
                ],
            ),
            _room("Office", "office", 0, 0.6, 0.35, 0.4, "N", _office_kit()),
            _room("Staff Canteen", "seating", 0.35, 0.6, 0.35, 0.4, "N", _seating_kit()),
            _room("Restroom", "bathroom", 0.7, 0.6, 0.3, 0.4, "N", _restroom_kit()),
        ],
        "Office",
        "Workshop",
        ["Workshop", "Warehouse"],
    ),
    "transit": _bp(
        "transit",
        [
            _room(
                "Waiting Hall",
                "waiting",
                0,
                0,
                0.7,
                0.65,
                "S",
                [
                    _obj("departure_board", "departure_board", 0.12, 0.06, 0.7, 0.08),
                    *[
                        _obj("bench", "bench", x, y, 0.32, 0.12, "rest")
                        for y in (0.35, 0.68)
                        for x in (0.1, 0.55)
                    ],
                ],
            ),
            _room(
                "Ticket Office",
                "ticket",
                0.7,
                0,
                0.3,
                0.65,
                "S",
                [
                    _obj("ticket_machine", "ticket_machine", 0.1, 0.14, 0.3, 0.18, "order"),
                    _obj("ticket_machine", "ticket_machine", 0.58, 0.14, 0.3, 0.18, "order"),
                    _obj("counter", "counter", 0.1, 0.6, 0.75, 0.2, "work"),
                ],
            ),
            _room(
                "Concourse",
                "concourse",
                0,
                0.65,
                0.7,
                0.35,
                "N",
                [_obj("turnstile", "turnstile", x, 0.3, 0.12, 0.35) for x in (0.2, 0.43, 0.66)],
            ),
            _room("Restroom", "bathroom", 0.7, 0.65, 0.3, 0.35, "N", _restroom_kit()),
        ],
        "Waiting Hall",
        "Ticket Office",
    ),
    "gym": _bp(
        "leisure",
        [
            _room(
                "Cardio Room",
                "fitness",
                0,
                0,
                0.65,
                0.6,
                "S",
                [
                    *[
                        _obj("treadmill", "treadmill", x, 0.12, 0.2, 0.38, "exercise")
                        for x in (0.1, 0.4, 0.7)
                    ],
                    _obj("weight_rack", "weight_rack", 0.1, 0.72, 0.7, 0.15, "exercise"),
                ],
            ),
            _room(
                "Studio",
                "studio",
                0.65,
                0,
                0.35,
                0.6,
                "S",
                [
                    _obj("exercise_mat", "exercise_mat", x, y, 0.26, 0.25, "exercise")
                    for x in (0.14, 0.55)
                    for y in (0.15, 0.58)
                ],
            ),
            _room("Reception", "reception", 0, 0.6, 0.3, 0.4, "N", _reception_kit()),
            _room(
                "Locker Room",
                "locker",
                0.3,
                0.6,
                0.35,
                0.4,
                "N",
                [
                    _obj("wardrobe", "wardrobe", 0.1, 0.1, 0.8, 0.18),
                    _obj("bench", "bench", 0.15, 0.6, 0.65, 0.12, "rest"),
                ],
            ),
            _room("Shower Room", "bathroom", 0.65, 0.6, 0.35, 0.4, "N", _bathroom_kit()),
        ],
        "Cardio Room",
        "Reception",
    ),
    "mixed": _bp(
        "mixed",
        [
            _room("Common Hall", "lounge", 0, 0, 0.65, 0.65, "S", _reception_kit()),
            _room("Office", "office", 0.65, 0, 0.35, 0.65, "S", _office_kit()),
            _room("Seating", "seating", 0, 0.65, 0.65, 0.35, "N", _seating_kit()),
            _room("Restroom", "bathroom", 0.65, 0.65, 0.35, 0.35, "N", _restroom_kit()),
        ],
        "Common Hall",
        "Office",
        ["Office"],
    ),
}
#: Layout types that share another's plan (the renderer: ``BLUEPRINTS.cafe = BLUEPRINTS.leisure``).
BLUEPRINT_ALIASES = {"cafe": "leisure"}

#: Layout types a resident reads (same as the renderer's LAYOUT_LABELS).
LAYOUT_LABELS = {
    "residential": "住宅",
    "apartment": "公寓",
    "hotel": "旅馆",
    "medical": "医院",
    "clinic": "诊所",
    "pharmacy": "药店",
    "education": "学校",
    "library": "图书馆",
    "commerce": "商店",
    "cafe": "咖啡馆",
    "restaurant": "餐厅",
    "office": "办公",
    "government": "政务",
    "industry": "工厂",
    "transit": "车站",
    "gym": "健身房",
    "park": "公园",
    "mixed": "公共空间",
}
_TYPE_ALIASES = {
    "house": "residential",
    "apartments": "apartment",
    "residential": "residential",
    "dormitory": "apartment",
    "hospital": "medical",
    "doctors": "clinic",
    "school": "education",
    "college": "education",
    "university": "education",
    "supermarket": "commerce",
    "convenience": "commerce",
    "retail": "commerce",
    "shop": "commerce",
    "mall": "commerce",
    "industrial": "industry",
    "factory": "industry",
    "warehouse": "industry",
    "station": "transit",
    "train_station": "transit",
    "bus_station": "transit",
    "townhall": "government",
    "fitness_centre": "gym",
    "leisure": "cafe",
    "hostel": "hotel",
    "guest_house": "hotel",
    "fast_food": "restaurant",
    "bar": "cafe",
    "company": "office",
}


def _js_regex(pattern: str) -> re.Pattern[str]:
    """A JS ``/…/i`` regex: ``\\b`` is an ASCII word boundary there (Chinese
    characters are not word characters), unlike Python's Unicode ``\\b``."""
    word = "[A-Za-z0-9_]"
    boundary = f"(?:(?<!{word})(?={word})|(?<={word})(?!{word}))"
    return re.compile(pattern.replace(r"\b", boundary), re.I)


_USE_HINTS: list[tuple[str, re.Pattern[str]]] = [
    ("hotel", _js_regex(r"宾馆|旅馆|酒店|民宿|客栈|\b(hotel|hostel|inn|guest\s*house)\b")),
    ("pharmacy", _js_regex(r"药店|药房|\b(pharmacy|drugstore)\b")),
    ("clinic", _js_regex(r"诊所|卫生服务|卫生院|\b(clinic|health\s*cent(?:er|re))\b")),
    ("medical", _js_regex(r"医院|医疗中心|\b(hospital|medical\s*cent(?:er|re))\b")),
    ("library", _js_regex(r"图书馆|阅览室|\blibrary\b")),
    ("education", _js_regex(r"学校|小学|中学|大学|学院|幼儿园|\b(school|college|university|kindergarten)\b")),
    ("cafe", _js_regex(r"咖啡|茶馆|茶楼|\b(caf[eé]|coffee|tea\s*house|bar|pub)\b")),
    ("restaurant", _js_regex(r"餐厅|餐馆|饭店|食堂|面馆|小吃|\b(restaurant|diner|canteen|bistro)\b")),
    ("gym", _js_regex(r"健身|运动馆|体育馆|\b(gym|fitness|sports\s*cent(?:er|re))\b")),
    ("industry", _js_regex(r"工厂|厂房|车间|工业|仓库|\b(factory|workshop|warehouse|industrial)\b")),
    ("transit", _js_regex(r"车站|火车站|地铁站|汽车站|机场|\b(station|terminal|airport)\b")),
    ("government", _js_regex(r"政府|街道办|政务|行政|办事处|\b(town\s*hall|city\s*hall|government)\b")),
    ("office", _js_regex(r"办公|写字楼|公司|商务|\b(office|company|business\s*(park|cent(?:er|re)))\b")),
    ("commerce", _js_regex(r"商店|超市|商场|购物|百货|便利店|\b(shop|store|supermarket|market|mall)\b")),
    ("apartment", _js_regex(r"公寓|宿舍|\b(apartments?|dormitory|dorm)\b")),
    ("residential", _js_regex(r"小区|住宅|家园|\b(residen(?:ce|tial)|house|home)\b")),
    ("park", _js_regex(r"公园|绿地|广场|花园|\b(park|garden|trail|greenbelt|playground|plaza)\b")),
]

#: Room types in Chinese, as the indoor views label them.
ROOM_TYPE_ZH = {
    "bedroom": "卧室",
    "bathroom": "卫生间",
    "kitchen": "厨房",
    "living": "客厅",
    "study": "书房",
    "seating": "就餐区",
    "counter": "吧台",
    "ward": "病房",
    "reception": "前台",
    "office": "办公室",
    "meeting": "会议室",
    "consult": "诊室",
    "pharmacy": "药房",
    "classroom": "教室",
    "library": "图书室",
    "shop": "卖场",
    "storeroom": "库房",
    "checkout": "收银台",
    "park": "公园",
    "guestroom": "客房",
    "lounge": "休息区",
    "waiting": "等候区",
    "treatment": "治疗室",
    "reading": "阅览室",
    "workshop": "生产车间",
    "warehouse": "仓储区",
    "ticket": "售票厅",
    "concourse": "进站通道",
    "fitness": "器械区",
    "studio": "训练室",
    "locker": "更衣室",
}


def _known_type(value: Any) -> str | None:
    key = str(value or "").strip().lower()
    if key in _TYPE_ALIASES:
        return _TYPE_ALIASES[key]
    return key if key in LAYOUT_LABELS else None


def layout_type(node: Mapping[str, Any] | None) -> str:
    """Which layout a place gets (same rule as the renderer's ``layoutFor``).

    An explicit ``interior_type`` first, then the place's use (``amenity`` /
    ``shop`` / ``office`` / ``tourism`` / ``leisure``, on the node or its
    ``tags``), then the building shell, then its name, then the map category;
    unknown places get the common hall, never a bedroom.
    """
    node = node or {}
    tags = node.get("tags") or {}
    kind = _known_type(node.get("interior_type"))
    if not kind:
        # A clinic or shop can occupy a house: use beats the building shell.
        for key in ("amenity", "shop", "office", "tourism", "leisure"):
            kind = _known_type(node.get(key)) or _known_type(tags.get(key))
            if kind:
                break
        if not kind and any(v and v != "no" for v in (node.get("office"), tags.get("office"))):
            kind = "office"
        if not kind and any(v and v != "no" for v in (node.get("shop"), tags.get("shop"))):
            kind = "commerce"
        if not kind:
            kind = _known_type(node.get("building_type")) or _known_type(tags.get("building"))
    if not kind:
        name = str(node.get("label") or node.get("name") or node.get("id") or "")
        kind = (
            next((k for k, rx in _USE_HINTS if rx.search(name)), None)
            or _known_type(node.get("category"))
            or "mixed"
        )
    return kind


def blueprint_key(node: Mapping[str, Any] | None) -> str:
    """The key of the room plan a place uses (``cafe`` shares ``leisure``'s)."""
    kind = layout_type(node)
    return BLUEPRINT_ALIASES.get(kind, kind)


def blueprint_for(node: Mapping[str, Any] | None) -> dict[str, Any]:
    return BLUEPRINTS[blueprint_key(node)]


def is_residential(key: str) -> bool:
    """Does this plan hold households (flats), not visitors?"""
    return BLUEPRINTS[key]["category"] == "residential"


# ---- activity → slot (same rule as site/dashboard/indoor-view.js; a test compares) ----
_SLOT_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"刷牙|洗漱|洗手|洗澡|brush|wash|shower", re.I), "wash"),
    (re.compile(r"上厕所|厕所|卫生间|如厕|toilet", re.I), "toilet"),
    (re.compile(r"做饭|做菜|烹饪|cook", re.I), "cook"),
    (re.compile(r"健身|锻炼|运动|跑步|exercise|workout|treadmill|jog", re.I), "exercise"),
    (re.compile(r"钢琴|弹琴|piano|音乐|music", re.I), "music"),
    (re.compile(r"睡|休息|床|sleep|rest|nap", re.I), "sleep"),
    (re.compile(r"咖啡|coffee|order|点单|点餐", re.I), "order"),
    (re.compile(r"开会|会议|meeting", re.I), "meeting"),
    (re.compile(r"看病|问诊|consult|诊", re.I), "consult"),
    (re.compile(r"吃|饭|餐|eat|用餐", re.I), "eat"),
    (re.compile(r"读|看书|book|read|阅读", re.I), "read"),
    (re.compile(r"看电视|tv|watch", re.I), "watch"),
    (re.compile(r"学|课|study", re.I), "study"),
    (re.compile(r"买|shop|购物|超市", re.I), "shop"),
    (re.compile(r"工作|办公|上班|work", re.I), "work"),
]
#: A slot with no object of its own here may use these (bed ↔ ward bed…).
SLOT_ALIASES = {
    "sleep": ["rest"],
    "rest": ["sleep"],
    "order": ["eat"],
    "watch": ["sit"],
    "study": ["work", "read"],
}


def activity_slot(text: Any) -> str | None:
    """The object slot an activity uses (``"cook"``, ``"eat"``…), or None."""
    s = str(text or "")
    for pattern, slot in _SLOT_RULES:
        if pattern.search(s):
            return slot
    return None


# ===== the tree + its index/query API (port of SpatialTree) =====
class SpatialTree:
    """World → sector (building) → arena (room) → object, with a flat index."""

    def __init__(self, world: str | None = None) -> None:
        self.world = world or WORLD
        self.sectors: dict[str, dict[str, Any]] = {}
        self._index: list[dict[str, Any]] = []
        self.sector = ""
        self.outdoor = False
        self.layout_type = ""
        self.layout_label = ""

    def add_sector(self, name: str, meta: dict[str, Any] | None = None) -> SpatialTree:
        self.sectors.setdefault(name, {"meta": dict(meta or {}), "arenas": {}})
        return self

    def add_arena(self, sector: str, name: str, meta: dict[str, Any] | None = None) -> SpatialTree:
        s = self.sectors.get(sector)
        if s is not None:
            s["arenas"].setdefault(name, {"meta": dict(meta or {}), "objects": {}})
        return self

    def add_object(
        self, sector: str, arena: str, name: str, meta: dict[str, Any] | None = None
    ) -> SpatialTree:
        s = self.sectors.get(sector)
        a = s["arenas"].get(arena) if s else None
        if a is None:
            return self
        key, i = name, 2
        while key in a["objects"]:  # keep object addresses unique
            key = f"{name} {i}"
            i += 1
        rec = {"name": key, "kind": name, **(meta or {})}
        a["objects"][key] = rec
        self._index.append(
            {
                "world": self.world,
                "sector": sector,
                "arena": arena,
                "object": key,
                "kind": rec["kind"],
                "slot": rec.get("slot") or None,
                "geom": rec,
                "address": ":".join([self.world, sector, arena, key]),
            }
        )
        return self

    # --- read / traverse ---
    def sector_names(self) -> list[str]:
        return list(self.sectors)

    def arena_names(self, sector: str) -> list[str]:
        s = self.sectors.get(sector)
        return list(s["arenas"]) if s else []

    def object_names(self, sector: str, arena: str) -> list[str]:
        a = self.arena(sector, arena)
        return list(a["objects"]) if a else []

    def arena(self, sector: str, name: str) -> dict[str, Any] | None:
        s = self.sectors.get(sector)
        return s["arenas"].get(name) if s else None

    def objects(self, sector: str | None = None, arena: str | None = None) -> list[dict[str, Any]]:
        return [
            r
            for r in self._index
            if (not sector or r["sector"] == sector) and (not arena or r["arena"] == arena)
        ]

    # --- index / query ---
    def find(self, query: str | Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
        """By substring of the object name or kind, or by predicate(record)."""
        if callable(query):
            return [r for r in self._index if query(r)]
        q = str(query or "").lower()
        return [r for r in self._index if q in r["object"].lower() or q in str(r["kind"]).lower()]

    def locate(self, query: str | Callable[[dict[str, Any]], bool]) -> dict[str, Any] | None:
        hits = self.find(query)
        return hits[0] if hits else None

    def by_slot(self, slot: str) -> list[dict[str, Any]]:
        return [r for r in self._index if r["slot"] == slot]

    def address(self, sector: str, arena: str | None = None, obj: str | None = None) -> str:
        return ":".join(p for p in (self.world, sector, arena, obj) if p)

    def resolve(self, address: str) -> dict[str, Any] | None:
        parts = str(address or "").split(":")
        for r in self._index:
            if r["address"] == address:
                return r
        if len(parts) >= 4:
            for r in self._index:
                if r["sector"] == parts[1] and r["arena"] == parts[2] and r["object"] == parts[3]:
                    return r
        return None

    def arena_for_activity(self, sector: str, slot: str | None) -> str | None:
        """Prefer a room owning a matching object, else a room of that type, else the first room."""
        if slot:
            for r in self._index:
                if r["sector"] == sector and r["slot"] == slot:
                    return r["arena"]
            s = self.sectors.get(sector)
            if s:
                for name, a in s["arenas"].items():
                    if a["meta"].get("type") == slot:
                        return name
        names = self.arena_names(sector)
        return names[0] if names else None

    def object_for_activity(self, sector: str, slot: str | None) -> dict[str, Any] | None:
        for r in self._index:
            if r["sector"] == sector and r["slot"] == slot:
                return r
        return None

    def object_building_rect(self, rec: Mapping[str, Any]) -> dict[str, float] | None:
        """Building-space rect (0..1 of the interior) for an object record."""
        a = self.arena(rec["sector"], rec["arena"])
        if not a:
            return None
        m, g = a["meta"], rec["geom"]
        return {
            "x": m["x"] + g["x"] * m["w"],
            "y": m["y"] + g["y"] * m["h"],
            "w": g["w"] * m["w"],
            "h": g["h"] * m["h"],
        }


def _tree_from_blueprint(sector: str, bp: Mapping[str, Any]) -> SpatialTree:
    tree = SpatialTree(WORLD)
    outdoor = bool(bp.get("outdoor"))
    tree.add_sector(sector, {"category": bp["category"], "outdoor": outdoor})
    for r in bp["rooms"]:
        tree.add_arena(
            sector,
            r["name"],
            {
                "type": r["type"],
                "x": r["x"],
                "y": r["y"],
                "w": r["w"],
                "h": r["h"],
                "door": r["door"],
                "outdoor": outdoor,
            },
        )
        for o in r["objects"]:
            tree.add_object(
                sector,
                r["name"],
                o["name"],
                {
                    "kind": o["kind"],
                    "x": o["x"],
                    "y": o["y"],
                    "w": o["w"],
                    "h": o["h"],
                    "slot": o["slot"],
                },
            )
    tree.sector = sector  # convenience: the single building's name
    tree.outdoor = outdoor
    return tree


def build_building_tree(node: Mapping[str, Any] | None) -> SpatialTree:
    """A one-building tree for a city-map node (same as the renderer's)."""
    sector = str((node and (node.get("label") or node.get("id"))) or "Building")
    tree = _tree_from_blueprint(sector, blueprint_for(node))
    tree.layout_type = layout_type(node)
    tree.layout_label = LAYOUT_LABELS.get(tree.layout_type, "")
    return tree


_LAYOUTS: dict[str, SpatialTree] = {}


def layout(key: str) -> SpatialTree:
    """The shared tree of one blueprint (sector name = blueprint key), cached."""
    if key not in _LAYOUTS:
        _LAYOUTS[key] = _tree_from_blueprint(key, BLUEPRINTS[key])
    return _LAYOUTS[key]


# ===== simulation side: which room, how big, which flat =====
#: Rooms of the home-environment plugin → the flat layout's room types.
HOME_ROOM_TYPES = {
    "living_room": "living",
    "bedroom": "bedroom",
    "bedroom_2": "bedroom",
    "kitchen": "kitchen",
    "study": "study",
    "bathroom": "bathroom",
    "balcony": "living",
}


def room_share(key: str, arena: str) -> float:
    """The room's share of its building's floor plan (shares sum to 1)."""
    for r in BLUEPRINTS[key]["rooms"]:
        if r["name"] == arena:
            return float(r["w"]) * float(r["h"])
    return 0.0


def room_type(key: str, arena: str) -> str:
    for r in BLUEPRINTS[key]["rooms"]:
        if r["name"] == arena:
            return str(r["type"])
    return ""


def room_label(key: str, arena: str) -> str:
    """A room's name for a resident to read: 座位区, 卧室 (Bedroom 2)…"""
    zh = ROOM_TYPE_ZH.get(room_type(key, arena), "")
    return zh or arena


def candidate_rooms(
    key: str,
    slot: str | None,
    *,
    staff: bool = False,
    resident: bool = False,
    home_type: str | None = None,
) -> list[str]:
    """Rooms suited to *slot* here, best first; empty when none is.

    Rooms owning an object for the slot come first (in plan order), then rooms
    owning one for an alias (:data:`SLOT_ALIASES`), then rooms of that type.
    Visitors never get ``staff_only`` rooms. With *home_type* (a resident at
    home whose home plugin already picked a room) only rooms of that type
    count, so the room the resident is told about is the room they are in.
    """
    bp = BLUEPRINTS[key]
    if home_type:
        typed = [r["name"] for r in bp["rooms"] if r["type"] == home_type]
        if typed:
            return typed
    blocked = set() if (staff or resident) else set(bp.get("staff_only") or [])
    out: list[str] = []
    if slot:
        tree = layout(key)
        for wanted in [slot, *SLOT_ALIASES.get(slot, [])]:
            out += [rec["arena"] for rec in tree.by_slot(wanted)]
        out += [r["name"] for r in bp["rooms"] if r["type"] == slot]
    return [n for n in dict.fromkeys(out) if n not in blocked]


def fallback_rooms(key: str, *, staff: bool = False) -> list[str]:
    """Where someone with nothing room-specific to do stands: the staff room
    for the people who work here, then the building's default room."""
    bp = BLUEPRINTS[key]
    return list(dict.fromkeys(([bp["staff"]] if staff else []) + [bp["default"]]))


def rooms_for(
    key: str,
    slot: str | None,
    *,
    staff: bool = False,
    resident: bool = False,
    home_type: str | None = None,
) -> list[str]:
    """The rooms a resident may be in for *slot*, best first. Never empty."""
    return candidate_rooms(key, slot, staff=staff, resident=resident, home_type=home_type) or fallback_rooms(
        key, staff=staff
    )


def pick_objects(key: str, arena: str, slot: str | None) -> list[str]:
    """Objects in *arena* that serve *slot* (or an alias), best first."""
    if not slot:
        return []
    records = layout(key).objects(key, arena)
    out: list[str] = []
    for wanted in [slot, *SLOT_ALIASES.get(slot, [])]:
        out += [rec["object"] for rec in records if rec["slot"] == wanted]
    return list(dict.fromkeys(out))


def pick_object(key: str, arena: str, slot: str | None, taken: Iterable[str] = ()) -> str | None:
    """A free object for *slot* (or an alias) in *arena*; None when none is free."""
    used = set(taken)
    return next((name for name in pick_objects(key, arena, slot) if name not in used), None)


def _flat_names(interior: Mapping[str, Any] | None) -> list[str]:
    names: list[str] = []
    for floor in (interior or {}).get("floors") or []:
        units = [str(u) for u in floor.get("units") or [] if str(u)]
        if units:
            names += units
        elif floor.get("name"):
            names.append(str(floor["name"]))
    return list(dict.fromkeys(names))


def _floor_of(name: str) -> int:
    m = re.match(r"\s*(\d+)", str(name))
    return int(m.group(1)) if m else 0


def building_units(interior: Mapping[str, Any] | None, needed: int) -> list[str]:
    """The flats of a building, with floors added on top until *needed* fit.

    Added floors repeat the top floor's flat count (4 when the citymap lists
    none) and follow the procedural ``3A / 3B`` naming.
    """
    units = _flat_names(interior)
    if len(units) >= needed:
        return units
    top = max((_floor_of(u) for u in units), default=0)
    per_floor = sum(1 for u in units if _floor_of(u) == top) if units and top else 4
    per_floor = max(1, min(per_floor, 26))
    floor = top
    while len(units) < needed:
        floor += 1
        for i in range(per_floor):
            name = f"{floor}{chr(ord('A') + i)}"
            if name not in units:
                units.append(name)
    return units


def _stable_hash(value: str) -> int:
    return int.from_bytes(hashlib.md5(str(value).encode("utf-8")).digest()[:8], "big")


def assign_units(
    households: Iterable[str], interior: Mapping[str, Any] | None, assigned: dict[str, str] | None = None
) -> dict[str, str]:
    """Give each household in one building its own flat.

    Deterministic: households are seated in sorted order, each taking the free
    flat a hash of its key points at. *assigned* (household → flat) is kept,
    so a household that moves in later does not reshuffle the others.
    """
    out = dict(assigned or {})
    new = sorted({str(h) for h in households} - set(out))
    if not new:
        return out
    units = building_units(interior, len(out) + len(new))
    free = [u for u in units if u not in set(out.values())]
    for household in new:
        start = _stable_hash(household) % len(free)
        out[household] = free.pop(start)
    return out


def household_key(agent: Mapping[str, Any]) -> str:
    """The family plugin's household id, else the resident alone."""
    family = ((agent.get("ext") or {}).get("family") or {}) if isinstance(agent, Mapping) else {}
    hid = family.get("household_id") if isinstance(family, Mapping) else None
    return str(hid) if hid else f"agent-{agent.get('id')}"


def room_key(agent: Mapping[str, Any]) -> tuple[str, str] | None:
    """(flat, room) the resident was placed in at their current place, if known."""
    locations = agent.get("locations") or {}
    room = locations.get("room")
    if not isinstance(room, Mapping) or locations.get("in_transit"):
        return None
    if room.get("node") != locations.get("current"):
        return None
    return str(room.get("unit") or ""), str(room.get("arena") or "")


def same_room(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """Are two residents at the same place also in the same room?

    True whenever either has no room for where they stand (rooms off, or not
    placed yet), so with ``local_physical.rooms`` off nothing changes.
    """
    ka, kb = room_key(a), room_key(b)
    return ka is None or kb is None or ka == kb


__all__ = [
    "BLUEPRINTS",
    "BLUEPRINT_ALIASES",
    "HOME_ROOM_TYPES",
    "LAYOUT_LABELS",
    "ROOM_TYPE_ZH",
    "SLOT_ALIASES",
    "WORLD",
    "SpatialTree",
    "activity_slot",
    "assign_units",
    "blueprint_for",
    "blueprint_key",
    "build_building_tree",
    "building_units",
    "candidate_rooms",
    "fallback_rooms",
    "household_key",
    "is_residential",
    "layout",
    "layout_type",
    "pick_object",
    "pick_objects",
    "room_key",
    "room_label",
    "room_share",
    "room_type",
    "rooms_for",
    "same_room",
]
