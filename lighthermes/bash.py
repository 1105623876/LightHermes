"""Bounded, explicitly authorized local bash execution (not a sandbox)."""

import codecs
import json
import math
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import time

from lighthermes.tools import tool


class _Output:
    """Keep a bounded head/tail while draining arbitrarily large pipe output."""

    def __init__(self, limit=12000):
        self.limit = limit
        self.head = ""
        self.tail = ""
        self.total = 0

    def add(self, text):
        self.total += len(text)
        missing = self.limit // 2 - len(self.head)
        self.head += text[:missing]
        self.tail = (self.tail + text[missing:])[-self.limit // 2:]

    def render(self):
        if self.total <= self.limit:
            return self.head + self.tail
        marker = "\n[output truncated]\n"
        return self.head + marker + self.tail[-(self.limit // 2 - len(marker)):]


def _kill_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


class BashExecutor:
    def __init__(self, cwd=None, *, authorized=False, env=None):
        self.cwd = Path(cwd or Path.cwd()).resolve()
        self.authorized = authorized
        self.env = dict(env or {})

    def execute(self, command, cwd=None, timeout=60):
        started = time.monotonic()
        result = {"status": "not_authorized", "exit_code": None, "output": "",
                  "truncated": False, "elapsed_ms": 0, "cwd": str(self.cwd)}
        if not self.authorized:
            return result
        executable = shutil.which("bash", path="/usr/bin:/bin")
        if os.name != "posix" or not executable:
            return {**result, "status": "unavailable", "error": "POSIX bash is required"}
        try:
            seconds = float(timeout)
            if isinstance(timeout, bool) or not math.isfinite(seconds) or not 0 < seconds <= 300:
                raise ValueError("timeout must be greater than 0 and at most 300 seconds")
            if not isinstance(command, str) or not command.strip():
                raise ValueError("command must be a non-empty string")
            target = Path(cwd) if cwd is not None else self.cwd
            if not target.is_absolute():
                target = self.cwd / target
            target = target.resolve()
        except (TypeError, ValueError, OSError) as exc:
            return {**result, "status": "invalid_arguments", "error": str(exc)}
        result["cwd"] = str(target)
        env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR") if key in os.environ}
        env.update(self.env)
        # Non-interactive bash can source BASH_ENV even with --norc.
        env.pop("BASH_ENV", None)
        env.pop("ENV", None)
        output = _Output()
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        process = None
        try:
            process = subprocess.Popen(
                [executable, "--noprofile", "--norc", "-c", command],
                cwd=target, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            result["status"] = "completed"
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    if time.monotonic() - started >= seconds:
                        result["status"] = "timeout"
                        break
                    if process.poll() is not None:
                        # Background descendants must not outlive an independent action.
                        _kill_group(process)
                    for key, _ in selector.select(0.05):
                        data = os.read(key.fileobj.fileno(), 4096)
                        if data:
                            output.add(decoder.decode(data))
                        else:
                            selector.unregister(key.fileobj)
                if result["status"] == "completed":
                    # A command may close stdout and keep running.
                    remaining = max(0.001, seconds - (time.monotonic() - started))
                    try:
                        process.wait(timeout=remaining)
                    except subprocess.TimeoutExpired:
                        result["status"] = "timeout"
        except KeyboardInterrupt:
            result["status"] = "cancelled"
        except OSError as exc:
            result.update(status="execution_error", error=str(exc))
        finally:
            if process is not None:
                _kill_group(process)
                process.wait()
                process.stdout.close()
                result["exit_code"] = process.returncode
            output.add(decoder.decode(b"", final=True))
            result.update(output=output.render(), truncated=output.total > output.limit,
                          elapsed_ms=round((time.monotonic() - started) * 1000, 2))
        if result["status"] == "completed" and result["exit_code"] != 0:
            result["status"] = "failed"
        return result

    @tool("bash", "在本机执行独立 bash 命令（非沙箱，需宿主授权）。cd/export 不跨调用保留；输出有上限，不支持后台任务。", [
        {"name": "command", "type": "string", "description": "bash 命令", "required": True},
        {"name": "cwd", "type": "string", "description": "工作目录，默认当前项目", "required": False},
        {"name": "timeout", "type": "number", "description": "秒，默认 60，最大 300", "required": False},
    ])
    def run(self, command, cwd=None, timeout=60):
        return json.dumps(self.execute(command, cwd, timeout), ensure_ascii=False)
