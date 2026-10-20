"""Local-task adapter for the unmodified Google recursion/selection/library workflow."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import tomllib
from pathlib import Path

from .core import tree
from .core.spec import BenchPrompts, BenchSpec, ChannelSpec
from .substrate.codex import CodexSubstrate
from .substrate.codex_login import run_codex


def checked_files(root: Path) -> list[Path]:
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symlinks are not supported: {path}")
        if path.is_file():
            files.append(path)
    return files


class LocalCodexAdapter:
    def __init__(
        self,
        tasks: Path,
        harness: Path,
        output: Path,
        *,
        model: str,
        effort: str,
        timeout: int,
        work: str,
        documents_only: bool = False,
        improver_model: str | None = None,
        improver_effort: str | None = None,
    ):
        self.substrate = CodexSubstrate()
        self.root = output.resolve()
        self.model, self.effort, self.timeout = model, effort, timeout
        self.documents_only = documents_only
        if not tasks.is_dir() or not harness.is_dir():
            raise ValueError("--tasks and --harness must be existing directories")
        for source in (tasks.resolve(), harness.resolve()):
            if self.root.is_relative_to(source) or source.is_relative_to(self.root):
                raise ValueError("Output and input directories must not overlap")
        self._tasks: dict[str, tuple[Path, str]] = {}
        fingerprint = hashlib.sha256()
        for label, source in (("tasks", tasks), ("harness", harness)):
            for path in checked_files(source):
                fingerprint.update(f"{label}/{path.relative_to(source)}\0".encode())
                fingerprint.update(path.read_bytes())
                fingerprint.update(b"\0")
        for source in sorted(tasks.iterdir()):
            if not source.is_dir():
                continue
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", source.name):
                raise ValueError(f"Invalid task ID: {source.name}")
            if not (source / "task.md").is_file():
                raise ValueError(f"Missing task.md: {source}")
            options = (
                tomllib.loads((source / "task.toml").read_text())
                if (source / "task.toml").exists()
                else {}
            )
            if set(options) - {"domain"}:
                raise ValueError(f"Unsupported task options: {source}")
            domain = options.get("domain", "local")
            if not isinstance(domain, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", domain):
                raise ValueError(f"Invalid task domain: {source}")
            files = source / "files"
            if any((files / name).exists() for name in ("AGENTS.md", ".agents", ".codex", ".git")):
                raise ValueError(f"Task source must not contain agent configuration: {source}")
            self._tasks[source.name] = (source, domain)
        if not self._tasks:
            raise ValueError("No tasks found")
        rejected: list[str] = []
        base = tree.read_tree(self.substrate.surface(), harness, rejected=rejected)
        if rejected:
            raise ValueError(f"Unsupported harness files (not silently omitted): {rejected[:5]}")
        self.validate_tree(base)
        channel = ChannelSpec(
            "codex_cli", improver_model or model, effort=improver_effort or effort, timeout=timeout
        )
        self.spec = BenchSpec(
            name="local",
            runs_root=self.root / "runs",
            install_mode="codex_root",
            prompts=BenchPrompts(work=work),
            channels={"proposer": channel, "selector": channel},
        )
        identity = {
            "inputs": fingerprint.hexdigest(),
            "model": model,
            "effort": effort,
            "work": work,
            "timeout": timeout,
            "documents_only": documents_only,
            "external_sandbox": os.environ.get("HARNESS2_CODEX_EXTERNAL_SANDBOX") == "1",
        }
        if (channel.model, channel.effort) != (model, effort):
            identity["improver"] = {"model": channel.model, "effort": channel.effort}
        if (
            self.root.exists()
            and any(self.root.iterdir())
            and not (self.root / "inputs.json").is_file()
        ):
            raise ValueError("Output must be empty or an existing local run directory")
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)
        manifest = self.root / "inputs.json"
        if manifest.exists() and json.loads(manifest.read_text()) != identity:
            raise ValueError("Inputs/settings changed: use a new output directory")
        manifest.write_text(json.dumps(identity, indent=2) + "\n")
        tree.write_tree(self.substrate.surface(), base, self.base_harness(), stubs=False)

    def tasks(self, split: str = "all") -> list[str]:
        if split != "all":
            raise ValueError("The local adapter supports split=all only")
        return list(self._tasks)

    def domain_of(self, task_id: str) -> str:
        return self._tasks[task_id][1]

    def task_prompt(self, task_id: str) -> str:
        return (self._tasks[task_id][0] / "task.md").read_text()

    def task_files(self, task_id: str) -> Path | None:
        path = self._tasks[task_id][0] / "files"
        return path if path.is_dir() else None

    def base_harness(self) -> Path:
        return self.root / "base"

    def validate_tree(self, harness: tree.Tree) -> None:
        tree.validate(self.substrate.surface(), harness, allow_subagents=False)
        if ".codex/hooks.json" in harness:
            raise ValueError("Local tasks do not enable model-authored hooks")
        if self.documents_only and any(
            name != "AGENTS.md" and not re.fullmatch(r"\.agents/skills/[a-z0-9_-]+/SKILL\.md", name)
            for name in harness
        ):
            raise ValueError("documents-only permits AGENTS.md and skill entrypoints only")

    def execute(
        self, task_id: str, harness_dir: Path | None, run_id: str, *, timeout: int | None = None
    ) -> Path:
        run_dir = self.root / "executions" / run_id
        if not run_dir.resolve().is_relative_to(self.root / "executions"):
            raise ValueError("Invalid run ID")
        run_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="harness2-local-") as temporary:
            workspace = Path(temporary)
            source = self.task_files(task_id)
            if source is not None:
                shutil.copytree(source, workspace, dirs_exist_ok=True)
            harness = tree.read_tree(self.substrate.surface(), harness_dir or self.base_harness())
            self.validate_tree(harness)
            tree.write_tree(self.substrate.surface(), harness, workspace, stubs=False)
            result = run_codex(
                workspace,
                self.task_prompt(task_id),
                self.model,
                self.effort,
                timeout or self.timeout,
            )
            (run_dir / "stream.jsonl").write_text(result.stream)
            if result.error:
                raise RuntimeError(result.error)
            (run_dir / "answer.txt").write_text(result.text)
        return run_dir

    def delivered(self, run_dir: Path) -> bool:
        return (run_dir / "answer.txt").is_file() and bool(self.deliverable_text(run_dir).strip())

    def trajectory(self, run_dir: Path, *, obs_trunc: int) -> str:
        return self.substrate.read_trajectory(
            run_dir / "stream.jsonl", obs_trunc=obs_trunc, max_chars=200_000
        )

    def deliverable_text(self, run_dir: Path) -> str:
        return (run_dir / "answer.txt").read_text()

    def deliverable_files(self, run_dir: Path) -> dict[str, str]:
        return {"answer.txt": self.deliverable_text(run_dir)}
