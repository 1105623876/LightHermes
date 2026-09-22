"""Supported configuration must affect behavior; retired options fail explicitly."""

from types import SimpleNamespace

import pytest

from lighthermes.core import LightHermes
from lighthermes.skills import SkillLoader


@pytest.mark.parametrize("config, message", [
    ({"plugins": {"dirs": ["plugins/tools"]}}, "Plugin loading"),
    ({"skills": {"enabled": False}}, "skills.enabled"),
    ({"skills": {"auto_load": True}}, "skills.auto_load"),
    ({"memory": {"adaptive": {"enabled": True}}}, "adaptation"),
    ({"memory": {"adaptive": {"adapt_interval": 7}}}, "adaptation"),
    ({"memory": {"retention": {"episodic_auto_archive": False}}}, "episodic_auto_archive"),
    ({"evolution": {"sandbox": {"max_memory_mb": 512}}}, "max_memory_mb"),
    ({"evolution": {"auto_generate_skills": True}}, "Automatic skill activation"),
])
def test_retired_config_rejected_before_creating_clients(config, message):
    with pytest.raises(ValueError, match=message):
        LightHermes(config=config, config_path=None)


def test_explicit_plugin_and_auto_activation_arguments_rejected():
    with pytest.raises(ValueError, match="Plugin loading"):
        LightHermes(config_path=None, plugin_dirs=["plugins"])
    with pytest.raises(ValueError, match="Automatic skill activation"):
        LightHermes(config_path=None, auto_generate_skills=True)


def test_empty_skill_dirs_stays_empty(tmp_path, monkeypatch):
    skills = tmp_path / "skills/core"
    skills.mkdir(parents=True)
    (skills / "unexpected.md").write_text("---\nname: unexpected\n---\nDo not load me")
    monkeypatch.setattr("lighthermes.core.get_adapter", lambda **kwargs: SimpleNamespace())
    agent = LightHermes(api_key="test", config_path=None, skill_dirs=[],
                        memory_dir=str(tmp_path / "memory"), config={
                            "context_compression": {"enabled": False},
                        })
    assert agent.skill_loader.get_all_skills() == []


def test_disabled_skill_and_removed_file_do_not_survive_reload(tmp_path):
    (tmp_path / "disabled.md").write_text("---\nname: disabled\n---\nNot allowed")
    active = tmp_path / "active.md"
    active.write_text("---\nname: active\n---\nUse me")
    loader = SkillLoader([str(tmp_path)], disabled=["disabled"])
    assert loader.match_skill("/disabled") is None
    assert loader.match_skill("/active") is not None
    active.unlink()
    loader.load_all()
    assert loader.match_skill("/active") is None


def test_partial_live_config_reload_is_rejected():
    with pytest.raises(ValueError, match="from_config"):
        LightHermes.__new__(LightHermes).load_config()
