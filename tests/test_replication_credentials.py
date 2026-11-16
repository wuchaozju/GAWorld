"""A successful personal-key probe must also work inside parallel survey answers."""

import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest import mock

import pytest

from gaworld.accounts.context import USER, WORLD
from gaworld.apps import replication_api
from gaworld.llm import credentials, providers
from gaworld.research import replication as rp
from tests.test_replication import PEOPLE, RAW_SPEC, framed_answer


@pytest.fixture
def personal_models(monkeypatch, tmp_path):
    monkeypatch.setenv(credentials.ENV_PATH, str(tmp_path.resolve() / "private" / "keys.json"))
    monkeypatch.delenv("GAWORLD_USER_ID", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = {"type": "openai", "base_url": "https://models.invalid/v1", "model": "test-model"}
    router = providers.LLMRouter(
        {"llm": {"providers": {"deepseek_flash": cfg}, "routing": {"default": "deepseek_flash"}}}
    )
    monkeypatch.setattr(providers, "LLM_ROUTER", router)
    monkeypatch.setattr(replication_api, "_LLM_OVERRIDE", None)
    monkeypatch.setattr(rp, "replication_root", lambda: tmp_path / "runs")
    monkeypatch.setattr("gaworld.interview.roster.recruitment_population", lambda _: PEOPLE)
    monkeypatch.setattr("gaworld.interview.roster.recruitment_profile", lambda *_: "")
    seen, usage = [], []

    def post(url, **kwargs):
        uid, world = USER.get()["id"], WORLD.get()["id"]
        assert url == "https://models.invalid/v1/chat/completions"
        assert kwargs["headers"]["Authorization"] == f"Bearer member-{uid}-test-key"
        assert world == f"world-{uid}"
        prompt = kwargs["json"]["messages"][-1]["content"]
        seen.append((uid, world))
        time.sleep(0.002)
        reply = "OK" if prompt == providers._PROBE_PROMPT else framed_answer(prompt)
        return SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: {"choices": [{"message": {"content": reply}}]}
        )

    monkeypatch.setattr(providers, "_post", post)
    monkeypatch.setattr(
        "gaworld.accounts.usage.record", lambda task: usage.append(((USER.get() or {}).get("id"), task))
    )
    return cfg, router, seen, usage


def test_personal_probe_and_parallel_replication_use_the_same_account(personal_models):
    cfg, _, seen, usage = personal_models

    def run_as(uid):
        user_token = USER.set({"id": uid, "role": "member"})
        world_token = WORLD.set({"id": f"world-{uid}"})
        try:
            credentials.save(cfg, f"member-{uid}-test-key")
            assert providers.probe_provider(cfg)["ok"]
            job = replication_api.start_run(
                {
                    "spec": RAW_SPEC,
                    "sample_size": 5,
                    "design": "paired",
                    "provider": "deepseek_flash",
                    "interpret": False,
                }
            )
            for _ in range(250):
                record = replication_api._JOBS.status(job["job_id"])
                if record["status"] != "running":
                    assert record["status"] == "done", record.get("error")
                    run = rp.load_run(record["result"]["run_id"])
                    assert run["owner_id"] == uid
                    assert len(run["responses"]) == 10
                    assert run["failed"] == 0
                    return
                time.sleep(0.01)
            pytest.fail("replication did not finish")
        finally:
            WORLD.reset(world_token)
            USER.reset(user_token)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run_as, [8, 11]))
    for uid in [8, 11]:
        assert seen.count((uid, f"world-{uid}")) == 11  # One probe and ten answers.
        assert usage.count((uid, "research.replication.answer")) == 10


@pytest.mark.parametrize("task", ["extract", "answer", "interpret"])
def test_replication_does_not_fall_back_to_a_different_model(personal_models, task):
    _, router, _, _ = personal_models
    primary = mock.Mock()
    primary.call.side_effect = ValueError("Primary model unavailable")
    fallback = mock.Mock()
    fallback.call.return_value = "Reply from a different model"
    router.providers = {"deepseek_flash": primary, "ollama_gemma4": fallback}
    router.routing = {"default": "deepseek_flash", "fallback": ["ollama_gemma4"]}
    with mock.patch("gaworld.accounts.usage.record"):
        with pytest.raises(ValueError, match="Primary model unavailable"):
            replication_api._llm("deepseek_flash", task, 0.1, 100)("Prompt")
    primary.call.assert_called_once()
    fallback.call.assert_not_called()
