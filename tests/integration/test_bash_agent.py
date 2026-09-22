"""Scripted model, real file edits and verification through the production tool loop."""

import json
import os
import shlex
import sys
from types import SimpleNamespace as NS

import pytest

from lighthermes.cli import CLI
from lighthermes.core import LightHermes


pytestmark = pytest.mark.skipif(os.name != "posix", reason="R1 supports POSIX bash")


class ScriptedAdapter:
    model = "offline-scripted"

    def __init__(self, steps):
        self.steps = iter(steps)
        self.messages = None

    def create(self, messages, stream=False, **kwargs):
        self.messages = messages
        commands = next(self.steps)
        calls = [NS(id=f"call-{i}", function=NS(name="bash", arguments=json.dumps({"command": cmd})))
                 for i, cmd in enumerate(commands or [])]
        content = "Verified task completed" if commands is None else ""
        if stream:
            deltas = [NS(index=i, id=call.id, function=call.function) for i, call in enumerate(calls)]
            return iter([NS(choices=[NS(delta=NS(content=content, tool_calls=deltas),
                                       finish_reason="tool_calls" if calls else "stop")])])
        return NS(choices=[NS(message=NS(content=content, tool_calls=calls))], usage=None)


def agent_for(tmp_path, monkeypatch, steps, authorized=True):
    adapter = ScriptedAdapter(steps)
    monkeypatch.setattr("lighthermes.core.get_adapter", lambda **kwargs: adapter)
    agent = LightHermes(api_key="test", config_path=None, memory_dir=str(tmp_path / "memory"),
                        skill_dirs=[], bash_cwd=str(tmp_path), bash_authorized=authorized,
                        config={"context_compression": {"enabled": False}})
    return agent, adapter


@pytest.mark.parametrize("stream", [False, True])
def test_read_edit_verify_in_both_loops(tmp_path, monkeypatch, stream):
    target = tmp_path / "calc.py"
    target.write_text("def add(a, b):\n    return a - b\n")
    python = shlex.quote(sys.executable)
    edit = "from pathlib import Path; p=Path('calc.py'); p.write_text(p.read_text().replace('a - b', 'a + b'))"
    verify = "from calc import add; assert add(3, 2) == 5; print('verified')"
    agent, adapter = agent_for(tmp_path, monkeypatch, [
        ["cat calc.py"], [f"{python} -c {shlex.quote(edit)} && {python} -c {shlex.quote(verify)}"], None,
    ])
    result = agent.run("Fix add and verify the result", stream=stream)
    assert ("".join(result) if stream else result) == "Verified task completed"
    observations = [json.loads(m["content"]) for m in adapter.messages if m["role"] == "tool"]
    assert len(observations) == 2
    assert observations[0]["output"].endswith("return a - b\n")
    assert observations[1]["output"] == "verified\n"
    assert all(item["exit_code"] == 0 for item in observations)
    assert "a + b" in target.read_text()
    assert agent.query_count == 1
    assert agent.last_turn["session_id"] == agent.session_id
    assert agent.last_turn["status"] == "completed"
    assert agent.last_turn["messages"] is adapter.messages


@pytest.mark.parametrize("stream", [False, True])
def test_batch_cannot_exceed_tool_budget(tmp_path, monkeypatch, stream):
    agent, _ = agent_for(tmp_path, monkeypatch, [["touch one", "touch two"]])
    result = agent.run("Do work", stream=stream, max_iterations=1)
    assert "任务未完成" in ("".join(result) if stream else result)
    assert not (tmp_path / "one").exists() and not (tmp_path / "two").exists()
    assert agent.query_count == 0
    assert agent.last_turn["status"] == "budget_exhausted"


@pytest.mark.parametrize("stream", [False, True])
def test_cancellation_stops_batch_and_does_not_finalize(tmp_path, monkeypatch, stream):
    agent, adapter = agent_for(tmp_path, monkeypatch, [["sleep 5", "touch later"]])

    def cancelled(*args, **kwargs):
        return {"status": "cancelled", "exit_code": -9, "output": "partial"}

    monkeypatch.setattr(agent.bash, "execute", cancelled)
    with pytest.raises(KeyboardInterrupt):
        result = agent.run("Do work", stream=stream)
        if stream:
            list(result)
    assert agent.query_count == 0
    assert agent.last_turn["status"] == "cancelled"
    assert len([m for m in adapter.messages if m["role"] == "tool"]) == 1
    assert not (tmp_path / "later").exists()


def test_cli_authorization_is_explicit_and_unattended_is_denied(tmp_path, monkeypatch):
    agent, _ = agent_for(tmp_path, monkeypatch, [], authorized=False)
    cli = CLI()
    cli.agent = agent
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")
    cli.authorize_bash()
    assert agent.bash.authorized
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    cli.authorize_bash()
    assert not agent.bash.authorized


@pytest.mark.parametrize("stream", [False, True])
def test_model_budget_exhaustion_is_not_completed(tmp_path, monkeypatch, stream):
    agent, _ = agent_for(tmp_path, monkeypatch, [["printf progress"]])
    result = agent.run("Do work", stream=stream, max_iterations=1)
    assert "任务未完成" in ("".join(result) if stream else result)
    assert agent.last_turn["status"] == "budget_exhausted"
    assert agent.query_count == 0


def test_bad_tool_arguments_are_observations_not_loop_crashes(tmp_path, monkeypatch):
    agent, _ = agent_for(tmp_path, monkeypatch, [])
    messages = []
    agent._append_tool_exchange(messages, [{
        "id": "bad", "function": {"name": "bash", "arguments": "{}"},
    }])
    assert "Tool call error" in messages[-1]["content"]
