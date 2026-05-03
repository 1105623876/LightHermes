"""CLI 集成测试"""

from types import SimpleNamespace

import pytest

from lighthermes.cli import CLI


class FakeSkillLoader:
    def get_all_skills(self):
        return [
            {"name": "debug", "description": "调试问题"}
        ]


class FakeCompressor:
    def __init__(self):
        self.compression_count = 1
        self.tokens_saved = 12
        self.compressed_messages = [
            {"role": "assistant", "content": "摘要"}
        ]

    def get_stats(self):
        return {
            "compression_count": self.compression_count,
            "tokens_saved": self.tokens_saved,
            "avg_tokens_saved": self.tokens_saved // self.compression_count
        }

    def compress(self, messages):
        return self.compressed_messages


class FakeAgent:
    def __init__(self):
        self.name = "LightHermes"
        self.model = "test-model"
        self.memory_enabled = True
        self.evolution_enabled = True
        self.compression_enabled = True
        self.debug = False
        self.query_count = 2
        self.api_call_count = 3
        self.total_tokens_used = 100
        self.skill_loader = FakeSkillLoader()
        self.compressor = FakeCompressor()
        self.memory = SimpleNamespace(
            short_term=SimpleNamespace(messages=[
                {"role": "user", "content": "1"},
                {"role": "assistant", "content": "2"},
                {"role": "user", "content": "3"},
                {"role": "assistant", "content": "4"},
                {"role": "user", "content": "5"}
            ]),
            episodic=SimpleNamespace(storage_dir="missing-episodic-dir"),
            semantic=SimpleNamespace(storage_dir="missing-semantic-dir")
        )

    def run(self, user_input, stream=True, session_id=None):
        if stream:
            return iter(["pong"])
        return "pong"


@pytest.fixture
def cli():
    instance = CLI()
    instance.agent = FakeAgent()
    instance.cli_config = {"color_enabled": False, "show_banner": False}
    return instance


@pytest.mark.integration
class TestCLICommands:
    """测试 CLI 命令处理"""

    def test_help_command_prints_available_commands(self, cli, capsys):
        assert cli.handle_command("/help") is True

        output = capsys.readouterr().out
        assert "/help" in output
        assert "/compress" in output

    def test_exit_command_stops_loop(self, cli):
        assert cli.handle_command("/exit") is False

    def test_unknown_command_prints_hint(self, cli, capsys):
        assert cli.handle_command("/unknown") is True

        output = capsys.readouterr().out
        assert "未知命令: /unknown" in output
        assert "输入 /help 查看可用命令" in output

    def test_show_config_uses_agent_state(self, cli, capsys):
        cli.handle_command("/config")

        output = capsys.readouterr().out
        assert "模型: test-model" in output
        assert "记忆系统: 启用" in output
        assert "自进化: 启用" in output
        assert "上下文压缩: 启用" in output

    def test_manual_compress_replaces_short_term_messages(self, cli, capsys):
        cli.handle_command("/compress")

        output = capsys.readouterr().out
        assert "压缩完成" in output
        assert cli.agent.memory.short_term.messages == [
            {"role": "assistant", "content": "摘要"}
        ]

    def test_reset_session_clears_stats_and_short_term_memory(self, cli, capsys):
        cli.handle_command("/reset")

        output = capsys.readouterr().out
        assert "会话已重置" in output
        assert cli.agent.memory.short_term.messages == []
        assert cli.agent.query_count == 0
        assert cli.agent.api_call_count == 0
        assert cli.agent.total_tokens_used == 0
        assert cli.agent.compressor.compression_count == 0
        assert cli.agent.compressor.tokens_saved == 0

    def test_run_handles_command_then_exit(self, cli, monkeypatch, capsys):
        inputs = iter(["/help", "/exit"])
        monkeypatch.setattr("builtins.input", lambda prompt: next(inputs))
        cli.init_agent = lambda: None

        cli.run()

        output = capsys.readouterr().out
        assert "LightHermes" in output
        assert "可用命令" in output

    def test_run_prints_non_stream_response(self, cli, monkeypatch, capsys):
        inputs = iter(["hello", "/exit"])
        monkeypatch.setattr("builtins.input", lambda prompt: next(inputs))
        cli.init_agent = lambda: None
        cli.cli_config = {
            "color_enabled": False,
            "show_banner": False,
            "stream_output": False
        }

        cli.run()

        output = capsys.readouterr().out
        assert "pong" in output
