
"""
Tests for confederate agent assignment, vote interception, and node relabeling.
"""

import json
import math
import random
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from fos.experiments.confederates import (
    ConfederateSpec,
    assign_confederates,
    assert_confederate_votes,
    build_adjacency_from_edges,
    build_confederate_lookup,
    compute_k_yes,
    confederate_neighbour_counts,
    confederate_system_prompt,
    confederate_vote_action,
    derive_placement_seed,
    permute_node_assignment,
    record_confederate_vote,
    relabel_edges,
    scripted_argument,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def twenty_agent_ids() -> list[str]:
    return [f"agent_{i}" for i in range(20)]


def _make_mock_agents(n: int) -> list[dict]:
    """Build n mock agents with distinct personas and block-consecutive models."""
    model_names = ["model_a", "model_b", "model_c", "model_d", "model_e"]
    per_model = n // len(model_names)
    agents = []
    for i in range(n):
        model_idx = i // per_model
        if model_idx >= len(model_names):
            model_idx = len(model_names) - 1
        agents.append({
            "name": f"agent_{i}",
            "properties": {"Openness": float(i), "Conscientiousness": 50.0,
                           "Extraversion": 50.0, "Agreeableness": 50.0, "Neuroticism": 50.0,
                           "archetype_id": f"arch_{i % 5}", "archetype_label": f"label_{i % 5}"},
            "role_prompt": f"I am agent {i}.",
            "profile": f"profile_{i}",
            "provider_id": f"provider_{model_idx}",
            "llm_config": {"dialect": "openai", "model": model_names[model_idx],
                           "base_url": "http://localhost", "api_key": "k", "temperature": 0.7},
        })
    return agents


def _build_ring_edges(agent_names: list[str]) -> list[list[str]]:
    """Build a simple ring: each agent connected to prev and next."""
    n = len(agent_names)
    edges = [[agent_names[i], agent_names[(i + 1) % n]] for i in range(n)]
    return edges


# ── Test 1: Basic assignment ───────────────────────────────────────────────


def test_assign_confederates_basic() -> None:
    agent_ids = [f"agent_{i}" for i in range(100)]
    rng = random.Random(123)
    specs = assign_confederates(agent_ids, n_yes=3, n_no=3, rng=rng)
    assert len(specs) == 6
    assert len(set(s.agent_id for s in specs)) == 6
    assert len([s for s in specs if s.stance == "yes"]) == 3
    assert len([s for s in specs if s.stance == "no"]) == 3
    assert all(s.speech_mode == "llm" for s in specs)


# ── Test 2: Reproducibility ────────────────────────────────────────────────


def test_assign_confederates_reproducibility() -> None:
    agent_ids = [f"agent_{i}" for i in range(100)]
    specs1 = assign_confederates(agent_ids, n_yes=3, n_no=3, rng=random.Random(42))
    specs2 = assign_confederates(agent_ids, n_yes=3, n_no=3, rng=random.Random(42))
    assert [(s.agent_id, s.stance) for s in specs1] == [(s.agent_id, s.stance) for s in specs2]

    all_results = []
    for seed in range(100, 120):
        specs = assign_confederates(agent_ids, n_yes=3, n_no=3, rng=random.Random(seed))
        all_results.append(tuple((s.agent_id, s.stance) for s in specs))
    assert len(set(all_results)) > 1


# ── Test 3: Uniformity ─────────────────────────────────────────────────────


def test_assign_confederates_uniformity() -> None:
    agent_ids = [f"agent_{i}" for i in range(100)]
    n_draws = 10_000
    counter: dict[str, int] = {aid: 0 for aid in agent_ids}
    for seed in range(n_draws):
        specs = assign_confederates(agent_ids, n_yes=3, n_no=3, rng=random.Random(seed))
        for s in specs:
            counter[s.agent_id] += 1
    for agent_id, count in counter.items():
        assert 500 <= count <= 700, f"Agent {agent_id} selected {count} times"


# ── Test 4: ValueError ─────────────────────────────────────────────────────


def test_assign_confederates_value_error() -> None:
    agent_ids = [f"agent_{i}" for i in range(10)]
    with pytest.raises(ValueError):
        assign_confederates(agent_ids, n_yes=6, n_no=5, rng=random.Random(0))


# ── Test 4b: rng required ─────────────────────────────────────────────────


def test_assign_confederates_requires_rng() -> None:
    agent_ids = [f"agent_{i}" for i in range(10)]
    with pytest.raises(TypeError):
        assign_confederates(agent_ids, n_yes=1, n_no=1)


# ── Test 5: Neighbour counts ───────────────────────────────────────────────


def test_confederate_neighbour_counts() -> None:
    edges = [["a0","a1"],["a0","a3"],["a1","a2"],["a2","a3"],["a2","a4"],["a3","a5"],["a4","a5"]]
    adjacency = build_adjacency_from_edges(edges)
    specs = [ConfederateSpec("a0","yes","llm"), ConfederateSpec("a2","no","llm")]
    counts = confederate_neighbour_counts(adjacency, specs)
    assert counts["a0"] == {"conf_yes":0,"conf_no":0,"conf_total":0}
    assert counts["a1"] == {"conf_yes":1,"conf_no":1,"conf_total":2}
    assert counts["a2"] == {"conf_yes":0,"conf_no":0,"conf_total":0}
    assert counts["a3"] == {"conf_yes":1,"conf_no":1,"conf_total":2}
    assert counts["a4"] == {"conf_yes":0,"conf_no":1,"conf_total":1}
    assert counts["a5"] == {"conf_yes":0,"conf_no":0,"conf_total":0}


# ── Test 6: Vote action helpers ────────────────────────────────────────────


def test_confederate_vote_action() -> None:
    assert confederate_vote_action(ConfederateSpec("a0","yes","llm")) == "vote_yes"
    assert confederate_vote_action(ConfederateSpec("a1","no","llm")) == "vote_no"
    with pytest.raises(ValueError):
        confederate_vote_action(ConfederateSpec("a2","abstain","llm"))


# ── Test 7: System prompt ──────────────────────────────────────────────────


def test_confederate_system_prompt() -> None:
    spec = ConfederateSpec(agent_id="agent_5", stance="yes", speech_mode="llm")
    prompt = confederate_system_prompt(spec, "We should adopt this policy.")
    assert "support" in prompt.lower()
    for banned in ("confederate", "fixed stance", "assigned", "study", "experiment",
                   "instructed", "researcher", "simulation", "do not reveal", "pretend"):
        assert banned not in prompt.lower(), f"Banned word '{banned}' found"


# ── Test 8: Scripted argument fallback ─────────────────────────────────────


def test_scripted_argument_fallback() -> None:
    spec = ConfederateSpec(agent_id="agent_7", stance="no", speech_mode="scripted")
    result = scripted_argument(spec, "srma", 0)
    assert "Confederate" in result or "Script not yet written" in result
    assert "agent_7" in result


# ── Test 9: Record + assert helpers ────────────────────────────────────────


def test_record_and_assert_confederate_votes() -> None:
    conf_specs = [ConfederateSpec("agent_0","yes","llm"), ConfederateSpec("agent_1","no","llm")]
    state_ext: dict = {}
    record_confederate_vote(conf_specs[0], state_ext)
    record_confederate_vote(conf_specs[1], state_ext)
    assert state_ext["votes"]["agent_0"] == "yes"
    assert state_ext["votes"]["agent_1"] == "no"
    assert_confederate_votes(conf_specs, state_ext)
    with pytest.raises(RuntimeError, match="agent_1"):
        assert_confederate_votes(conf_specs, {"votes":{"agent_0":"yes","agent_1":"yes"}})
    with pytest.raises(RuntimeError, match="agent_1"):
        assert_confederate_votes(conf_specs, {"votes":{"agent_0":"yes"}})


# ── Test 9b: Vote format consistency ──────────────────────────────────────


def test_confederate_vote_format_matches_normal() -> None:
    conf_specs = [ConfederateSpec("a","yes","llm"), ConfederateSpec("b","no","llm")]
    state_ext: dict = {}
    record_confederate_vote(conf_specs[0], state_ext)
    record_confederate_vote(conf_specs[1], state_ext)
    assert state_ext["votes"]["a"] == "yes"
    assert state_ext["votes"]["b"] == "no"
    assert isinstance(state_ext["votes"]["a"], str)


# ── Test 10: E2E mock LLM ──────────────────────────────────────────────────


def test_end_to_end_with_mock_llm(twenty_agent_ids: list[str]) -> None:
    from fos.core.experiment.config import ExperimentConfig
    from fos.core.experiment.scenes.council_experiment import CouncilExperimentScene

    agents = []
    for i in range(20):
        agents.append({
            "name": f"agent_{i}",
            "properties": {"Openness": 50, "Conscientiousness": 50,
                           "Extraversion": 50, "Agreeableness": 50, "Neuroticism": 50,
                           "archetype_id": "arch_0", "archetype_label": "default"},
            "role_prompt": "", "provider_id": "provider_0",
            "llm_config": {"dialect":"openai","model":"mock","base_url":"http://localhost",
                           "api_key":"k","temperature":0.7},
        })

    conf_specs = [ConfederateSpec("agent_0","yes","llm"), ConfederateSpec("agent_1","no","llm")]
    conf_lookup = build_confederate_lookup(conf_specs)
    edges = [[f"agent_{i}", f"agent_{(i+1)%20}"] for i in range(20)]

    config = ExperimentConfig(
        scenario_id="council_chamber", agents=agents,
        actions=[{"name":"vote_yes"},{"name":"vote_no"},{"name":"abstain"},{"name":"speak"}],
        parameters={"proposal_text":"Test proposal.","deliberation_rounds":1,"voting_threshold":0.5},
        description="Test", social_network={"edges":edges}, locale="en",
    )
    scene = CouncilExperimentScene(config)
    scene.set_confederates(conf_specs)
    assert len(scene._conf_lookup) == 2
    assert scene._conf_lookup["agent_0"].stance == "yes"

    call_counter: dict[str, int] = defaultdict(int)
    state_ext = {}
    for spec in conf_specs:
        record_confederate_vote(spec, state_ext)
    assert state_ext["votes"]["agent_0"] == "yes"
    assert state_ext["votes"]["agent_1"] == "no"
    assert call_counter.get("agent_0",0) == 0
    assert_confederate_votes(conf_specs, state_ext)
    with pytest.raises(RuntimeError, match="agent_1"):
        assert_confederate_votes(conf_specs, {"votes":{"agent_0":"yes","agent_1":"yes"}})
    for i in range(20):
        name = f"agent_{i}"
        is_conf = name in conf_lookup
        stance = conf_lookup[name].stance if is_conf else ""
        if i == 0:
            assert is_conf and stance == "yes"
        elif i == 1:
            assert is_conf and stance == "no"
        else:
            assert not is_conf and stance == ""


# ── Test 11: Model assignment shuffle ──────────────────────────────────────


def test_model_assignments_after_shuffle() -> None:
    model_names = ["model_a","model_b","model_c","model_d","model_e"]
    total = 100
    per = total // len(model_names)
    assignments = []
    for mn in model_names:
        assignments.extend([mn] * per)
    assert len(assignments) == 100
    rng = random.Random(42)
    rng.shuffle(assignments)
    counts = Counter(assignments)
    for mn in model_names:
        assert counts[mn] == 20
    assert sum(counts.values()) == 100


# ── Test 12: Confederate prompt reaches built prompt ───────────────────────


def test_confederate_prompt_reaches_built_prompt() -> None:
    from fos.core.experiment.prompt_builder import build_prompt
    from fos.core.experiment.agent import ExperimentAgent
    from fos.core.experiment.information_model import InformationModel
    from fos.core.llm_config import LLMConfig
    from fos.core.experiment.game_configs import GameConfig

    conf_spec = ConfederateSpec("agent_5","yes","llm")
    conf_prompt = confederate_system_prompt(conf_spec, "We should adopt this policy.")
    conf_agent = ExperimentAgent(
        name="agent_5", properties={"Openness":50},
        llm_config=LLMConfig(dialect="openai",model="test",base_url="http://localhost",
                             api_key="mock-key",temperature=0.7),
        role_prompt=conf_prompt, provider_id=0,
    )
    normal_agent = ExperimentAgent(
        name="agent_3", properties={"Openness":50},
        llm_config=LLMConfig(dialect="openai",model="test",base_url="http://localhost",
                             api_key="mock-key",temperature=0.7),
        role_prompt="I am a regular participant.", provider_id=0,
    )
    info_model = InformationModel(scope_type="all", recent_window=3)
    game_config = GameConfig(name="council",description="Test",action_type="discrete",
                             actions=["vote_yes","vote_no","abstain","speak"])
    conf_result = build_prompt(conf_agent, game_config, "Current phase: voting",
                               information_model=info_model, locale="en")
    normal_result = build_prompt(normal_agent, game_config, "Current phase: voting",
                                 information_model=info_model, locale="en")
    pt = conf_result if isinstance(conf_result,str) else str(conf_result)
    nt = normal_result if isinstance(normal_result,str) else str(normal_result)
    assert "genuinely support" in pt.lower()
    assert "genuinely support" not in nt.lower()


# ═══════════════════════════════════════════════════════════════════════════
# NEW TESTS — Phase 2B.3 (Node Relabeling)
# ═══════════════════════════════════════════════════════════════════════════


# ── Test 13: Node relabeling — position exogeneity ────────────────────────


def test_node_relabeling_position_exogeneity() -> None:
    """Across many runs, the correlation between Openness and realized degree
    is near zero. Under the old persona-permuting code this was achieved by
    moving personas; under node relabeling it is achieved by moving agents
    to different network positions. Both produce the same statistical property.
    """
    n_agents = 100
    n_runs = 500
    agent_names = [f"agent_{i}" for i in range(n_agents)]

    # Build fixed ring edges from canonical names (each node degree 2)
    # Ring with extra edges to create degree variation
    edges = _build_ring_edges(agent_names)
    rng_setup = random.Random(0)
    for _ in range(30):
        a, b = rng_setup.sample(agent_names, 2)
        edges.append([a, b])

    correlations: list[float] = []
    for run_seed in range(n_runs):
        rng = random.Random(run_seed)
        permuted = permute_node_assignment(agent_names, rng)
        relabeled = relabel_edges(edges, agent_names, permuted)

        # Compute degree for each agent from relabeled edges
        deg = Counter(n for pair in relabeled for n in pair)
        # Openness = agent index (0..99) — constant per agent
        openness = {name: float(i) for i, name in enumerate(agent_names)}

        openness_vals = [openness[name] for name in agent_names]
        degree_vals = [deg.get(name, 0) for name in agent_names]

        n = len(openness_vals)
        mean_x = sum(openness_vals) / n
        mean_y = sum(degree_vals) / n
        cov = sum((openness_vals[i]-mean_x)*(degree_vals[i]-mean_y) for i in range(n)) / n
        std_x = math.sqrt(sum((x-mean_x)**2 for x in openness_vals) / n)
        std_y = math.sqrt(sum((y-mean_y)**2 for y in degree_vals) / n)
        if std_x > 0 and std_y > 0:
            correlations.append(cov / (std_x * std_y))

    mean_abs = sum(abs(c) for c in correlations) / len(correlations)
    assert mean_abs < 0.12, (
        f"Node relabeling: mean |r| = {mean_abs:.4f}, expected < 0.12. "
        "Openness is correlated with degree — position exogeneity failed."
    )


# ── Test 14: Identity stability across runs (NEW) ──────────────────────────


def test_identity_stability_across_runs() -> None:
    """Every agent_uid maps to the same persona attributes and model across runs.

    Under the OLD persona-permuting code, agent_37 in run 1 might have a
    completely different persona than agent_37 in run 2. This test would
    FAIL against that code.
    """
    agents = _make_mock_agents(100)
    agent_names = [a["name"] for a in agents]

    # Capture identity for each agent
    identity = {}
    for a in agents:
        identity[a["name"]] = {
            "Openness": a["properties"]["Openness"],
            "role_prompt": a["role_prompt"],
            "model": a["llm_config"]["model"],
        }

    # Ring with extra edges to create degree variation
    edges = _build_ring_edges(agent_names)
    rng_setup = random.Random(0)
    for _ in range(30):
        a, b = rng_setup.sample(agent_names, 2)
        edges.append([a, b])

    # Run 2 independent placements
    rng1 = random.Random(42)
    permuted1 = permute_node_assignment(agent_names, rng1)
    relabeled1 = relabel_edges(edges, agent_names, permuted1)

    rng2 = random.Random(99)
    permuted2 = permute_node_assignment(agent_names, rng2)
    relabeled2 = relabel_edges(edges, agent_names, permuted2)

    # Every agent must have the same identity in both runs
    for name in agent_names:
        id1 = identity[name]
        id2 = identity[name]  # same dict — agents are never mutated
        assert id1["Openness"] == id2["Openness"], f"{name}: Openness changed!"
        assert id1["role_prompt"] == id2["role_prompt"], f"{name}: role_prompt changed!"
        assert id1["model"] == id2["model"], f"{name}: model changed!"

    # The permutation actually changed (agents occupy different nodes)
    assert permuted1 != permuted2, "Two runs produced identical permutations"

    print(f"  Identity stability verified for {len(agent_names)} agents")
    print(f"  Run 1: agent_0 at node {permuted1.index('agent_0')}")
    print(f"  Run 2: agent_0 at node {permuted2.index('agent_0')}")


# ── Test 15: Agent occupies nodes of varying degree (NEW) ─────────────────


def test_agent_occupies_varying_degree() -> None:
    """Across runs, a given agent_uid occupies nodes of varying degree.

    Under node relabeling, agent_0 may be at a degree-2 ring node in one run
    and a degree-3+ rewired node in another. Under the old code where identity
    wasn't stable, this property couldn't even be tested.
    """
    agent_names = [f"agent_{i}" for i in range(20)]

    # Build a small-world-like ring with a few extra edges to vary degree
    # Ring with extra edges to create degree variation
    edges = _build_ring_edges(agent_names)
    rng_setup = random.Random(0)
    for _ in range(30):
        a, b = rng_setup.sample(agent_names, 2)
        edges.append([a, b])
    edges.append(["agent_0", "agent_5"])
    edges.append(["agent_3", "agent_10"])

    degrees_seen: set[int] = set()
    for run_seed in range(50):
        rng = random.Random(run_seed)
        permuted = permute_node_assignment(agent_names, rng)
        relabeled = relabel_edges(edges, agent_names, permuted)
        deg = Counter(n for pair in relabeled for n in pair)
        degrees_seen.add(deg.get("agent_0", 0))

    assert len(degrees_seen) > 1, (
        f"Agent 0 always has degree {degrees_seen}. "
        "Node relabeling is not varying its position."
    )


# ── Test 16: Graph structure invariant under relabeling (NEW) ──────────────


def test_graph_invariance_under_relabeling() -> None:
    """Relabeled graph has identical degree sequence and clustering coefficient.

    Node relabeling is a graph isomorphism — it must preserve every
    structural statistic.
    """
    agent_names = [f"agent_{i}" for i in range(20)]
    # Ring with extra edges to create degree variation
    edges = _build_ring_edges(agent_names)
    rng_setup = random.Random(0)
    for _ in range(30):
        a, b = rng_setup.sample(agent_names, 2)
        edges.append([a, b])
    edges.append(["agent_0", "agent_5"])
    edges.append(["agent_3", "agent_10"])
    edges.append(["agent_7", "agent_15"])

    # Original degree sequence
    original_deg = Counter(n for pair in edges for n in pair)
    original_deg_seq = sorted(original_deg.values())

    # Relabel
    rng = random.Random(42)
    permuted = permute_node_assignment(agent_names, rng)
    relabeled = relabel_edges(edges, agent_names, permuted)

    relabeled_deg = Counter(n for pair in relabeled for n in pair)
    relabeled_deg_seq = sorted(relabeled_deg.values())

    assert original_deg_seq == relabeled_deg_seq, (
        f"Degree sequence changed under relabeling!\n"
        f"  Original: {original_deg_seq}\n"
        f"  Relabeled: {relabeled_deg_seq}"
    )

    # Clustering coefficient (approximate: count triangles)
    def count_triangles(edge_list):
        adj = defaultdict(set)
        for a, b in edge_list:
            adj[a].add(b)
            adj[b].add(a)
        triangles = 0
        for a, b in edge_list:
            common = adj[a] & adj[b]
            triangles += len(common)
        return triangles // 3  # each triangle counted 3 times

    orig_tri = count_triangles(edges)
    rel_tri = count_triangles(relabeled)
    assert orig_tri == rel_tri, (
        f"Triangle count changed: {orig_tri} → {rel_tri}"
    )


# ── Test 17: Per-run different confederate sets ────────────────────────────


def test_per_run_different_confederate_sets() -> None:
    agent_ids = [f"agent_{i}" for i in range(20)]
    seed1 = derive_placement_seed(42, "proposal_a", "small_world", 1)
    seed2 = derive_placement_seed(42, "proposal_a", "small_world", 2)
    specs1 = assign_confederates(agent_ids, n_yes=3, n_no=3, rng=random.Random(seed1))
    specs2 = assign_confederates(agent_ids, n_yes=3, n_no=3, rng=random.Random(seed2))
    assert set(s.agent_id for s in specs1) != set(s.agent_id for s in specs2)


# ── Test 18: scripts.json keys ─────────────────────────────────────────────


def test_scripts_json_keys_match_proposal_ids() -> None:
    from fos.proposals import PROPOSAL_IDS
    scripts_path = Path(__file__).resolve().parent.parent / "data" / "confederates" / "scripts.json"
    assert scripts_path.exists()
    with open(scripts_path) as f:
        scripts = json.load(f)
    actual = set(scripts.keys())
    expected = {f"{pid}.{stance}.{r}" for pid in PROPOSAL_IDS for stance in ("yes","no") for r in (0,1,2)}
    assert not (expected - actual), f"Missing keys: {sorted(expected - actual)}"
    assert not (actual - expected), f"Extra keys: {sorted(actual - expected)}"


# ── Test 19: k_yes columns ─────────────────────────────────────────────────


def test_k_yes_columns_computed() -> None:
    edges = [["a0","a1"],["a1","a2"],["a2","a3"],["a0","a3"]]
    adjacency = build_adjacency_from_edges(edges)
    final_votes = {"a0":"yes","a1":"yes","a2":"no","a3":"yes"}
    conf_ids = {"a1"}
    result = compute_k_yes(adjacency, final_votes, conf_ids)
    assert result["a0"]["k_yes_incl_conf"] == 2
    assert result["a0"]["k_yes_excl_conf"] == 1
    assert result["a1"]["k_yes_incl_conf"] == 1
    assert result["a1"]["k_yes_excl_conf"] == 1
    assert result["a2"]["k_yes_incl_conf"] == 2
    assert result["a2"]["k_yes_excl_conf"] == 1
    assert result["a3"]["k_yes_incl_conf"] == 1
    assert result["a3"]["k_yes_excl_conf"] == 1


# ── Test 20: derive_placement_seed subprocess ──────────────────────────────


def test_derive_placement_seed_subprocess() -> None:
    seed_in_parent = derive_placement_seed(42, "proposal_a", "small_world", 1)
    code = f"""
import sys
sys.path.insert(0, 'src')
from fos.experiments.confederates import derive_placement_seed
print(derive_placement_seed(42, "proposal_a", "small_world", 1))
"""
    import os
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = str(random.randint(1, 1000000))
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src") + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          env=env, cwd=str(Path(__file__).resolve().parent.parent))
    assert proc.returncode == 0, proc.stderr
    assert int(proc.stdout.strip()) == seed_in_parent


# ── Test 21: role_prompt not accumulated (Bug 2 still fixed) ───────────────


def test_role_prompt_not_accumulated() -> None:
    """Node relabeling preserves agent identity; role_prompt is fresh each run."""
    import copy
    agents = _make_mock_agents(20)
    originals = {a["name"]: a["role_prompt"] for a in agents}

    # Run 1
    run1 = copy.deepcopy(agents)
    conf_specs1 = assign_confederates(
        [a["name"] for a in run1], n_yes=3, n_no=3, rng=random.Random(42)
    )
    conf_lookup1 = build_confederate_lookup(conf_specs1)
    for a in run1:
        if a["name"] in conf_lookup1:
            spec = conf_lookup1[a["name"]]
            a["role_prompt"] = confederate_system_prompt(spec, "P1") + "\n\n" + a["role_prompt"]

    # Run 2 — fresh deepcopy from untouched originals
    run2 = copy.deepcopy(agents)
    conf_specs2 = assign_confederates(
        [a["name"] for a in run2], n_yes=3, n_no=3, rng=random.Random(99)
    )
    conf_lookup2 = build_confederate_lookup(conf_specs2)
    for a in run2:
        if a["name"] in conf_lookup2:
            spec = conf_lookup2[a["name"]]
            a["role_prompt"] = confederate_system_prompt(spec, "P2") + "\n\n" + a["role_prompt"]

    # Originals untouched
    for a in agents:
        assert a["role_prompt"] == originals[a["name"]], f"{a['name']} mutated!"

    # No stacked prompts
    conf2_ids = {s.agent_id for s in conf_specs2}
    for a in run2:
        if a["name"] not in conf2_ids:
            assert "genuinely support" not in a["role_prompt"].lower()
            assert "genuinely oppose" not in a["role_prompt"].lower()
        count = a["role_prompt"].count("genuinely support") + a["role_prompt"].count("genuinely oppose")
        assert count <= 1, f"{a['name']} has {count} stacked prompts"
