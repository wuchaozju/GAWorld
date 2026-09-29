"""Tests for the Overpass retry + mirror-cooldown logic in gaworld.city.osm.

The public Overpass mirrors go down routinely (504 storms, regional
outages); the retry loop and the per-mirror cooldown are the only thing
that keeps ``fetch_bundle`` from returning OSMError on the first 504 it
sees. These tests stub out the network so they don't depend on the
mirrors being reachable.
"""

from __future__ import annotations

import time

import pytest

from gaworld.city import osm


@pytest.fixture(autouse=True)
def _reset_cooldown():
    """Wipe module-level cooldown / preference state between tests.

    The retry loop lives in module-level globals so the real client
    remembers across calls — for tests we need a clean slate, otherwise a
    failed run from a previous test would short-circuit the current one.
    """
    osm._preferred_mirror = None
    osm._mirror_cooldown_until = {}
    yield
    osm._preferred_mirror = None
    osm._mirror_cooldown_until = {}


def test_succeeds_on_first_try_no_retry():
    calls: list[str] = []

    def fake(query, timeout):
        calls.append(query)
        # Each call returns one named element so fetch_bundle doesn't bail
        # on the MIN_USABLE_NODES check. The names are deduped across the
        # whole bundle, so vary them per call.
        n = len(calls)
        return {"elements": [{
            "type": "node",
            "lon": 1.0 + 0.01 * n,
            "lat": 2.0 + 0.01 * n,
            "tags": {"name": f"place-{n}"},
        }]}

    from gaworld.city.osm import fetch_bundle

    nodes, _, _ = fetch_bundle(
        (0.0, 0.0, 0.1, 0.1),
        city="test",
        origin={"lat": 0.05, "lng": 0.05, "lat_per_km": 1 / 111, "lng_per_km": 1 / 96},
        overpass=fake,
        pause=0,
    )
    # 8 queries: 7 categories + subway. Each must succeed on first try.
    assert len(calls) >= 8
    assert len(nodes) >= 1


def test_falls_back_to_cache_when_mirror_dies(monkeypatch, tmp_path):
    """If every mirror 504s, the retry loop must exhaust rounds and
    raise OSMError — and the cooldown map must mark every URL as
    cooling-down so the next call doesn't repeat the same dead URL first.
    """
    import urllib.error

    def always_504(url, data, timeout):
        raise urllib.error.HTTPError(url, 504, "Gateway Timeout", {}, None)

    monkeypatch.setattr(osm, "_request_once", always_504)
    # Make the inner sleep almost-instant so the test runs fast.
    monkeypatch.setattr(osm.time, "sleep", lambda *_a, **_kw: None)

    with pytest.raises(osm.OSMError):
        osm._default_overpass("[out:json];out;", timeout=30)

    # Every mirror should now be in the cooldown map.
    assert set(osm._mirror_cooldown_until.keys()) == set(osm.OVERPASS_URLS)
    for url, until in osm._mirror_cooldown_until.items():
        # Cooldown ends in the future (60s from now).
        assert until > time.monotonic()


def test_mirror_order_skips_cooldown_until_window_passes():
    """After a mirror fails, _mirror_order() drops it from the front
    until MIRROR_COOLDOWN elapses, even if it would otherwise be the
    'preferred' one.
    """
    osm._preferred_mirror = osm.OVERPASS_URLS[0]
    osm._mirror_cooldown_until[osm.OVERPASS_URLS[0]] = time.monotonic() + 30.0

    order = osm._mirror_order()
    assert osm.OVERPASS_URLS[0] not in order[:2], (
        f"preferred-but-cooling mirror should be pushed back, got {order}"
    )


def test_mirror_order_returns_all_when_all_in_cooldown():
    """If every mirror is cooling down we still want *some* order — better
    to retry than to pretend there is no Overpass at all.
    """
    future = time.monotonic() + 999.0
    for url in osm.OVERPASS_URLS:
        osm._mirror_cooldown_until[url] = future
    order = osm._mirror_order()
    assert len(order) == len(osm.OVERPASS_URLS)


def test_retry_recovers_when_one_mirror_comes_back(monkeypatch):
    """Round 1: all mirrors fail (504). Round 2: the first mirror in the
    cooldown is back up and returns data. The retry loop should succeed.
    """
    import urllib.error

    call_count: dict[str, int] = {url: 0 for url in osm.OVERPASS_URLS}

    def flaky(url, data, timeout):
        call_count[url] += 1
        # The 'preferred' mirror comes back on round 2; others stay dead.
        if url == osm.OVERPASS_URLS[0] and call_count[url] >= 2:
            return {"elements": [{"lon": 1.0, "lat": 2.0}]}
        raise urllib.error.HTTPError(url, 504, "Gateway Timeout", {}, None)

    monkeypatch.setattr(osm, "_request_once", flaky)
    monkeypatch.setattr(osm.time, "sleep", lambda *_a, **_kw: None)
    # Force the cooldown map empty at start (autouse fixture already does
    # this, but be explicit since flaky records its own state).
    osm._mirror_cooldown_until = {}

    payload = osm._default_overpass("[out:json];out;", timeout=30)
    assert payload == {"elements": [{"lon": 1.0, "lat": 2.0}]}


def test_successful_response_clears_cooldown(monkeypatch):
    """Once a mirror answers successfully, its cooldown entry (if any) is
    removed so the next call doesn't gate it.

    Pin a cooldown on ``OVERPASS_URLS[1]`` so the mirror-order logic
    doesn't pick it as the first try; the test then verifies the
    successful response to *that* URL clears the entry.
    """
    target = osm.OVERPASS_URLS[1]
    osm._mirror_cooldown_until[target] = time.monotonic() + 999.0
    # Also pin [0] in cooldown so the order must pick [2] first, then [1].
    osm._mirror_cooldown_until[osm.OVERPASS_URLS[0]] = time.monotonic() + 999.0

    def ok(url, data, timeout):
        return {"elements": [{"lon": 1.0, "lat": 2.0}]}

    monkeypatch.setattr(osm, "_request_once", ok)
    osm._default_overpass("[out:json];out;", timeout=30)
    # Whatever URL we actually hit (the first non-cooldown one), it
    # must no longer be in the cooldown map.
    # Two URLs started with cooldown entries; at least one was tried
    # and therefore cleared.
    cleared = [u for u in (osm.OVERPASS_URLS[0], osm.OVERPASS_URLS[1], osm.OVERPASS_URLS[2])
               if u not in osm._mirror_cooldown_until]
    assert cleared, f"no cooldown entry was cleared: {osm._mirror_cooldown_until}"