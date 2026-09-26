"""Occupancy recording — the input Track B needs, and nothing else writes.

``update_occupancy_from_agents`` has always computed who is where; the result
fed perception and was then dropped. Track B's spatial experiment needs it
kept, so it can be recorded — off by default, because no run should grow an
artifact it did not ask for.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from gaworld.kernel import build_kernel
from gaworld.world.plugin import LocalPhysicalPlugin


def _ctx(local_physical):
    return build_kernel(
        {"local_physical": local_physical,
         "records": {"output_dir": tempfile.mkdtemp()}},
        load_entry_points=False,
    )


def _tick(ctx, agents):
    rows = []
    ctx.recorder.record = lambda table, data: rows.append((table, data))
    ctx.bus.emit("on_time_tick", day=3, time_str="09:00",
                 city_map={"nodes": {}, "runtime": {}}, agents=agents)
    return rows


AGENTS = [
    {"id": 1, "locations": {"current": "Plaza"}},
    {"id": 2, "locations": {"current": "Plaza"}},
    {"id": 3, "locations": {"current": "Home Block"}},
]


class TestOccupancyRecording(unittest.TestCase):
    def test_off_by_default(self):
        self.assertEqual(_tick(_ctx({"enabled": True}), AGENTS), [])

    def test_on_request_it_records_the_distribution(self):
        ctx = _ctx({"enabled": True, "record_occupancy": True})
        LocalPhysicalPlugin().setup(ctx)
        rows = _tick(ctx, AGENTS)
        self.assertEqual([table for table, _ in rows], ["spatial.occupancy"])
        data = rows[0][1]
        self.assertEqual(data["counts"], {"Plaza": 2, "Home Block": 1})
        self.assertEqual(data["people"], 3)
        self.assertEqual(data["nodes"], 2)

    def test_an_empty_town_writes_nothing(self):
        ctx = _ctx({"enabled": True, "record_occupancy": True})
        LocalPhysicalPlugin().setup(ctx)
        self.assertEqual(_tick(ctx, []), [])

    def test_the_layer_being_off_wins(self):
        ctx = _ctx({"enabled": False, "record_occupancy": True})
        LocalPhysicalPlugin().setup(ctx)
        self.assertEqual(_tick(ctx, AGENTS), [])


if __name__ == "__main__":
    unittest.main()
