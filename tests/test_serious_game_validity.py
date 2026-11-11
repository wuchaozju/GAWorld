"""Executable contracts for role fit, negotiation outcomes and information boundaries."""

import copy
import json
from unittest.mock import patch

import pytest

from gaworld.research import serious_game as sg


def design():
    return {
        "schema_version": 2,
        "game_type": "negotiation",
        "title": "住房协商",
        "roles": [
            {
                "id": "owner",
                "name": "业主",
                "public": "业主代表",
                "private": "底价十万元",
                "eligibility": [{"field": "owns_home", "op": "eq", "value": True}],
                "private_state": {"cash": {"value": 100, "unit": "万元", "source": "研究者设定"}},
            },
            {"id": "tenant", "name": "住户", "public": "未来住户", "private": "不愿超过十二万元"},
        ],
        "indicators": [
            {
                "id": "integration",
                "name": "社区融合度",
                "initial": 50,
                "concept_id": "community_integration",
                "definition_version": "1",
                "description": "参与公共活动的比例",
                "unit": "%",
                "method": "registered_rules",
            }
        ],
        "rounds": [{"title": "议题讨论", "prompt": "提出条件"} for _ in range(3)],
        "negotiation": {"required_roles": ["owner", "tenant"]},
    }


def game_session(spec=None, **kwargs):
    game = {"id": "game", "spec": sg.normalize_spec(spec or design())}
    return sg.new_session(
        game, [{"role_id": "owner", "kind": "human"}, {"role_id": "tenant", "kind": "human"}], **kwargs
    )


def move(session, role, intent="maintain", **details):
    sg.record_action(session, role, "这是我的条件。", decision={"intent": intent, **details})


def close(session):
    return sg.apply_resolution(
        session, json.dumps({"narration": "主持人说已签约", "indicator_changes": {"integration": 9}})
    )


def test_v2_schema_preserves_role_requirements_and_legacy_remains_v1():
    spec = sg.normalize_spec(design())
    assert spec.get("schema_version") == 2
    assert spec["roles"][0]["eligibility"][0]["field"] == "owns_home"
    old = design()
    old.pop("schema_version")
    assert sg.normalize_spec(old)["schema_version"] == 1


def test_casting_handles_unknowns_age_and_global_feasibility():
    from gaworld.research.game_casting import match_roles

    roles = [
        {"id": "any", "name": "代表", "eligibility": []},
        {"id": "owner", "name": "业主", "eligibility": [{"field": "owns_home", "op": "eq", "value": True}]},
    ]
    people = [{"id": 1, "name": "甲", "age": 71, "owns_home": True}, {"id": 2, "name": "乙", "age": 58}]
    first = match_roles(roles, people, seed=3)
    assert first == match_roles(roles, people, seed=3)
    assert {s["role_id"]: s["agent_id"] for s in first} == {"any": 2, "owner": 1}
    with pytest.raises(ValueError, match=r"资格|候选"):
        match_roles(roles, people[1:], seed=3)
    with pytest.raises(ValueError, match="重复"):
        match_roles(roles, people, selected={"any": 1, "owner": 1})


def test_manual_casting_cannot_bypass_requirements():
    from gaworld.research.game_casting import match_roles

    with pytest.raises(ValueError, match=r"资格|候选"):
        match_roles(design()["roles"], [{"id": 1}, {"id": 2}], selected={"owner": 1})


def test_host_narration_cannot_create_agreement_and_limit_is_unresolved():
    s = game_session()
    for _ in range(3):
        move(s, "owner")
        move(s, "tenant")
        close(s)
    assert s["outcome"]["kind"] == "unresolved"
    assert s["status"] == "debriefing"


def test_same_proposal_version_requires_explicit_acceptance():
    s = game_session()
    move(s, "owner", "propose", proposal_id="p1", terms="租金每月1000元", issue="rent")
    move(s, "tenant")
    close(s)
    assert s["proposals"]["p1"]["version"] == 1
    move(s, "owner", "accept", proposal_id="p1", proposal_version=1)
    move(s, "tenant", "accept", proposal_id="p1", proposal_version=1)
    close(s)
    assert s["outcome"]["kind"] == "agreement"
    assert s["status"] == "debriefing"


def test_revised_proposal_invalidates_old_acceptance_even_within_same_round():
    s = game_session()
    move(s, "owner", "propose", proposal_id="p1", terms="1000", issue="rent")
    move(s, "tenant")
    close(s)
    move(s, "owner", "propose", proposal_id="p1", terms="2000", issue="rent")
    move(s, "tenant", "accept", proposal_id="p1", proposal_version=1)
    close(s)
    assert s["proposals"]["p1"]["version"] == 2
    assert not s["proposals"]["p1"]["accepted_by"]
    assert s["outcome"]["kind"] == "ongoing"


def test_defer_needs_required_roles_and_pauses_without_claiming_agreement():
    s = game_session()
    move(s, "owner", "defer")
    move(s, "tenant", "defer")
    close(s)
    assert s["status"] == "paused"
    assert s["outcome"]["kind"] == "deferred"


def test_private_state_and_thoughts_are_not_exposed_to_other_seat():
    s = game_session()
    own = sg.public_view(s, seat_token=s["seats"][0]["token"])
    other = sg.public_view(s, seat_token=s["seats"][1]["token"])
    assert own["roles"][0]["private_state"]["cash"]["value"] == 100
    assert "private_state" not in other["roles"][0]
    assert "底价十万元" not in json.dumps(other, ensure_ascii=False)


def test_registered_indicator_rule_cannot_be_overridden_by_model():
    spec = design()
    spec["rules"] = [
        {
            "id": "r1",
            "intent": "maintain",
            "actor": "owner",
            "target": "indicator:integration",
            "delta": -2,
            "source": "研究者设定",
        }
    ]
    s = game_session(spec)
    move(s, "owner")
    move(s, "tenant")
    record = close(s)
    assert s["indicators"]["integration"] == 48
    assert record["rule_audit"][0]["rule_id"] == "r1"


def test_indicator_definition_comparison_does_not_merge_near_synonyms():
    from gaworld.research.game_rules import comparable

    left = sg.normalize_spec(design())["indicators"][0]
    right = copy.deepcopy(left)
    assert comparable(left, right)
    right["description"] = "群体间信任感"
    assert not comparable(left, right)


def test_invalid_duplicate_indicator_or_nonfinite_state_is_rejected():
    d = design()
    d["indicators"] *= 2
    with pytest.raises(ValueError):
        sg.normalize_spec(d)
    d = design()
    d["roles"][0]["private_state"]["cash"]["value"] = float("nan")
    with pytest.raises(ValueError):
        sg.normalize_spec(d)


def test_interventions_wait_for_boundary_and_apply_exactly_once():
    from gaworld.research import game_interventions as gi

    s = game_session(step_mode=True)
    move(s, "owner")
    event = {
        "id": "event-1",
        "text": "监管部门发布新消息",
        "visibility": "public",
        "indicator_changes": {"integration": 3},
    }
    gi.enqueue(s, event)
    assert s["indicators"]["integration"] == 50
    move(s, "tenant")
    close(s)
    assert s["status"] == "paused"
    before = s["indicators"]["integration"]
    gi.resume(s)
    assert s["indicators"]["integration"] == before + 3
    gi.enqueue(s, event)
    assert len(s["interventions"]) == 1
    assert s["indicators"]["integration"] == before + 3


def test_private_intervention_is_not_exposed_through_history_or_prompt():
    from gaworld.research import game_interventions as gi

    s = game_session(step_mode=True)
    s["status"] = "paused"
    gi.enqueue(s, {"id": "secret-event", "text": "银行私下催款", "visibility": "owner"})
    gi.resume(s)
    outsider = sg.public_view(s, seat_token=s["seats"][1]["token"])
    assert "银行私下催款" not in json.dumps(outsider, ensure_ascii=False)
    assert "银行私下催款" not in sg.agent_prompt(s, s["seats"][1])
    assert "银行私下催款" in sg.agent_prompt(s, s["seats"][0])


def test_full_run_respects_snapshot_and_human_cannot_invent_secret_disclosure():
    s = game_session()
    with pytest.raises(ValueError):
        move(s, "owner", disclose_fact_ids=["imaginary"])
    assert "owner" not in s["actions"]


def test_restricted_fact_cannot_be_selected_for_disclosure():
    d = design()
    d["roles"][0]["private_facts"] = [{"id": "secret", "text": "账户口令", "disclosable": False}]
    s = game_session(d)
    with pytest.raises(ValueError):
        move(s, "owner", disclose_fact_ids=["secret"])


@pytest.fixture
def hosted(tmp_path):
    from gaworld.apps import serious_game_api as api

    with patch.object(sg, "games_root", return_value=tmp_path), patch.object(api, "_kick"):
        api.reset()
        g = {"id": "testgame", "spec": sg.normalize_spec(design())}
        sg.save_game(g)
        data = api.create_session(
            {
                "game_id": "testgame",
                "seats": [{"role_id": "owner", "kind": "human"}, {"role_id": "tenant", "kind": "human"}],
                "step_mode": True,
            }
        )
        yield api, data["id"]
        api.reset()


def test_api_pause_resume_and_structured_human_action(hosted):
    api, sid = hosted
    view = api.control(sid, "pause", {})
    assert view["status"] == "paused"
    api.control(sid, "resume", {})
    s = api._get(sid)
    api.act(sid, {"seat": s["seats"][0]["token"], "action": "延期", "decision": {"intent": "defer"}})
    assert s["actions"]["owner"]["decision"]["intent"] == "defer"
    api.control(sid, "pause", {})
    assert s["status"] == "acting" and s["pause_requested"]


def test_non_owner_cannot_intervene_even_with_a_valid_seat(hosted):
    from gaworld.accounts.context import USER

    api, sid = hosted
    s = api._get(sid)
    s["owner_id"] = 1
    token = USER.set({"id": 2, "role": "member"})
    try:
        assert api.view(sid, seat=s["seats"][0]["token"])["me"]["role_id"] == "owner"
        with pytest.raises(KeyError):
            api.control(sid, "intervene", {"id": "x", "text": "偷偷改变规则"})
    finally:
        USER.reset(token)


def test_external_human_role_enters_at_boundary_without_secret_history(hosted):
    api, sid = hosted
    api.control(sid, "pause", {})
    view = api.control(
        sid,
        "intervene",
        {
            "id": "regulator-1",
            "text": "监管者入场",
            "role": {"id": "regulator", "name": "监管者", "public": "负责监督", "private": "内部期限"},
            "seat": {"kind": "human", "player_name": "监管人员"},
        },
    )
    assert len(view["seats"]) == 3
    assert view["negotiation"]["required_roles"] == ["owner", "tenant"]
    s = api._get(sid)
    outsider = sg.public_view(s, seat_token=s["seats"][-1]["token"])
    assert "底价十万元" not in json.dumps(outsider, ensure_ascii=False)
    assert "token" not in outsider["interventions"][0]


def test_revision_and_suspension_preserve_old_session_spec(hosted):
    api, sid = hosted
    original = copy.deepcopy(api._get(sid)["spec"])
    changed = design()
    changed["title"] = "另一场游戏"
    api.update_game("testgame", {"spec": changed})
    assert api._get(sid)["spec"] == original


def test_payoff_transfer_is_conserved_and_private_audit_is_hidden():
    d = design()
    d["roles"][1]["private_state"] = {"cash": {"value": 5, "unit": "万元", "source": "研究者设定"}}
    d["rules"] = [
        {
            "id": "pay",
            "actor": "owner",
            "intent": "maintain",
            "op": "transfer",
            "from": "private:owner:cash",
            "target": "private:tenant:cash",
            "delta": 10,
            "source": "研究者设定",
        }
    ]
    s = game_session(d)
    move(s, "owner")
    move(s, "tenant")
    close(s)
    assert s["private_state"]["owner"]["cash"]["value"] == 90
    assert s["private_state"]["tenant"]["cash"]["value"] == 15
    v = sg.public_view(s, seat_token=s["seats"][1]["token"])
    assert not v["rounds"][0]["rule_audit"]


def test_export_carries_frozen_definitions_and_registered_outcome():
    s = game_session()
    text = sg.export_markdown(s)
    assert "community_integration" in text
    assert s["input_hash"] in text
    assert "私人收益与风险" in text


def test_world_storage_resolves_active_world_path():
    from gaworld.apps import world_paths

    with (
        patch.object(world_paths, "current_world", return_value={"id": "world-test"}),
        patch.object(world_paths, "world_file", return_value="/tmp/world-test/research/serious_games"),
    ):
        assert str(sg.games_root()) == "/tmp/world-test/research/serious_games"


def test_repeated_action_is_diagnosed_without_forcing_change_of_position():
    s = game_session()
    move(s, "owner")
    move(s, "tenant")
    close(s)
    move(s, "owner")
    assert s["actions"]["owner"]["repeated_action"]
    assert s["actions"]["owner"]["decision"]["intent"] == "maintain"


def test_deferred_at_round_limit_can_request_explicit_extra_budget():
    from gaworld.research.game_interventions import resume

    d = design()
    d["rounds"] = d["rounds"][:1]
    s = game_session(d)
    move(s, "owner", "defer")
    move(s, "tenant", "defer")
    close(s)
    assert s["status"] == "paused"
    with pytest.raises(ValueError):
        resume(s)
    resume(s, extra_rounds=1)
    assert s["status"] == "acting"


def test_preview_refuses_stale_configuration_before_starting(hosted):
    api, _ = hosted
    payload = {
        "game_id": "testgame",
        "seats": [{"role_id": "owner", "kind": "human"}, {"role_id": "tenant", "kind": "human"}],
    }
    preview = api.serious_game_controls.preview(api._game("testgame"), payload)
    payload.update(preview_hash=preview["preview_hash"], seed=8)
    with pytest.raises(ValueError, match="预览"):
        api.create_session(payload)


def test_active_world_cannot_read_cached_session_from_another_world(hosted):
    from gaworld.apps import world_paths

    api, sid = hosted
    with patch.object(world_paths, "current_world", return_value={"id": "another-world"}):
        with pytest.raises(KeyError):
            api.view(sid, host=True)


def test_legacy_spec_keeps_fixed_round_lifecycle():
    d = design()
    d.pop("schema_version")
    s = game_session(d)
    for _ in range(3):
        move(s, "owner")
        move(s, "tenant")
        close(s)
    assert "outcome" not in s and s["status"] == "debriefing"


def test_initial_snapshot_survives_budget_amendment():
    import hashlib

    from gaworld.research.game_interventions import resume

    s = game_session(step_mode=True)
    original = s.get("frozen_input")
    assert original is not None
    s["status"] = "paused"
    resume(s, extra_rounds=1)
    assert len(original["spec"]["rounds"]) == 3
    assert (
        hashlib.sha256(json.dumps(original, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        == s["input_hash"]
    )


def test_read_restarts_an_interrupted_acting_driver(hosted):
    api, sid = hosted
    s = api._get(sid)
    s["seats"][0].update(kind="agent", persona={"agent_id": 5, "name": "测试居民"})
    sg.save_session(s)
    api._SESSIONS.clear()
    with patch.object(api, "_kick") as restart:
        api.view(sid, host=True)
    restart.assert_called_once_with(sid)


def test_simultaneous_new_proposal_id_collision_never_overwrites_either_party():
    s = game_session()
    move(s, "owner", "propose", proposal_id="p1", terms="1000", issue="rent")
    move(s, "tenant", "propose", proposal_id="p1", terms="2000", issue="rent")
    record = close(s)
    assert "p1" not in s["proposals"]
    assert len(record["decision_errors"]) == 2
    assert s["outcome"]["kind"] == "ongoing"
