"""Regression tests for task 2875 (fresh GAWorld SimTree 500).

Written TDD-RED before any fix. Each class pins one defect:

- Path resolver — ``resolve_gaworld_path`` must fall back to the repo parent
  (the integrated-launch contract already used by the experiments route) when
  neither a startup snapshot nor ``GAWORLD_PATH`` is set, so a fresh sim's
  first ``GET tree/graph`` no longer 500s with ``gaworld.error.path_not_set``.
- City-aware roster — ``resolve_gaworld_agent_ids`` must validate against the
  simulation's city, not the server default.
- Typed errors — ``get_tree_record`` maps GAWorld path/unavailable failures to
  503 and an unknown roster to 409 instead of an opaque 500.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from litestar.exceptions import HTTPException

from fos.backend.services.simtree_gaworld import (
    resolve_gaworld_agent_ids,
    resolve_gaworld_path,
)


# ---------------------------------------------------------------------------
# Resolver fallback (integrated launch, no GAWORLD_PATH env)
# ---------------------------------------------------------------------------


class TestResolverFallback:
    def test_env_unset_falls_back_to_repo_parent(self, monkeypatch):
        """With no env and no startup path, the repo root containing a
        ``gaworld/`` directory ancestor of this module resolves (the
        in-process repro of the old ``path_not_set`` 500)."""
        monkeypatch.delenv("GAWORLD_PATH", raising=False)
        resolved = resolve_gaworld_path(None)
        assert resolved is not None
        assert os.path.isdir(os.path.join(resolved, "gaworld"))

    def test_startup_path_wins(self, monkeypatch):
        monkeypatch.setenv("GAWORLD_PATH", "/env/gaworld-root")
        assert resolve_gaworld_path("/startup/gaworld-root") == "/startup/gaworld-root"

    def test_env_wins_over_repo_walk(self, monkeypatch):
        monkeypatch.setenv("GAWORLD_PATH", "/env/gaworld-root")
        assert resolve_gaworld_path(None) == "/env/gaworld-root"

    def test_runtime_resolver_uses_fallback(self, monkeypatch):
        """simtree_runtime._resolve_gaworld_path() no longer returns None on
        an integrated launch (the exact repro from the debug spec)."""
        from fos.backend.services import simtree_runtime as rt

        monkeypatch.delenv("GAWORLD_PATH", raising=False)
        monkeypatch.setattr(rt, "_GAWORLD_PATH", None)
        assert rt._resolve_gaworld_path() is not None


# ---------------------------------------------------------------------------
# Fresh-sim tree build no longer raises path_not_set
# ---------------------------------------------------------------------------


class TestBuildTreeFreshSim:
    def _stub_live_ids(self, monkeypatch, per_city: dict[str, set[str]]):
        from fos.backend.services import gaworld_agents as svc

        def fake_get_agents(city="", limit=200, offset=0):
            ids = sorted(per_city.get(city or "", set()))
            page = [{"id": int(a)} for a in ids[offset : offset + limit]]
            return {"agents": page, "total": len(ids)}

        monkeypatch.setattr(svc, "get_agents", fake_get_agents)

    def _record(self):
        return SimpleNamespace(
            id="ab12cd34",
            scene_type="gaworld_scene",
            scene_config={"scene_type": "gaworld_scene"},
            agent_config={"city": "liuxi"},
            latest_state=None,
            name="fresh sim",
            description="",
            notes="",
        )

    def test_build_tree_resolves_without_env(self, monkeypatch):
        """The debug-spec in-process repro: _build_tree_for_sim on a fresh
        gaworld sim with no env must NOT raise path_not_set."""
        import fos.backend.services.simtree_runtime as rt
        import fos.core.experiment.scenes.gaworld as gw_module

        monkeypatch.delenv("GAWORLD_PATH", raising=False)
        monkeypatch.setattr(rt, "_GAWORLD_PATH", None)
        monkeypatch.setattr(
            rt, "_resolve_gaworld_agents", lambda cfg: [{"id": 1}, {"id": 2}]
        )
        self._stub_live_ids(monkeypatch, {"liuxi": {1, 2}})

        captured: dict = {}

        class FakeScene:
            def __init__(self, config):
                captured["config"] = config

        class FakeAdapter:
            def __init__(self, scene, clients):
                captured["clients"] = clients
                self.clients = clients

        class FakeTree:
            @staticmethod
            def new(adapter, clients):
                captured["agent_ids"] = captured["config"].parameters.get("agent_ids")
                captured["gaworld_path"] = captured["config"].parameters.get(
                    "gaworld_path"
                )
                return object()

        monkeypatch.setattr(gw_module, "GAWorldScene", FakeScene)
        monkeypatch.setattr(rt, "ExperimentRunnerAdapter", FakeAdapter)
        monkeypatch.setattr(rt, "SimTree", FakeTree)

        tree = rt._build_tree_for_sim(self._record(), None)
        assert tree is not None
        # exactly the 2 canonical residents, no fallback to a default roster
        assert captured["agent_ids"] == ["1", "2"]
        # resolver fallback produced a real path in-process, no env needed
        assert captured["gaworld_path"]
        assert os.path.isdir(os.path.join(captured["gaworld_path"], "gaworld"))

    def test_persisted_gaworld_path_wins(self, monkeypatch):
        """A path persisted in parameters is honoured over the derived one."""
        import fos.backend.services.simtree_runtime as rt
        import fos.core.experiment.scenes.gaworld as gw_module

        monkeypatch.delenv("GAWORLD_PATH", raising=False)
        monkeypatch.setattr(
            rt, "_resolve_gaworld_agents", lambda cfg: [{"id": 1}, {"id": 2}]
        )
        self._stub_live_ids(monkeypatch, {"liuxi": {1, 2}})

        captured: dict = {}

        class FakeScene:
            def __init__(self, config):
                captured["config"] = config

        class FakeAdapter:
            def __init__(self, scene, clients):
                self.clients = clients

        class FakeTree:
            @staticmethod
            def new(adapter, clients):
                return object()

        monkeypatch.setattr(gw_module, "GAWorldScene", FakeScene)
        monkeypatch.setattr(rt, "ExperimentRunnerAdapter", FakeAdapter)
        monkeypatch.setattr(rt, "SimTree", FakeTree)

        record = self._record()
        record.scene_config = {
            "scene_type": "gaworld_scene",
            "parameters": {"gaworld_path": "/persisted/gaworld-root"},
        }
        rt._build_tree_for_sim(record, None)
        assert captured["config"].parameters["gaworld_path"] == "/persisted/gaworld-root"


# ---------------------------------------------------------------------------
# City-aware roster validation
# ---------------------------------------------------------------------------


class TestCityAwareRoster:
    def _stub_live_ids(self, monkeypatch, per_city: dict[str, set[str]]):
        from fos.backend.services import gaworld_agents as svc

        calls: list[str] = []

        def fake_get_agents(city="", limit=200, offset=0):
            calls.append(city)
            ids = sorted(per_city.get(city or "", set()))
            page = [{"id": int(a)} for a in ids[offset : offset + limit]]
            return {"agents": page, "total": len(ids)}

        monkeypatch.setattr(svc, "get_agents", fake_get_agents)
        return calls

    def test_validation_pages_the_given_city(self, monkeypatch):
        calls = self._stub_live_ids(monkeypatch, {"liuxi": {"1", "2"}})
        assert resolve_gaworld_agent_ids({}, [{"id": 1}, {"id": 2}], city="liuxi") == [
            "1",
            "2",
        ]
        assert calls and all(c == "liuxi" for c in calls)

    def test_id_valid_only_in_sim_city_passes(self, monkeypatch):
        """Agent 7 exists in the sim's city but not the server default —
        validation must query the sim's city (would fail before the fix)."""
        self._stub_live_ids(monkeypatch, {"liuxi": {"7"}, "": {"1", "2"}})
        assert resolve_gaworld_agent_ids({}, [{"id": 7}], city="liuxi") == ["7"]

    def test_id_unknown_in_sim_city_rejected(self, monkeypatch):
        self._stub_live_ids(monkeypatch, {"liuxi": {"1"}, "": {"7"}})
        with pytest.raises(ValueError, match="7"):
            resolve_gaworld_agent_ids({}, [{"id": 7}], city="liuxi")

    def test_roster_priority_preserved(self):
        """Explicit roster [1,2] beats params 1..10 (task 2845 invariant)."""
        params = {"agent_ids": [str(i) for i in range(1, 11)]}
        assert resolve_gaworld_agent_ids(
            params, [{"id": 1}, {"id": 2}], known_ids={"1", "2"}
        ) == ["1", "2"]


# ---------------------------------------------------------------------------
# Typed error mapping in get_tree_record
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None

    def all(self):
        return self._items

    def first(self):
        return self._items[0] if self._items else None

    def scalar_one(self):
        return self._items[0]


def _provider():
    return SimpleNamespace(
        id=1,
        provider="mock",
        base_url=None,
        api_key="k",
        model="m",
        config={"active": True},
    )


def _fake_session(provider):
    class _Session:
        async def execute(self, *_a, **_k):
            return _FakeResult([provider] if provider else [])

    return _Session()


class _RaisingRegistry:
    def __init__(self, exc):
        self._exc = exc

    async def get_or_create_from_sim(self, sim, clients=None):
        raise self._exc


class TestTypedErrors:
    async def _get_tree_record(self, monkeypatch, registry_exc):
        from fos.backend.api.routes.simulations import helpers

        monkeypatch.setattr(
            helpers, "SIM_TREE_REGISTRY", _RaisingRegistry(registry_exc)
        )
        sim = SimpleNamespace(id="ab12cd34")
        return await helpers.get_tree_record(sim, _fake_session(_provider()), 1)

    async def test_path_not_set_maps_to_503(self, monkeypatch):
        with pytest.raises(HTTPException) as ei:
            await self._get_tree_record(
                monkeypatch, ValueError("gaworld.error.path_not_set")
            )
        assert ei.value.status_code == 503
        assert "GAWORLD_PATH" in str(ei.value.detail)

    async def test_gaworld_unavailable_maps_to_503(self, monkeypatch):
        from fos.backend.services.gaworld_agents import GAWorldUnavailableError

        with pytest.raises(HTTPException) as ei:
            await self._get_tree_record(
                monkeypatch, GAWorldUnavailableError("GAWorld is down")
            )
        assert ei.value.status_code == 503
        assert "GAWorld is down" in str(ei.value.detail)

    async def test_unknown_roster_maps_to_409(self, monkeypatch):
        with pytest.raises(HTTPException) as ei:
            await self._get_tree_record(
                monkeypatch,
                ValueError("GAWorld: unknown agent IDs in the selected roster: ['9']"),
            )
        assert ei.value.status_code == 409
        assert "9" in str(ei.value.detail)

    async def test_provider_400s_unchanged(self, monkeypatch):
        from fos.backend.api.routes.simulations import helpers

        with pytest.raises(HTTPException) as ei:
            await helpers.get_tree_record(
                SimpleNamespace(id="X"), _fake_session(None), 1
            )
        assert ei.value.status_code == 400


# ---------------------------------------------------------------------------
# env-suggestions no-500 (fresh sim state read)
# ---------------------------------------------------------------------------


class TestEnvSuggestionsFreshSim:
    async def test_get_state_after_resolver_fix_does_not_raise_path_error(
        self, monkeypatch
    ):
        """get_simulation_state on a fresh gaworld sim enters the same rebuild
        path; the resolver fix means it no longer fails with path_not_set
        before any suggestion logic runs."""
        from fos.backend.services import environment_suggestion_service as svc
        from fos.backend.services import simtree_runtime as rt

        monkeypatch.delenv("GAWORLD_PATH", raising=False)
        monkeypatch.setattr(rt, "_GAWORLD_PATH", None)

        record = SimpleNamespace(
            id="ZZ000001",
            scene_type="gaworld_scene",
            scene_config={"scene_type": "gaworld_scene"},
            agent_config={"city": "liuxi"},
            latest_state=None,
            _suggestions_viewed_intervals=None,
        )

        async def fake_get_or_create(sim, clients=None):
            # In-process proof the rebuild path no longer raises path_not_set;
            # stub the tree so suggestion logic can proceed on a fresh sim.
            import fos.backend.services.simtree_runtime as rt_inner

            monkeypatch.setattr(
                rt_inner, "_resolve_gaworld_agents", lambda cfg: [{"id": 1}, {"id": 2}]
            )
            TestBuildTreeFreshSim()._stub_live_ids(monkeypatch, {"liuxi": {1, 2}})
            import fos.core.experiment.scenes.gaworld as gw_module

            class FakeScene:
                def __init__(self, config):
                    self.config = config

            class FakeAdapter:
                def __init__(self, scene, clients):
                    self.clients = clients

            class FakeTree:
                @staticmethod
                def new(adapter, clients):
                    return SimpleNamespace(leaves=lambda: [], serialize=lambda: {})

            monkeypatch.setattr(gw_module, "GAWorldScene", FakeScene)
            monkeypatch.setattr(rt_inner, "ExperimentRunnerAdapter", FakeAdapter)
            monkeypatch.setattr(rt_inner, "SimTree", FakeTree)
            return SimpleNamespace(
                tree=rt_inner._build_tree_for_sim(sim, None),
                _suggestions_viewed_intervals=None,
            )

        monkeypatch.setattr(
            rt.SIM_TREE_REGISTRY, "get_or_create_from_sim", fake_get_or_create
        )
        monkeypatch.setattr(rt.SIM_TREE_REGISTRY, "get", lambda key: None)

        class _Session:
            async def execute(self, *_a, **_k):
                return _FakeResult([record])

        try:
            state = await svc.get_simulation_state("zz000001", _Session(), 1)
        except ValueError as exc:
            pytest.fail(f"env-suggestions path raised: {exc}")
        assert state is None or isinstance(state, dict)
