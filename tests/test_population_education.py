"""Education and enrollment must survive synthesis, storage and recruitment."""

import csv
import io

import pytest

from gaworld.population.schema import normalize_spec
from gaworld.population.synth import synthesize_people
from gaworld.population.writer import render_state_csv
from gaworld.research import replication as rp


def test_college_town_contains_adult_students_with_completed_qualifications():
    spec = normalize_spec({"preset": "college_town", "size": 500, "seed": 42})
    people, _ = synthesize_people(spec)
    students = [p for p in people if p.age >= 18 and "学生" in p.job]
    assert students, "college_town currently generates no adult students"
    assert any(p.student_status in ("大专", "本科") for p in students)
    assert any(p.student_status in ("硕士", "博士") for p in students)
    assert all(p.employment == "not_in_labor_force" for p in students)
    assert all(p.education != p.student_status for p in students)
    assert render_state_csv(people) == render_state_csv(synthesize_people(spec)[0])


def test_education_and_enrollment_are_structured_csv_columns():
    people, _ = synthesize_people(normalize_spec({"size": 50}))
    rows = list(csv.DictReader(io.StringIO(render_state_csv(people))))
    assert "education" in rows[0]
    assert "student_status" in rows[0]


def test_recruitment_requires_enrollment_instead_of_similar_age_or_degree():
    people = [
        {
            "id": 1,
            "age": 21,
            "education": "高中/中专",
            "student_status": "本科",
            "gender": "女",
            "job": "本科学生",
        },
        {
            "id": 2,
            "age": 21,
            "education": "本科",
            "student_status": "非在读",
            "gender": "女",
            "job": "工程师",
        },
        {"id": 3, "age": 21, "gender": "女", "job": "未知"},
        {
            "id": 4,
            "age": 21,
            "education": "高中/中专",
            "student_status": "本科",
            "gender": "男",
            "job": "本科学生",
        },
    ]
    spec = rp.normalize_spec({"age_min": 18, "age_max": 25, "student_status": "本科", "gender": "女"})
    assert [p["id"] for p in rp.eligible_residents(people, spec)] == [1]


def test_completed_degree_and_job_filters_intersect():
    people = [
        {"id": 1, "age": 24, "education": "本科", "student_status": "硕士", "job": "硕士研究生"},
        {"id": 2, "age": 24, "education": "高中/中专", "student_status": "本科", "job": "本科学生"},
    ]
    spec = rp.normalize_spec({"education": "本科", "job": "研究生"})
    assert [p["id"] for p in rp.eligible_residents(people, spec)] == [1]


def test_education_group_is_not_silently_dropped():
    spec = rp.normalize_spec({"groups": [{"id": "G1", "label": "本科在读", "student_status": "本科"}]})
    assert len(spec["groups"]) == 1
    assert rp.in_group({"age": 20, "student_status": "本科"}, spec["groups"][0])
    assert not rp.in_group({"age": 20}, spec["groups"][0])


@pytest.fixture
def world_files(tmp_path, monkeypatch):
    from gaworld.apps import world_paths
    from gaworld.interview import roster

    csv_path, md_path = tmp_path / "agents.csv", tmp_path / "profiles.md"
    csv_path.write_text(
        "id,name,gender,age,hukou,residence,custom\n1,原居民,女,24,本地,公寓,keep\n", encoding="utf-8-sig"
    )
    md_path.write_text(
        "## Profile 01｜原居民\n**教育与收入背景**：本科学历，月收入约 5000 元。\n\n**职业与工作节奏**：工程师\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(world_paths, "state_csv_path", lambda: str(csv_path))
    monkeypatch.setattr(world_paths, "profile_path", lambda: str(md_path))
    monkeypatch.setattr(roster, "city_paths", lambda slug: (csv_path, md_path))
    return csv_path, md_path


def test_legacy_degree_does_not_imply_enrollment(world_files):
    from gaworld.interview.roster import load_population

    person = load_population("")[0]
    assert person["education"] == "本科"
    assert person["student_status"] == "未知"


def test_explicit_legacy_university_student_does_not_imply_graduated(world_files):
    from gaworld.interview.roster import load_population

    world_files[1].write_text(
        "## Profile 01｜原居民\n**教育与收入背景**：本科在读，家庭支持。\n**职业与工作节奏**：大学生\n"
    )
    person = load_population("")[0]
    assert person["education"] == "未知"
    assert person["student_status"] == "本科"


def test_studio_edit_and_create_round_trip_education_and_job(world_files):
    from gaworld.apps import residents
    from gaworld.interview.roster import load_population

    residents.save_agent_state(
        1, {"education": "本科", "student_status": "硕士", "job": "硕士研究生（学生）"}
    )
    again = residents.agent_state(1)
    assert again["student_status"] == "硕士"
    assert again["education"] == "本科"
    assert again["job"] == "硕士研究生（学生）"
    assert "当前在读阶段：硕士" in world_files[1].read_text()
    created = residents.create_agent(
        {"name": "新大学生", "age": 20, "education": "高中/中专", "student_status": "本科", "job": "本科学生"}
    )
    assert created["id"] == 2
    assert load_population("")[1]["student_status"] == "本科"
    with world_files[0].open(encoding="utf-8-sig") as handle:
        assert next(csv.DictReader(handle))["custom"] == "keep"


def test_invalid_education_edit_does_not_write(world_files):
    from gaworld.apps import residents

    before = [p.read_bytes() for p in world_files]
    with pytest.raises(ValueError):
        residents.save_agent_state(1, {"age": 12, "education": "本科", "student_status": "本科"})
    assert [p.read_bytes() for p in world_files] == before


def test_student_preview_and_append_preserve_existing_population(world_files):
    from gaworld.apps import student_samples_api as api
    from gaworld.interview.roster import load_population

    before = [p.read_bytes() for p in world_files]
    payload = {"count": 8, "student_status": "本科", "seed": 7}
    preview = api.preview(payload)
    assert len(preview["people"]) == 8
    assert [p.read_bytes() for p in world_files] == before
    assert api.preview(payload) == preview
    result = api.append({**payload, "preview_token": preview["preview_token"]})
    assert result["count"] == 8
    people = load_population("")
    assert len(people) == 9
    assert people[0]["name"] == "原居民"
    assert all(p["student_status"] == "本科" for p in people[1:])
    assert len({p["id"] for p in people}) == 9
    with pytest.raises(ValueError, match="预览"):
        api.append({**payload, "preview_token": preview["preview_token"]})


def test_active_world_students_are_recruited_without_reading_city_bundle(tmp_path, monkeypatch):
    from gaworld.apps import games_api, world_paths
    from gaworld.interview import roster

    world_csv, world_md = tmp_path / "world.csv", tmp_path / "world.md"
    world_csv.write_text(
        "id,name,age,gender,education,student_status\n2,世界学生,20,女,高中/中专,本科\n", encoding="utf-8-sig"
    )
    world_md.write_text("## Profile 02｜世界学生\n**职业与工作节奏**：本科学生\n")
    monkeypatch.setattr(world_paths, "current_world", lambda: {"id": "world-a"})
    monkeypatch.setattr(world_paths, "effective_config", lambda: {"city": "source-city"})
    monkeypatch.setattr(world_paths, "state_csv_path", lambda: str(world_csv))
    monkeypatch.setattr(world_paths, "profile_path", lambda: str(world_md))
    # Source bundle is deliberately unavailable; recruitment must use the world copy.
    monkeypatch.setattr(
        roster, "city_paths", lambda slug: (_ for _ in ()).throw(AssertionError("bundle read"))
    )
    for city in ("", "source-city"):
        assert [p["name"] for p in games_api.list_agents(city)] == ["世界学生"]


def test_unreachable_student_target_reports_capacity():
    spec = normalize_spec(
        {
            "size": 100,
            "education_work": {"adult_student_rate": 1, "employment_rate": 1, "unemployment_rate": 0},
        }
    )
    _, report = synthesize_people(spec)
    assert report["adult_students"]["requested"] > 0
    assert report["adult_students"]["actual"] == report["adult_students"]["available"] == 0


def test_append_failure_rolls_back_both_files(world_files, monkeypatch):
    from gaworld.apps import residents
    from gaworld.apps import student_samples_api as api

    original = [p.read_bytes() for p in world_files]
    payload = {"count": 3, "seed": 8, "student_status": "硕士"}
    payload["preview_token"] = api.preview(payload)["preview_token"]
    create = residents.create_agent
    calls = []

    def fail_after_first(person):
        calls.append(person)
        if len(calls) > 1:
            raise ValueError("write failed")
        return create(person)

    monkeypatch.setattr(residents, "create_agent", fail_after_first)
    with pytest.raises(ValueError, match="write failed"):
        api.append(payload)
    assert [p.read_bytes() for p in world_files] == original


@pytest.mark.parametrize(
    "job",
    [
        "大学生辅导员，负责宿舍与就业指导",
        "硕士研究生导师，每周指导学生",
        "已毕业的本科生，目前做自由职业",
        "曾是大学生，现在工作",
    ],
)
def test_legacy_roles_and_graduates_are_not_current_students(job):
    from gaworld.population.education import education_attributes

    assert education_attributes({"job": job})["student_status"] == "未知"


def test_explicit_not_enrolled_survives_readback():
    from gaworld.population.education import education_attributes

    assert education_attributes({"student_status": "非在读"})["student_status"] == "非在读"


def test_age_only_edit_checks_education_constraints(world_files):
    from gaworld.apps import residents

    residents.save_agent_state(1, {"education": "本科", "student_status": "硕士"})
    before = [p.read_bytes() for p in world_files]
    with pytest.raises(ValueError):
        residents.save_agent_state(1, {"age": 12})
    assert [p.read_bytes() for p in world_files] == before


def test_zero_age_with_education_fields_is_rejected(world_files):
    from gaworld.apps import residents

    before = [p.read_bytes() for p in world_files]
    with pytest.raises(ValueError):
        residents.save_agent_state(1, {"age": 0, "education": "本科", "student_status": "硕士"})
    assert [p.read_bytes() for p in world_files] == before


def test_city_add_and_import_preserve_education_fields(tmp_path):
    from gaworld.apps.import_api import _append_clean_rows
    from gaworld.city.agents import add_agent
    from gaworld.city.create import create_city

    city = create_city("教育测试镇", offline=True, scale="tiny", root=tmp_path)
    add_agent(city, name="本科在读甲", age=20, education="高中/中专", student_status="本科", job="本科学生")
    assert (
        _append_clean_rows(
            city,
            [
                {
                    "name": "研究生乙",
                    "age": "24",
                    "education": "本科",
                    "student_status": "硕士",
                    "job": "硕士研究生",
                }
            ],
        )
        == 1
    )
    with city.state_csv_path.open(encoding="utf-8-sig") as handle:
        people = list(csv.DictReader(handle))
    assert [p["student_status"] for p in people] == ["本科", "硕士"]
    assert [p["education"] for p in people] == ["高中/中专", "本科"]


def test_confirmed_profile_edit_updates_structured_picker_fields(world_files):
    from gaworld.apps import residents

    residents.save_agent_state(1, {"education": "本科", "student_status": "非在读", "job": "工程师"})
    profile = residents.agent_profile(1)["text"]
    residents.save_agent_profile(
        1,
        profile.replace("当前在读阶段：非在读", "当前在读阶段：硕士").replace(
            "**职业与工作节奏**：工程师", "**职业与工作节奏**：硕士研究生"
        ),
    )
    again = residents.agent_state(1)
    assert again["student_status"] == "硕士"
    assert again["job"] == "硕士研究生"


def test_locale_change_invalidates_student_preview(world_files):
    from gaworld.apps import student_samples_api as api

    payload = {"count": 2, "seed": 42, "student_status": "本科"}
    first = api.preview(payload)
    (world_files[0].parent / "locale.json").write_text('{"surnames":["测试"]}')
    assert api.preview(payload)["preview_token"] != first["preview_token"]


def test_qualification_validation_accepts_shorter_adult_degree_paths(world_files):
    from gaworld.apps import residents

    # A 21-year-old graduate student is valid; generation's usual age floor
    # must not become a universal education-system rule in the editor.
    residents.save_agent_state(1, {"age": 21, "education": "本科", "student_status": "硕士"})
    assert residents.agent_state(1)["student_status"] == "硕士"


@pytest.mark.parametrize("edited_line", ["canonical", "legacy"])
def test_raw_qualification_edits_leave_no_conflicting_narrative(world_files, edited_line):
    from gaworld.apps import residents

    residents.save_agent_state(1, {"education": "本科", "student_status": "非在读"})
    text = residents.agent_profile(1)["text"]
    old = "最高已获学历：本科" if edited_line == "canonical" else "**教育与收入背景**：本科学历"
    new = "最高已获学历：硕士及以上" if edited_line == "canonical" else "**教育与收入背景**：硕士及以上学历"
    residents.save_agent_profile(1, text.replace(old, new))
    assert residents.agent_state(1)["education"] == "硕士及以上"
    assert "本科学历" not in residents.agent_profile(1)["text"]
