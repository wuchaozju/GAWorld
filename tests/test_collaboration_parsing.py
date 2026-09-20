"""Tolerant JSON extraction for model replies.

Models rarely answer with a bare JSON document: they fence it, prefix it
with a sentence, or both. A strict ``json.loads`` turns every such reply
into ``{}``, and the callers' defaults then contradict what the model
actually said — a fenced ``{"approved": true}`` becomes a rejection.
"""

from __future__ import annotations

import json

from gaworld.collaboration._parsing import extract_json


def test_bare_json_object_is_parsed():
    assert extract_json('{"approved": true}') == {"approved": True}


def test_fenced_json_is_parsed():
    raw = '```json\n{\n  "approved": true,\n  "feedback": "内容完整。"\n}\n```'
    assert extract_json(raw) == {"approved": True, "feedback": "内容完整。"}


def test_unlabelled_fence_is_parsed():
    assert extract_json('```\n{"converged": true}\n```') == {"converged": True}


def test_prose_around_json_is_ignored():
    raw = '我的审阅结论如下：\n{"approved": false, "feedback": "需要补数据"}\n请参考。'
    assert extract_json(raw) == {"approved": False, "feedback": "需要补数据"}


def test_braces_inside_strings_do_not_break_scanning():
    raw = '前言\n{"feedback": "把 {占位符} 替换掉", "approved": true}\n结束'
    assert extract_json(raw) == {
        "feedback": "把 {占位符} 替换掉",
        "approved": True,
    }


def test_nested_object_is_returned_whole():
    payload = {"roles": {"1": "研究员"}, "leader_id": 1}
    raw = "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
    assert extract_json(raw) == payload


def test_non_object_and_empty_inputs_yield_empty_dict():
    assert extract_json("") == {}
    assert extract_json(None) == {}
    assert extract_json("完全没有 JSON 的一段话") == {}
    assert extract_json("[1, 2, 3]") == {}
    assert extract_json('"just a string"') == {}
