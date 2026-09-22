"""R0: real SQLite sessions survive resets/restarts without automatic promotion."""

from types import SimpleNamespace

import pytest

from lighthermes.cli import CLI
from lighthermes.core import LightHermes
from lighthermes.memory import DEFAULT_USER_ID, MemoryManager


def make_cli(path):
    cli = CLI()
    cli.cli_config = {"color_enabled": False}
    cli.agent = SimpleNamespace(
        memory_enabled=True, memory=MemoryManager(str(path)),
        compression_enabled=False, query_count=0, api_call_count=0,
        total_tokens_used=0,
    )
    return cli


def test_reset_and_restart_keep_distinct_sources(tmp_path):
    cli = make_cli(tmp_path / "memory")
    first = cli.session_id
    cli.agent.memory.add_message("user", "Project A uses Python.")
    cli.agent.memory.add_message("assistant", "Noted for A.")
    cli.reset_session()
    second = cli.session_id
    assert second != first
    cli.agent.memory.add_message("user", "Project B uses TypeScript.")
    cli.agent.memory.add_message("assistant", "Noted for B.")
    assert cli.end_session() is True
    assert cli.end_session() is True

    restarted = make_cli(tmp_path / "memory")
    memory = restarted.agent.memory
    assert restarted.session_id not in {first, second}
    sessions = memory.working.get_recent_sessions(DEFAULT_USER_ID)
    assert {s["session_id"] for s in sessions} == {first, second}
    assert "Python" in memory.get_source(f"working:{first}")["content"]
    assert "TypeScript" in memory.get_source(f"working:{second}")["content"]
    assert "TypeScript" not in memory.get_source(f"working:{first}")["content"]
    # Default recall must use the same user namespace as the CLI writer.
    assert any(item["source"] == f"working:{first}" for item in memory.recall_items("Python"))
    assert not list(memory.episodic.storage_dir.glob("*.md"))
    assert not list(memory.semantic.storage_dir.glob("*.md"))


def test_failed_save_does_not_clear_or_rotate_session(tmp_path, monkeypatch, capsys):
    cli = make_cli(tmp_path / "memory")
    original_id = cli.session_id
    cli.agent.memory.add_message("user", "Do not lose this message.")

    def failed_save(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(cli.agent.memory.working, "save_conversation", failed_save)
    cli.reset_session()
    assert cli.session_id == original_id
    assert cli.agent.memory.get_context()[0]["content"] == "Do not lose this message."
    assert "保存失败" in capsys.readouterr().out


def test_normal_turn_never_runs_hit_adaptation_or_skill_activation(tmp_path, monkeypatch):
    adapter = SimpleNamespace(model="test-model", create=lambda **kwargs: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="Done", tool_calls=None))],
        usage=None,
    ))
    monkeypatch.setattr("lighthermes.core.get_adapter", lambda **kwargs: adapter)
    agent = LightHermes(api_key="test", memory_dir=str(tmp_path / "memory"),
                        config_path=None, skill_dirs=[], config={"context_compression": {"enabled": False}})

    def forbidden(*args, **kwargs):
        pytest.fail("Normal turns must not run legacy automatic maintenance")

    monkeypatch.setattr(agent.memory, "adapt_weights", forbidden)
    monkeypatch.setattr(agent.memory, "auto_migrate", forbidden)
    agent.query_count = 99
    assert agent.run("hello") == "Done"
    first_id = agent.session_id
    assert agent.run("next") == "Done"
    assert agent.session_id == first_id
    assert agent.evolution is None
    agent.memory.on_session_end(first_id, summary="Normal completion")
    assert agent.memory.working.get_recent_sessions(DEFAULT_USER_ID)[0]["session_id"] == first_id


def test_working_store_propagates_persistence_failure(tmp_path, monkeypatch):
    memory = MemoryManager(str(tmp_path / "memory"))

    def failed_connect(*args, **kwargs):
        raise OSError("read-only filesystem")

    monkeypatch.setattr("lighthermes.memory.sqlite3.connect", failed_connect)
    with pytest.raises(OSError, match="read-only"):
        memory.working.add_session("one", DEFAULT_USER_ID, "summary")
    with pytest.raises(OSError, match="read-only"):
        memory.working.save_conversation("one", DEFAULT_USER_ID, [])
