"""Tests for 谁是真人 (gaworld.apps.whois_api) and its Track D read-out.

What we defend:

* a room seats residents and people at drawn numbers within the limits, and
  refuses impossible tables;
* rounds are simultaneous: a round appears whole, in number order, once
  every seat has written; the host may close it without absent people but
  not while residents are still writing;
* players never see who is who, who has written or voted, or how many
  people are present — until the reveal; the host sees everything;
* a ballot covers every other number with human/resident, once;
* the reveal counts who was judged what and how well each person guessed,
  is archived, and GAWorld-Bench Track D reads the archive;
* residents are not told about the guessing;
* a seat link opens its seat; without one only the host may look.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from gaworld.accounts.context import USER
from gaworld.apps import game_archive, whois_api

_PEOPLE = [
    {"agent_id": i, "name": f"居民{i}", "age": 30 + i, "gender": "女", "job": "店员", "profile_md": ""}
    for i in range(1, 9)
]


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    whois_api.reset()
    prompts: list[str] = []

    def persona(city, agent_id, taken):
        pool = [p for p in _PEOPLE if p["agent_id"] not in taken]
        return next(p for p in pool if agent_id in (None, p["agent_id"]))

    def llm(prompt):
        prompts.append(prompt)
        return json.dumps({"message": "周末在家躺着，哪也没去"}, ensure_ascii=False)

    monkeypatch.setattr(whois_api, "_PERSONA_OVERRIDE", persona)
    monkeypatch.setattr(whois_api, "_LLM_OVERRIDE", llm)
    yield prompts
    whois_api.reset()


def _wait(room_id, test, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        room = whois_api._ROOMS[room_id]
        with whois_api._LOCK:
            if test(room):
                return room
        time.sleep(0.01)
    raise AssertionError("room never got there")


def _open(**payload):
    view = whois_api.create_room({"agents": 2, "humans": 2, "rounds": 2, **payload})
    room = _wait(view["id"], lambda r: not whois_api.pending(r, "agent") or r["status"] != "chatting")
    tokens = [s["token"] for s in room["seats"] if s["kind"] == "human"]
    return room, tokens


def _play_through(room, tokens):
    for _ in range(room["rounds_total"]):
        for token in tokens:
            whois_api.say(room["id"], {"seat": token, "text": "我周末去西湖边走了走"})
        _wait(room["id"], lambda r: r["status"] != "chatting" or not whois_api.pending(r, "agent"))


def _ballot(room, token, *, all_say=None):
    me = whois_api.seat_by_token(room, token)["alias"]
    kinds = {s["alias"]: s["kind"] for s in room["seats"]}
    return {
        alias: (all_say or ("human" if kind == "human" else "resident"))
        for alias, kind in kinds.items()
        if alias != me
    }


def test_a_room_is_seated_at_drawn_numbers_within_the_limits():
    room = whois_api.new_room({"agents": 3, "humans": 2, "agent_ids": [4], "topic_id": "food"})
    aliases = [s["alias"] for s in room["seats"]]
    assert aliases == [f"{i}号" for i in range(1, 6)]
    assert sorted(s["kind"] for s in room["seats"]) == ["agent"] * 3 + ["human"] * 2
    assert 4 in {s["persona"]["agent_id"] for s in room["seats"] if s["kind"] == "agent"}
    assert all(s.get("token") for s in room["seats"] if s["kind"] == "human")
    assert room["topic"]["id"] == "food" and room["status"] == "chatting"
    custom = whois_api.new_room({"agents": 1, "humans": 2, "custom": {"text": "你怎么看早高峰"}})
    assert custom["topic"]["text"] == "你怎么看早高峰"
    for bad in (
        {"agents": 0},
        {"agents": 5, "humans": 5},
        {"agents": 1, "humans": 1},
        {"rounds": 9},
        {"topic_id": "nope"},
        {"agents": 1, "agent_ids": [1, 2]},
        {"custom": {"text": " "}},
    ):
        with pytest.raises(ValueError):
            whois_api.new_room({"agents": 2, "humans": 2, **bad})


def test_residents_are_not_told_about_the_guessing(_stubs):
    room, _tokens = _open()
    assert _stubs and all("真人" not in p and "猜" not in p for p in _stubs)
    seat = next(s for s in room["seats"] if s["kind"] == "agent")
    prompt = whois_api.agent_prompt(room, seat)
    assert seat["alias"] in prompt and room["topic"]["text"] in prompt


def test_a_round_appears_whole_and_in_number_order():
    room, tokens = _open()
    assert room["transcript"] == []
    whois_api.say(room["id"], {"seat": tokens[0], "text": "  我  在家  "})
    with pytest.raises(ValueError, match="说过了"):
        whois_api.say(room["id"], {"seat": tokens[0], "text": "再说一句"})
    assert room["transcript"] == []
    whois_api.say(room["id"], {"seat": tokens[1], "text": "我加班"})
    first = room["transcript"][0]
    assert [m["alias"] for m in first["messages"]] == [s["alias"] for s in room["seats"]]
    assert "我 在家" in [m["text"] for m in first["messages"]]
    assert room["round"] == 1 and room["status"] == "chatting"


def test_the_host_closes_a_round_without_absent_people_but_not_without_residents(monkeypatch):
    room, tokens = _open()
    whois_api.say(room["id"], {"seat": tokens[0], "text": "我来了"})
    whois_api.next_round(room["id"])
    assert whois_api.SILENT in [m["text"] for m in room["transcript"][0]["messages"]]
    with whois_api._LOCK:  # pretend a resident is still writing round two
        room["open"].clear()
    with pytest.raises(ValueError, match="居民还在打字"):
        whois_api.next_round(room["id"])


def test_players_see_nothing_about_who_is_who_until_the_reveal():
    room, tokens = _open()
    view = whois_api.view(room["id"], token=tokens[0])
    assert all(set(card) == {"alias"} for card in view["seats"])
    assert "results" not in view and "votes" not in view
    assert view["me"]["alias"] == whois_api.seat_by_token(room, tokens[0])["alias"]
    host = whois_api.view(room["id"], host=True)
    assert {card["kind"] for card in host["seats"]} == {"agent", "human"}
    assert sum(1 for card in host["seats"] if card.get("token")) == 2


def test_a_ballot_covers_every_other_number_once():
    room, tokens = _open()
    with pytest.raises(ValueError, match="还没到"):
        whois_api.vote(room["id"], {"seat": tokens[0], "verdicts": {}})
    _play_through(room, tokens)
    assert room["status"] == "guessing"
    partial = dict(list(_ballot(room, tokens[0]).items())[:1])
    with pytest.raises(ValueError, match="还没选"):
        whois_api.vote(room["id"], {"seat": tokens[0], "verdicts": partial})
    whois_api.vote(room["id"], {"seat": tokens[0], "verdicts": _ballot(room, tokens[0])})
    with pytest.raises(ValueError, match="猜过了"):
        whois_api.vote(room["id"], {"seat": tokens[0], "verdicts": _ballot(room, tokens[0])})
    assert whois_api.view(room["id"], token=tokens[1])["status"] == "guessing"


def test_the_reveal_counts_judgments_and_is_archived_for_track_d():
    room, tokens = _open()
    _play_through(room, tokens)
    whois_api.vote(room["id"], {"seat": tokens[0], "verdicts": _ballot(room, tokens[0])})
    whois_api.vote(room["id"], {"seat": tokens[1], "verdicts": _ballot(room, tokens[1], all_say="human")})
    assert room["status"] == "revealed"
    res = room["results"]
    # Two judges, each judging two residents and one person.
    assert (res["resident_judgments"], res["human_judgments"]) == (4, 2)
    assert (res["resident_judged_human"], res["human_judged_human"]) == (2, 2)
    assert sorted(j["correct"] for j in res["judges"]) == [1, 3]
    assert res["accuracy"] == pytest.approx(4 / 6, abs=1e-4)
    view = whois_api.view(room["id"], token=tokens[0])
    assert {card["kind"] for card in view["seats"]} == {"agent", "human"}

    files = list((Path(game_archive.ARCHIVE_DIR) / "whois").glob("*.json"))
    assert len(files) == 1
    saved = json.loads(files[0].read_text(encoding="utf-8"))
    assert "token" not in json.dumps(saved)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmark"))
    import gaworld_bench as gb

    track = gb.track_d_whois(Path(game_archive.ARCHIVE_DIR))
    assert (track["rooms"], track["resident_judgments"], track["human_judgments"]) == (1, 4, 2)
    assert track["status"] == "n/a"  # one room is not enough


def test_the_host_reveals_with_the_ballots_that_are_in():
    room, tokens = _open()
    _play_through(room, tokens)
    with pytest.raises(ValueError, match="还没有人猜"):
        whois_api.reveal(room["id"])
    whois_api.vote(room["id"], {"seat": tokens[0], "verdicts": _ballot(room, tokens[0])})
    whois_api.reveal(room["id"])
    assert room["status"] == "revealed" and len(room["results"]["judges"]) == 1


def test_a_seat_link_opens_its_seat_and_nothing_else():
    token = USER.set({"id": 1, "nickname": "老师", "role": "member"})
    try:
        room, tokens = _open()
    finally:
        USER.reset(token)
    other = USER.set({"id": 2, "nickname": "学生", "role": "member"})
    try:
        assert whois_api.view(room["id"], token=tokens[0])["me"]
        with pytest.raises(KeyError):
            whois_api.view(room["id"])
        with pytest.raises(KeyError):
            whois_api.next_round(room["id"])
        with pytest.raises(ValueError, match="无效"):
            whois_api.say(room["id"], {"seat": "forged", "text": "hi"})
        assert whois_api.list_rooms() == []
    finally:
        USER.reset(other)


def test_messages_are_read_from_json_or_prose_and_capped():
    assert whois_api.parse_message('{"message": "  行  吧 "}') == "行 吧"
    assert whois_api.parse_message("就在家呆着") == "就在家呆着"
    assert len(whois_api.parse_message("长" * 500)) == whois_api.MAX_MESSAGE_CHARS


def test_http_routes():
    body, status = whois_api.handle_get("/api/games/whois/catalogue")
    assert status == 200 and len(body["topics"]) == len(whois_api.TOPICS)
    body, status = whois_api.handle_post("/api/games/whois/rooms", {"agents": 1, "humans": 2, "rounds": 2})
    assert status == 200 and body["host"]
    assert whois_api.handle_get(f"/api/games/whois/rooms/{body['id']}")[1] == 200
    assert whois_api.handle_get("/api/games/whois/rooms/nope")[1] == 404
    assert (
        whois_api.handle_post(f"/api/games/whois/rooms/{body['id']}/say", {"seat": "x", "text": "a"})[1]
        == 400
    )
    assert whois_api.handle_post("/api/games/whois/nope", {})[1] == 404
