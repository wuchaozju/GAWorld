"""Planning tasks retain their outcome across refreshes and server restarts."""

from gaworld.apps import research_api
from gaworld.research import workbench


def test_finished_job_can_be_recovered_after_memory_eviction(tmp_path, monkeypatch):
    monkeypatch.setattr(workbench, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(research_api, "_JOBS", {})
    job_id = research_api._new_job("plan")
    research_api._update_job(job_id, status="done", result={"plan_id": "saved-plan"}, message="完成")
    research_api._JOBS.clear()
    recovered = research_api.job_status(job_id)
    assert recovered["status"] == "done"
    assert recovered["result"] == {"plan_id": "saved-plan"}


def test_restart_marks_an_unfinished_planning_job_interrupted(tmp_path, monkeypatch):
    monkeypatch.setattr(workbench, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(research_api, "_JOBS", {})
    job_id = research_api._new_job("study")
    research_api._JOBS.clear()
    recovered = research_api.job_status(job_id)
    assert recovered["status"] == "error"
    assert "中断" in recovered["message"]
    assert recovered["result"] is None


def test_persisted_jobs_respect_workspace_visibility(tmp_path, monkeypatch):
    monkeypatch.setattr(workbench, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(research_api, "_JOBS", {})
    job_id = research_api._new_job("digest")
    research_api._JOBS.clear()
    monkeypatch.setattr(research_api.workspaces, "visible", lambda record: False)
    assert research_api.job_status(job_id) is None


def test_single_model_job_does_not_invent_progress_based_eta(tmp_path, monkeypatch):
    monkeypatch.setattr(workbench, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(research_api, "_JOBS", {})
    job_id = research_api._new_job("plan")
    research_api._update_job(job_id, progress=0.1)
    research_api._JOBS[job_id]["_timing"]._started -= 60
    assert research_api.job_status(job_id)["remaining_seconds"] is None


def test_repeated_submission_id_reuses_job_without_another_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(workbench, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(research_api, "_JOBS", {})
    workers = []
    monkeypatch.setattr(research_api, "_run_in_background", lambda job_id, work: workers.append(job_id))
    payload = {"text": "a research question", "request_id": "same-submission-123"}
    first = research_api.start_digest(payload)
    second = research_api.start_digest(payload)
    assert first["job_id"] == second["job_id"]
    assert workers == [first["job_id"]]
    research_api._JOBS.clear()
    assert research_api.start_digest(payload)["job_id"] == first["job_id"]
    assert workers == [first["job_id"]]


def test_digest_task_keeps_source_material_for_refresh_recovery(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(workbench, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(research_api, "_JOBS", {})
    monkeypatch.setattr(
        research_api,
        "_llm",
        lambda *args: (
            lambda prompt: json.dumps(
                {
                    "title": "paper",
                    "paper_digest": {"theory": "mechanism"},
                    "research_questions": ["why?"],
                    "hypotheses": ["H1"],
                }
            )
        ),
    )
    workers = []
    monkeypatch.setattr(research_api, "_run_in_background", lambda jid, work: workers.append(work))
    research_api.start_digest({"text": "original paper material", "title": "paper"})
    result = workers[0](lambda *args: None)
    assert result["source"]["text"] == "original paper material"
    assert result["source"]["kind"] == "paper"


def test_context_recovery_accepts_dashboard_parse_qs_shape(tmp_path, monkeypatch):
    from urllib.parse import parse_qs

    monkeypatch.setattr(workbench, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(research_api, "_JOBS", {})
    jid, _ = research_api._claim_job("digest", {"request_id": "recover-with-query"})
    research_api._update_job(jid, status="done", result={"title": "paper"})
    monkeypatch.setattr(research_api, "_providers", list)
    result, status = research_api.handle_get(
        "/api/research/context", parse_qs("request_id=recover-with-query")
    )
    assert status == 200
    assert [record["id"] for record in result["jobs"]] == [jid]
