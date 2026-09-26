"""Who can choose to drive, decided from income.

Mode choice had no ownership test: a 6-10 km trip without metro access simply
became a car trip. Adding the condition does *not* close the transit-share
anchor gap — it widens it, because a non-owner in that band now takes the bus.
That is a finding about the mode ladder, not a reason to drop the condition:
without it, residents with no car still drove.
"""

from __future__ import annotations

import random
import unittest

from gaworld.world import traffic as tf


def _people(incomes, age=35):
    return [{"id": i, "monthly_income": v, "age": age} for i, v in enumerate(incomes)]


def _rng():
    return random.Random("test")


class TestOwnershipFollowsIncome(unittest.TestCase):
    def test_richer_residents_own_cars_more_often(self):
        """Spread across a realistic range, not two clumps: the pivot is a
        multiple of the *median*, so a bimodal fixture puts the median inside
        one of the clumps and says nothing about the gradient."""
        incomes = [1500.0 * (1.25 ** i) for i in range(24)] * 25
        everyone = _people(incomes)
        tf.assign_car_ownership(everyone, rng=_rng())
        ranked = sorted(everyone, key=lambda a: a["monthly_income"])
        quarter = len(ranked) // 4
        poor_rate = sum(1 for a in ranked[:quarter] if a["has_car"]) / quarter
        rich_rate = sum(1 for a in ranked[-quarter:] if a["has_car"]) / quarter
        self.assertLess(poor_rate, 0.1)
        self.assertGreater(rich_rate, 0.9)

    def test_the_pivot_scales_to_the_town_not_to_an_absolute_figure(self):
        """The same parameters must transfer to a richer population."""
        modest = _people([3000.0, 5000.0, 8000.0, 12000.0] * 60)
        wealthy = _people([30000.0, 50000.0, 80000.0, 120000.0] * 60)
        a = tf.assign_car_ownership(modest, rng=_rng())
        b = tf.assign_car_ownership(wealthy, rng=_rng())
        self.assertAlmostEqual(a, b, delta=0.08)

    def test_a_higher_pivot_means_fewer_owners(self):
        cheap = tf.assign_car_ownership(_people([8000.0] * 200), pivot_multiple=1.0, rng=_rng())
        dear = tf.assign_car_ownership(_people([8000.0] * 200), pivot_multiple=4.0, rng=_rng())
        self.assertGreater(cheap, dear)

    def test_nobody_under_the_driving_age_owns_one(self):
        kids = _people([90000.0] * 50, age=15)
        tf.assign_car_ownership(kids, rng=_rng())
        self.assertTrue(all(a["has_car"] is False for a in kids))

    def test_no_income_means_no_car_and_no_crash(self):
        people = [{"id": 1, "age": 40}, {"id": 2, "monthly_income": 0.0, "age": 40}]
        self.assertEqual(tf.assign_car_ownership(people, rng=_rng()), 0.0)
        self.assertTrue(all(a["has_car"] is False for a in people))

    def test_an_empty_town_is_safe(self):
        self.assertEqual(tf.assign_car_ownership([], rng=_rng()), 0.0)
        self.assertEqual(tf.assign_car_ownership(None, rng=_rng()), 0.0)

    def test_the_same_seed_gives_the_same_owners(self):
        first = _people([4000.0, 9000.0, 20000.0] * 40)
        second = _people([4000.0, 9000.0, 20000.0] * 40)
        tf.assign_car_ownership(first, rng=random.Random("s"))
        tf.assign_car_ownership(second, rng=random.Random("s"))
        self.assertEqual([a["has_car"] for a in first], [a["has_car"] for a in second])


class TestModeChoiceRespectsOwnership(unittest.TestCase):
    """A resident without a car must not produce a car trip."""

    def setUp(self):
        from tests.test_location_system import _metro_map

        self.city_map = _metro_map()

    def _mode(self, has_car, origin="Midtown", target="Outpost"):
        from gaworld.world.city_map import choose_transport_mode

        agent = {"job": "工程师", "daily_life": "", "personality": "", "has_car": has_car}
        return choose_transport_mode(agent, self.city_map, origin, target)[0]

    def test_an_owner_drives_the_medium_trip(self):
        self.assertEqual(self._mode(True), "car")

    def test_a_non_owner_takes_the_bus_instead(self):
        self.assertEqual(self._mode(False), "bus")


class TestTwoWheelerOwnership(unittest.TestCase):
    """The assumption the scored mode model exposed.

    Cars were modelled; the thing most people actually ride was not, so every
    resident was treated as having a two-wheeler and the cheapest, quickest
    option was available to everyone — active travel came out at 98.5% of
    commutes. Anchor: China's e-bike stock passed 400 million in 2024 against
    ~1.41 billion people (~0.28 each, all ages), and ownership among
    working-age commuters runs above that population-wide figure.
    """

    def test_two_wheelers_are_far_commoner_than_cars(self):
        """They are cheap, so the curve is flat and the pivot sits low."""
        incomes = [1500.0 * (1.25 ** i) for i in range(24)] * 25
        cars = _people(incomes)
        bikes = _people(incomes)
        car_rate = tf.assign_car_ownership(cars, rng=_rng())
        bike_rate = tf.assign_two_wheeler_ownership(bikes, rng=_rng())
        self.assertGreater(bike_rate, car_rate * 1.3)

    def test_it_still_follows_income(self):
        incomes = [1500.0 * (1.25 ** i) for i in range(24)] * 25
        everyone = _people(incomes)
        tf.assign_two_wheeler_ownership(everyone, rng=_rng())
        ranked = sorted(everyone, key=lambda a: a["monthly_income"])
        quarter = len(ranked) // 4
        poor = sum(1 for a in ranked[:quarter] if a["has_two_wheeler"]) / quarter
        rich = sum(1 for a in ranked[-quarter:] if a["has_two_wheeler"]) / quarter
        self.assertGreater(rich, poor)

    def test_children_do_not_own_one(self):
        kids = _people([90000.0] * 50, age=12)
        tf.assign_two_wheeler_ownership(kids, rng=_rng())
        self.assertTrue(all(a["has_two_wheeler"] is False for a in kids))

    def test_the_two_decisions_are_independent(self):
        people = _people([9000.0] * 200)
        tf.assign_car_ownership(people, rng=random.Random("a"))
        tf.assign_two_wheeler_ownership(people, rng=random.Random("b"))
        self.assertTrue(any(a["has_car"] and a["has_two_wheeler"] for a in people))
        self.assertTrue(any(not a["has_car"] and a["has_two_wheeler"] for a in people))


class TestTheLadderRespectsTwoWheelers(unittest.TestCase):
    """The 1.2-3.2 km band *was* the ownership assumption."""

    def setUp(self):
        from tests.test_location_system import _metro_map

        self.city_map = _metro_map()

    def _mode(self, **flags):
        from gaworld.world.city_map import choose_transport_mode

        agent = {"job": "工程师", "daily_life": "", "personality": "", **flags}
        return choose_transport_mode(agent, self.city_map, "West End", "Midtown")[0]

    def test_an_owner_still_rides(self):
        self.assertEqual(self._mode(has_two_wheeler=True), "e-bike")

    def test_someone_without_one_does_not(self):
        self.assertNotIn(self._mode(has_two_wheeler=False), ("bike", "e-bike"))

    def test_a_corpus_with_no_ownership_field_is_unchanged(self):
        """Older agents carry no flag; they must keep the old behaviour."""
        self.assertEqual(self._mode(), "e-bike")


if __name__ == "__main__":
    unittest.main()
