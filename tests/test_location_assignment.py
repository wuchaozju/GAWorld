"""Tests for gravity-based home / workplace assignment.

The original rule — take the nearest node matching the job's category —
gave everyone with the same kind of job the same building. Measured on
``data/citymap.md`` it put 56% of commuters at one node and left 89% of the
road network carrying no traffic at all, which makes any spatial quantity
measured on that map an artifact of the assignment rather than a finding.

Pinned here: ``nearest`` still behaves the old way, ``gravity`` spreads,
capacity and distance both steer the draw, homes use their own gentler
distance exponent, and the whole thing stays reproducible under a seed.
"""

from __future__ import annotations

import collections
import os
import random
import tempfile
import unittest
from unittest.mock import patch

from gaworld.settings import CONFIG
from gaworld.sim import _location as loc
from gaworld.world import city_map as cm


def _map():
    """Symmetric around ``Centre`` so the map's geometric centre is that node.

    Two offices and two housing blocks, each pair at 1 km and 4 km out. The
    far office is three times the size of the near one, so capacity and
    distance pull against each other by construction; the two housing blocks
    are the same size, so only distance separates them.
    """
    content = (
        "# City Map\n"
        "@node: Centre | kind=hub | category=mixed | x=0.0 | y=0.0 | capacity=100\n"
        "@node: Office Near | kind=hub | category=commerce | x=1.0 | y=0.0 | capacity=200\n"
        "@node: Office Far | kind=hub | category=commerce | x=4.0 | y=0.0 | capacity=600\n"
        "@node: Homes Near | kind=hub | category=residential | x=-1.0 | y=0.0 | capacity=200\n"
        "@node: Homes Far | kind=hub | category=residential | x=-4.0 | y=0.0 | capacity=200\n"
        "\n- City: Demo\n  - Hub: Centre\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "m.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return cm.load_city_map(path)


def _agent():
    return {"id": 1, "job": "销售经理", "personality": "", "daily_life": "", "values": ""}


def _cfg(**overrides):
    merged = dict(loc._DEFAULT_LOCATION_ASSIGNMENT)
    merged.update(overrides)
    return patch.dict(CONFIG, {"location_assignment": merged}, clear=False)


def _workplaces(city_map, count, seed=7, **overrides):
    """Workplace draws from a *fixed* home, to isolate the workplace rule."""
    random.seed(seed)
    with _cfg(**overrides):
        return collections.Counter(
            loc._infer_workplace(_agent(), city_map, home_node="Centre")
            for _ in range(count)
        )


def _homes(city_map, count, seed=7, **overrides):
    random.seed(seed)
    with _cfg(**overrides):
        return collections.Counter(loc._infer_home(_agent(), city_map) for _ in range(count))


class TestNearestIsUnchanged(unittest.TestCase):
    def test_nearest_sends_everyone_to_the_same_building(self):
        self.assertEqual(
            dict(_workplaces(_map(), 40, mode="nearest")), {"Office Near": 40}
        )


class TestGravitySpreads(unittest.TestCase):
    def test_both_offices_get_staff(self):
        places = _workplaces(_map(), 400)
        self.assertGreater(places["Office Near"], 0)
        self.assertGreater(places["Office Far"], 0)

    def test_without_distance_the_draw_is_purely_size(self):
        """Office Far holds 3x the people, so it should take ~3/4 of the draws."""
        places = _workplaces(_map(), 600, distance_decay=0.0)
        share = places["Office Far"] / 600
        self.assertGreater(share, 0.65)
        self.assertLess(share, 0.85)

    def test_a_steep_decay_collapses_back_onto_the_nearest(self):
        places = _workplaces(_map(), 400, distance_decay=12.0)
        self.assertGreater(places["Office Near"] / 400, 0.95)


class TestHomesUseTheirOwnDecay(unittest.TestCase):
    def test_a_steeper_home_decay_pulls_people_towards_the_centre(self):
        steep = _homes(_map(), 400, home_distance_decay=8.0)
        flat = _homes(_map(), 400, home_distance_decay=0.0)
        self.assertGreater(steep["Homes Near"] / 400, flat["Homes Near"] / 400)

    def test_equal_blocks_split_evenly_with_no_decay(self):
        homes = _homes(_map(), 600, home_distance_decay=0.0)
        self.assertAlmostEqual(homes["Homes Near"] / 600, 0.5, delta=0.08)

    def test_the_workplace_exponent_does_not_move_homes(self):
        """Distance from the centre and distance from home are different
        preferences; sharing one exponent conflates them."""
        self.assertEqual(
            _homes(_map(), 300, distance_decay=0.0),
            _homes(_map(), 300, distance_decay=12.0),
        )


class TestReproducible(unittest.TestCase):
    def _town(self, seed):
        random.seed(seed)
        with _cfg():
            return [
                tuple(sorted(loc.assign_agent_locations(_agent(), _map()).items()))
                for _ in range(20)
            ]

    def test_same_seed_same_town(self):
        self.assertEqual(self._town(11), self._town(11))

    def test_different_seed_different_town(self):
        self.assertNotEqual(self._town(11), self._town(12))


class TestCandidateCap(unittest.TestCase):
    """0 means "every node of the right category inside the search radius".

    A fixed top-k cuts the pool wherever the k-th nearest node happens to
    sit: on the default map that hid 8 of 20 residential blocks behind a
    3 km line drawn across a 19 km city.
    """

    def test_zero_means_no_cap(self):
        self.assertEqual(loc._candidate_cap(0), loc._NO_CAP)
        self.assertEqual(loc._candidate_cap(None), loc._NO_CAP)
        self.assertEqual(loc._candidate_cap("nonsense"), loc._NO_CAP)
        self.assertEqual(loc._candidate_cap(-3), loc._NO_CAP)

    def test_a_positive_cap_is_honoured(self):
        self.assertEqual(loc._candidate_cap(5), 5)

    def test_capping_to_one_collapses_onto_the_nearest(self):
        places = _workplaces(_map(), 200, workplace_candidates=1)
        self.assertEqual(dict(places), {"Office Near": 200})

    def test_the_default_reaches_the_far_office(self):
        self.assertGreater(_workplaces(_map(), 400)["Office Far"], 0)


class TestGravityPickEdgeCases(unittest.TestCase):
    def test_single_candidate_is_returned(self):
        self.assertEqual(loc._gravity_pick(_map(), [("Office Near", 1.0)], 1.5), "Office Near")

    def test_unknown_node_does_not_raise(self):
        self.assertIn(
            loc._gravity_pick(_map(), [("Nowhere", 1.0), ("Office Near", 2.0)], 1.5),
            {"Nowhere", "Office Near"},
        )


if __name__ == "__main__":
    unittest.main()
