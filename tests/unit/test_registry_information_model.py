"""
Unit tests for INFORMATION_MODEL_MAP registry and helper functions.

Note: These tests use deferred imports to avoid httpx dependency issues
in the test environment. The registry module imports web_actions which
requires httpx, but we don't need that for testing the information model.
"""
from fos.core.experiment.information_model import InformationModel


def test_all_scene_map_keys_have_information_model():
    from fos.core.registry import INFORMATION_MODEL_MAP, SCENE_MAP

    for key in SCENE_MAP:
        assert key in INFORMATION_MODEL_MAP, (
            f"INFORMATION_MODEL_MAP missing entry for SCENE_MAP key {key!r}"
        )


def test_get_information_model_known_scenes():
    from fos.core.registry import get_information_model

    for key in ["village_scene", "werewolf_scene", "experiment_template", "generic_scene"]:
        model = get_information_model(key)
        assert isinstance(model, InformationModel)


def test_get_information_model_default_fallback():
    from fos.core.registry import get_information_model

    model = get_information_model("nonexistent_scene_xyz")
    assert isinstance(model, InformationModel)
    assert model.scope_type == "all"


def test_get_information_model_derives_council_chamber_from_scenario_registry():
    from fos.core.registry import get_information_model

    model = get_information_model("council_chamber")

    assert isinstance(model, InformationModel)
    assert model.scope_type == "all"
    assert model.include_scores is False


def test_get_information_model_derives_contagion_neighborhood_scope():
    from fos.core.registry import get_information_model

    model = get_information_model("contagion")

    assert isinstance(model, InformationModel)
    assert model.scope_type == "neighborhood"
    assert model.include_scores is False


def test_get_information_model_derives_custom_neighborhood_scope():
    from fos.core.registry import get_information_model

    model = get_information_model("custom")

    assert isinstance(model, InformationModel)
    assert model.scope_type == "neighborhood"
    assert model.include_scores is False


def test_pair_agents_randomly_is_deterministic():
    from fos.core.registry import pair_agents_randomly

    agents = ["Alice", "Bob", "Charlie", "David"]
    p1 = pair_agents_randomly(agents, round_num=1)
    p2 = pair_agents_randomly(agents, round_num=1)
    assert p1 == p2


def test_pair_agents_randomly_does_not_affect_global_random():
    from fos.core.registry import pair_agents_randomly
    import random

    random.seed(42)
    before = random.random()
    random.seed(42)
    pair_agents_randomly(["A", "B", "C", "D"], round_num=7)
    after = random.random()
    assert before == after  # global state untouched


def test_pair_agents_randomly_returns_correct_shape():
    from fos.core.registry import pair_agents_randomly

    agents = ["A", "B", "C", "D"]
    pairs = pair_agents_randomly(agents, round_num=1)
    assert len(pairs) == 2
    all_paired = [a for pair in pairs for a in pair]
    assert set(all_paired) == set(agents)


def test_werewolf_visibility_scope_mafia_see_each_other():
    from fos.core.registry import werewolf_visibility_scope

    state = {"roles": {"Alice": "mafia", "Bob": "mafia", "Charlie": "villager"}}
    obs = werewolf_visibility_scope("Alice", state, ["Alice", "Bob", "Charlie"])
    assert set(obs) == {"Alice", "Bob"}


def test_werewolf_visibility_scope_villager_sees_self():
    from fos.core.registry import werewolf_visibility_scope

    state = {"roles": {"Alice": "mafia", "Charlie": "villager"}}
    obs = werewolf_visibility_scope("Charlie", state, ["Alice", "Charlie"])
    assert obs == ["Charlie"]
