"""ChatGPT-authenticated Codex transport; no API bridge or model credentials in config.

The caller supplies a dedicated CODEX_HOME already signed in with `codex login`.
The external sandbox opt-in is for a container/Cloudflare Sandbox, never a host default.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CodexResult:
    text: str
    stream: str
    error: str = ""


def login_environment() -> dict[str, str]:
    home = os.environ.get("CODEX_HOME", "")
    if not home or not Path(home).is_absolute():
        raise ValueError("Set CODEX_HOME to a dedicated absolute ChatGPT login directory")
    # Codex itself seeds skills/plugins cache directories on first execution.
    # Their existence is not evidence of a personal configuration being loaded.
    for name in ("AGENTS.md", "hooks.json"):
        if (Path(home) / name).exists():
            raise ValueError("CODEX_HOME must not contain personal instructions, hooks, or plugins")
    # Same principle as Peco: arbitrary environment credentials and preload/proxy
    # settings do not enter a model process. This does not isolate files/processes
    # inside a shared container; that is the external sandbox's trust boundary.
    allowed = {
        "PATH",
        "HOME",
        "CODEX_HOME",
        "TMPDIR",
        "TMP",
        "TEMP",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
    }
    return {key: value for key, value in os.environ.items() if key in allowed}


def codex_binary() -> str:
    binary = shutil.which(os.environ.get("HARNESS2_CODEX_BINARY", "codex"))
    if binary is None:
        raise ValueError("Codex CLI is not installed or HARNESS2_CODEX_BINARY is invalid")
    return binary


def check_login() -> None:
    result = subprocess.run(
        [codex_binary(), "login", "status"],
        env=login_environment(),
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode or "ChatGPT" not in result.stdout + result.stderr:
        raise ValueError("Sign in to ChatGPT with `CODEX_HOME=<dedicated directory> codex login`")


def run_codex(cwd: Path, prompt: str, model: str, effort: str, timeout: int) -> CodexResult:
    if not model.strip() or "/" in model:
        raise ValueError("Codex ChatGPT model must be a nonempty bare model ID")
    argv = [
        codex_binary(),
        "exec",
        "--json",
        "--ephemeral",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--ignore-rules",
        "--model",
        model,
        "-c",
        f"model_reasoning_effort={json.dumps(effort)}",
        "-c",
        'forced_login_method="chatgpt"',
        "-c",
        'model_provider="openai"',
        "-c",
        'approval_policy="never"',
        "-C",
        str(cwd),
    ]
    if os.environ.get("HARNESS2_CODEX_EXTERNAL_SANDBOX") == "1":
        argv.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        argv.extend(["--sandbox", "workspace-write"])
    argv.append("-")
    result = subprocess.run(
        argv,
        input=prompt,
        cwd=cwd,
        env=login_environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    text, completed, failed = "", False, False
    for line in result.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        completed |= event.get("type") == "turn.completed"
        failed |= event.get("type") in ("error", "turn.failed")
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            text = str(item.get("text") or "")
    # An earlier message followed by failure is never a usable result. Do not
    # forward stderr/raw service errors: they may include sensitive material.
    error = ""
    if result.returncode or failed or not completed or not text.strip():
        text = ""
        error = f"CODEX_RUN_INCOMPLETE (exit={result.returncode}, completed={completed}, failed={failed})"
    return CodexResult(text, result.stdout, error)
