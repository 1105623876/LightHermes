"""Exercise real subprocess limits in temporary workspaces; no model/network calls."""

import os
import shlex
import sys
import time

import pytest

from lighthermes.bash import BashExecutor, _Output


pytestmark = pytest.mark.skipif(os.name != "posix", reason="R1 supports POSIX bash")


def test_permission_is_required_and_command_cannot_authorize_itself(tmp_path):
    executor = BashExecutor(tmp_path)
    assert executor.execute("touch unauthorized")["status"] == "not_authorized"
    assert not (tmp_path / "unauthorized").exists()


def test_independent_cwd_and_environment(tmp_path, monkeypatch):
    (tmp_path / "nested").mkdir()
    monkeypatch.setenv("LIGHTHERMES_API_KEY", "must-not-be-inherited")
    monkeypatch.setenv("BASH_ENV", str(tmp_path / "startup"))
    (tmp_path / "startup").write_text("touch sourced-profile\n")
    executor = BashExecutor(tmp_path, authorized=True, env={"EXPLICIT_VALUE": "allowed"})
    assert executor.execute("cd nested; export LOCAL_ONLY=1; pwd")["output"].strip() == str(tmp_path / "nested")
    result = executor.execute('printf "%s|%s|%s|%s" "$PWD" "${LOCAL_ONLY-unset}" "${LIGHTHERMES_API_KEY-unset}" "$EXPLICIT_VALUE"')
    assert result["output"] == f"{tmp_path}|unset|unset|allowed"
    assert not (tmp_path / "sourced-profile").exists()
    assert executor.execute("pwd", cwd="nested")["cwd"] == str(tmp_path / "nested")


def test_failure_and_launch_error_are_distinct(tmp_path):
    executor = BashExecutor(tmp_path, authorized=True)
    result = executor.execute("printf failure >&2; exit 7")
    assert (result["status"], result["exit_code"], result["output"]) == ("failed", 7, "failure")
    assert executor.execute("pwd", cwd="missing")["status"] == "execution_error"


@pytest.mark.parametrize("timeout", [0, -1, 301, float("nan"), float("inf"), True, "bad"])
def test_invalid_timeout_cannot_execute(tmp_path, timeout):
    executor = BashExecutor(tmp_path, authorized=True)
    assert executor.execute("touch unsafe", timeout=timeout)["status"] == "invalid_arguments"
    assert not (tmp_path / "unsafe").exists()


def test_large_unicode_output_is_bounded_and_contains_head_and_tail(tmp_path):
    executor = BashExecutor(tmp_path, authorized=True)
    command = f"{shlex.quote(sys.executable)} -c \"print('HEAD' + '字'*200000 + 'TAIL')\""
    result = executor.execute(command)
    assert result["status"] == "completed"
    assert result["truncated"]
    assert len(result["output"]) <= 12000
    assert result["output"].startswith("HEAD") and result["output"].endswith("TAIL\n")
    assert "�" not in result["output"]
    buffer = _Output()
    for _ in range(100):
        buffer.add("x" * 4096)
        assert len(buffer.head) + len(buffer.tail) <= 12000


@pytest.mark.parametrize("command", ["sleep 5", "exec 1>&- 2>&-; sleep 5"])
def test_timeout_handles_open_and_closed_output_pipes(tmp_path, command):
    started = time.monotonic()
    result = BashExecutor(tmp_path, authorized=True).execute(command, timeout=0.1)
    assert result["status"] == "timeout"
    assert result["exit_code"] != 0
    assert time.monotonic() - started < 2


def test_background_process_cannot_outlive_action(tmp_path):
    executor = BashExecutor(tmp_path, authorized=True)
    result = executor.execute("(sleep 0.3; touch leaked) & printf done")
    assert result["status"] == "completed"
    time.sleep(0.4)
    assert not (tmp_path / "leaked").exists()


def test_cancel_kills_process_group(tmp_path, monkeypatch):
    import selectors

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(selectors.DefaultSelector, "select", interrupt)
    result = BashExecutor(tmp_path, authorized=True).execute("sleep 0.3; touch leaked")
    assert result["status"] == "cancelled"
    time.sleep(0.4)
    assert not (tmp_path / "leaked").exists()
