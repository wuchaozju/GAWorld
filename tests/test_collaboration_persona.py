"""Individual traits reaching collaboration prompts.

Collaboration calls used to carry only the task and an assigned role, so
an economics teacher and a courier produced interchangeable text. These
helpers decide which traits travel with each call and which member is
competent to author a given step.
"""

from __future__ import annotations

from gaworld.collaboration._persona import expertise_terms, match_score, persona


def _teacher():
    return {
        "identity": {"id": 3, "name": "林岚"},
        "profile_text": "杭州某中学经济学教师。",
        "capabilities": {
            "job_label": "teacher",
            "skills": ["经济学分析"],
            "interests": ["公共政策"],
            "deliverables": ["教学讲义"],
        },
        "private_skills": [{"file": "a.md", "title": "课堂案例设计"}],
        "growth": {
            "items": [
                {"name": "计量经济学", "level": 0.8},
                {"name": "书法", "level": 0.3},
            ]
        },
    }


def test_persona_merges_private_skills_and_ranks_expertise():
    block = persona(_teacher())
    assert block["job_label"] == "teacher"
    assert block["skills"] == ["经济学分析", "课堂案例设计"]
    assert [item["name"] for item in block["expertise"]] == ["计量经济学", "书法"]
    assert block["expertise"][0]["level"] == 0.8
    assert block["profile_text"].startswith("杭州某中学")


def test_persona_tolerates_missing_sections():
    assert persona(None)["skills"] == []
    assert persona({"identity": {"id": 1}})["expertise"] == []


def test_persona_falls_back_to_whole_detail_when_identity_absent():
    """Runner fixtures and older payloads carry the identity fields inline."""
    assert persona({"id": 4, "name": "王"})["identity"] == {"id": 4, "name": "王"}


def test_expertise_terms_drop_placeholder_job_label():
    detail = {"capabilities": {"job_label": "other", "skills": ["社区走访"]}}
    assert expertise_terms(detail) == ["社区走访"]


def test_match_score_counts_partial_chinese_overlap():
    """"经济学分析" must cover "分析租金结构" — verbatim matching finds nothing."""
    assert match_score("分析租金结构", ["经济学分析"]) == 1
    assert match_score("分析租金结构", ["社区走访"]) == 0


def test_match_score_ignores_untitled_steps():
    assert match_score("", ["经济学分析"]) == 0
