import pytest


def test_incremental_utf8_redaction_and_rotation(tmp_path):
    from gaworld.research.run_logs import read_chunk

    path = tmp_path / "run.log"
    path.write_text("中文第一行\nAuthorization: Bearer secret-token\n", encoding="utf-8")
    first = read_chunk(path, tmp_path, offset=0, secrets=["secret-token"], limit=20)
    assert first["text"] == "中文第一行\n"
    second = read_chunk(
        path, tmp_path, offset=first["next_offset"], file_id=first["file_id"], secrets=["secret-token"]
    )
    assert "secret-token" not in second["text"]
    assert "[REDACTED]" in second["text"]
    path.unlink()
    path.write_text("新日志\n", encoding="utf-8")
    rotated = read_chunk(path, tmp_path, offset=second["next_offset"], file_id=second["file_id"])
    assert rotated["reset"]
    assert "新日志" in rotated["text"]


def test_log_paths_reject_escape_and_symlink(tmp_path):
    from gaworld.research.run_logs import read_chunk

    world = tmp_path / "world"
    world.mkdir()
    outside = tmp_path / "secret"
    outside.write_text("secret\n")
    link = world / "run.log"
    link.symlink_to(outside)
    with pytest.raises(ValueError):
        read_chunk(link, world)
    with pytest.raises(ValueError):
        read_chunk(outside, world)


def test_partial_secret_line_waits_until_complete(tmp_path):
    from gaworld.research.run_logs import read_chunk

    path = tmp_path / "run.log"
    path.write_text('api_key="secret')
    first = read_chunk(path, tmp_path, secrets=["secret-value"])
    assert first["text"] == ""
    with path.open("a") as handle:
        handle.write('-value"\n')
    second = read_chunk(path, tmp_path, offset=first["next_offset"], secrets=["secret-value"])
    assert "secret" not in second["text"]


def test_oversized_line_never_exposes_secret_continuation(tmp_path):
    from gaworld.research.run_logs import read_chunk

    path = tmp_path / "run.log"
    path.write_text("Authorization: Bearer " + "x" * 100 + "\nokay\n")
    offset = 0
    result_text = ""
    for _ in range(12):
        result = read_chunk(path, tmp_path, offset=offset, limit=32)
        offset = result["next_offset"]
        result_text += result["text"]
        if not result["has_more"]:
            break
    assert "xxxx" not in result_text
    assert "okay" in result_text


def test_unlabeled_echo_of_default_and_legacy_credentials_is_redacted(monkeypatch):
    from gaworld.research.run_logs import configured_secrets, redact

    monkeypatch.setenv("ANTHROPIC_API_KEY", "default-secret-echo")
    config = {
        "llm": {"providers": {"claude": {"type": "claude", "ANTHROPIC_AUTH_TOKEN": "legacy-secret-echo"}}}
    }
    text = "arbitrary server message default-secret-echo /path?token=legacy-secret-echo"
    safe = redact(text, configured_secrets(config))
    assert "default-secret-echo" not in safe
    assert "legacy-secret-echo" not in safe
