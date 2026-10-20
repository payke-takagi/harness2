"""Transport failure/privacy and original-workflow adapter regressions."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from harness2.core.proposer import Proposer
from harness2.core.spec import resolve_channel_model
from harness2.local import LocalCodexAdapter
from harness2.substrate.codex_login import check_login, login_environment, run_codex

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "examples/local-ledger"


class CodexLoginTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "login"
        self.home.mkdir()
        self.environment = patch.dict(
            os.environ,
            {"CODEX_HOME": str(self.home), "PATH": "/bin", "HOME": str(self.root)},
            clear=True,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def reply(self, events, returncode=0):
        return Mock(
            stdout="\n".join(json.dumps(e) for e in events),
            stderr="secret stderr",
            returncode=returncode,
        )

    def test_incomplete_turn_never_returns_an_earlier_answer(self):
        message = {"type": "item.completed", "item": {"type": "agent_message", "text": "earlier"}}
        for tail in (
            [{"type": "turn.failed"}],
            [],
            [{"type": "error"}, {"type": "turn.completed"}],
        ):
            with (
                self.subTest(tail=tail),
                patch("harness2.substrate.codex_login.codex_binary", return_value="/bin/codex"),
                patch(
                    "harness2.substrate.codex_login.subprocess.run",
                    return_value=self.reply([message, *tail]),
                ),
            ):
                result = run_codex(self.root, "request", "model", "medium", 10)
                self.assertEqual(result.text, "")
                self.assertIn("CODEX_RUN_INCOMPLETE", result.error)
                self.assertNotIn("secret stderr", result.error)

    def test_transport_excludes_credentials_and_defaults_to_workspace_sandbox(self):
        os.environ.update(
            {
                "SHOPIFY_ADMIN_TOKEN": "private",
                "GITHUB_TOKEN": "private",
                "OPENAI_API_KEY": "private",
                "NODE_OPTIONS": "private",
            }
        )
        response = self.reply(
            [
                {"type": "item.completed", "item": {"type": "agent_message", "text": "answer"}},
                {"type": "turn.completed"},
            ]
        )
        with (
            patch("harness2.substrate.codex_login.codex_binary", return_value="/bin/codex"),
            patch("harness2.substrate.codex_login.subprocess.run", return_value=response) as called,
        ):
            self.assertEqual(run_codex(self.root, "request", "model", "medium", 10).text, "answer")
            args, options = called.call_args
            self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", args[0])
            self.assertIn("workspace-write", args[0])
            self.assertIn('forced_login_method="chatgpt"', args[0])
            self.assertFalse(
                {"SHOPIFY_ADMIN_TOKEN", "GITHUB_TOKEN", "OPENAI_API_KEY", "NODE_OPTIONS"}
                & options["env"].keys()
            )
            self.assertEqual(options["input"], "request")
            os.environ["HARNESS2_CODEX_EXTERNAL_SANDBOX"] = "1"
            run_codex(self.root, "request", "model", "medium", 10)
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", called.call_args.args[0])

    def test_dedicated_home_rejects_personal_hooks_and_api_login(self):
        (self.home / "skills").mkdir()
        (self.home / "plugins").mkdir()
        self.assertEqual(login_environment()["CODEX_HOME"], str(self.home))
        (self.home / "hooks.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "personal"):
            login_environment()
        (self.home / "hooks.json").unlink()
        with (
            patch("harness2.substrate.codex_login.codex_binary", return_value="/bin/codex"),
            patch(
                "harness2.substrate.codex_login.subprocess.run",
                return_value=Mock(returncode=0, stdout="API key", stderr=""),
            ),
            self.assertRaisesRegex(ValueError, "ChatGPT"),
        ):
            check_login()

    def test_proposer_uses_the_new_transport_and_original_harvest(self):
        source = self.root / "source"
        (source / "harness").mkdir(parents=True)
        (source / "harness/AGENTS.md").write_text("original")

        def answer(cwd, prompt, model, effort, timeout):
            from harness2.substrate.codex_login import CodexResult

            (cwd / "context/harness/AGENTS.md").write_text("improved")
            return CodexResult("changed", "")

        channel = resolve_channel_model("codex_cli", "model", effort="medium")
        proposer = Proposer(channel, audit_dir=self.root / "audit", attempts=1)
        with patch("harness2.substrate.codex_login.run_codex", side_effect=answer):
            reply = proposer.call("improve", source, "inv1", harvest="context/harness")
            self.assertEqual((reply.workspace / "AGENTS.md").read_text(), "improved")
            cached = proposer.call("improve", source, "inv1", harvest="context/harness")
            self.assertTrue(cached.cached)
        self.assertEqual((source / "harness/AGENTS.md").read_text(), "original")

    def adapter(self, **overrides):
        return LocalCodexAdapter(
            SAMPLE / "tasks",
            SAMPLE / "harness",
            self.root / "output",
            **(
                {
                    "model": "model",
                    "effort": "medium",
                    "timeout": 10,
                    "work": "reconcile signed ledger entries",
                }
                | overrides
            ),
        )

    def test_adapter_keeps_original_ledger_inputs_and_rejects_stale_resume(self):
        adapter = self.adapter()
        self.assertEqual(adapter.tasks(), ["ledger-1", "ledger-2"])
        # Golden values come from the upstream DemoAdapter's exact fixtures.
        from harness2.demo import DemoAdapter

        upstream = DemoAdapter(self.root / "upstream")
        for task_id in adapter.tasks():
            self.assertEqual(
                (adapter.task_files(task_id) / "ledger.csv").read_text(),
                (upstream.task_files(task_id) / "ledger.csv").read_text(),
            )
        self.adapter()
        with self.assertRaisesRegex(ValueError, "changed"):
            self.adapter(model="other-model")
        with self.assertRaisesRegex(ValueError, "documents-only"):
            self.adapter(documents_only=True)

    def test_adapter_refuses_overwriting_an_unrelated_output_directory(self):
        output = self.root / "output"
        output.mkdir()
        existing = output / "unrelated.txt"
        existing.write_text("keep")
        with self.assertRaisesRegex(ValueError, "Output must be empty"):
            self.adapter()
        self.assertEqual(existing.read_text(), "keep")

    def test_improver_tuning_does_not_change_executor_and_invalidates_resume(self):
        adapter = self.adapter(improver_model="faster-model", improver_effort="low")
        self.assertEqual((adapter.model, adapter.effort), ("model", "medium"))
        channel = adapter.spec.channels["proposer"]
        self.assertEqual((channel.model, channel.effort), ("faster-model", "low"))
        with self.assertRaisesRegex(ValueError, "changed"):
            self.adapter()


if __name__ == "__main__":
    unittest.main()
