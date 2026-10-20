# ChatGPT-authenticated Codex in this fork

This fork starts at Google's `1cfe254e8d25b15f37048c3730134686abe60335`.
It adds a ChatGPT-login transport and a local-task adapter. It does not import
the third-party `harness2-cli` implementation.

The published recursion, prompts, candidate selection, experience library,
ledger, and resume driver remain Google's implementation. The new adapter
implements `BenchmarkAdapter`, the upstream extension interface. Changes in
existing method files add the `codex_cli` model channel and dispatch calls to it.
The three benchmark setups and their external judges remain API-based.

The public entry points are batch drivers over a task stream. Each task's
execution/refinement happens inside that batch. This does not require attaching
the improvement loop to a live Slack response: recorded tasks may be replayed
in a separate batch, with adopted changes reviewed before deployment.

## Authentication and execution

`harness2-local` runs task execution, both proposal directions, composition,
selection (when k > 1), and experience reflection through the installed Codex
CLI. Use a bare model ID such as `gpt-6.1-sol`. This path needs no Vertex setup,
Responses bridge, or API key.

`--model` and `--effort` select the task executor. Optional `--improver-model`
and `--improver-effort` independently select the proposal/composition,
selection, and reflection sessions; both default to the executor settings.
For example, `--effort medium --improver-effort low` changes only the improvement
side. This does not reduce the published number of method steps. Measure
correctness and elapsed time on the same tasks before adopting a faster setting.

Provide a dedicated `CODEX_HOME` signed in using `codex login`. Do not use a
personal home containing AGENTS.md or hooks.json. `--ignore-user-config`,
`--ignore-rules`, and forced ChatGPT authentication exclude personal provider
configuration. A narrowly allowed environment excludes arbitrary Shopify,
GitHub, and R2 tokens. This does not protect files/process state from another
unrestricted process in the same container.

Codex defaults to `workspace-write`. Set `HARNESS2_CODEX_EXTERNAL_SANDBOX=1`
only inside an independently isolated container or Cloudflare Sandbox. This
explicitly opts into Codex's unsandboxed automation mode, leaving the outer
container boundary intact. Do not use this opt-in on a host machine.
The local adapter rejects model-authored hooks and subagents.

## Local tasks

Use a dedicated harness directory with `AGENTS.md` and optionally
`.agents/skills/<name>/SKILL.md` and `scripts/*.py`. Unsupported files are
rejected, not silently dropped. Skill `references/` files are not yet supported
by the upstream editable-file schema.

Each task lives at `<tasks>/<task-id>/task.md`. Optional input files go into
`files/`. `task.toml` may contain `domain = "shipping"`. IDs and domains use
lowercase ASCII letters, digits, `_`, and `-`. The agent and improver both see
`files/`: do not place grading answers there. Sources may not contain agent
configuration (AGENTS.md, .agents, .codex, or .git) at their root.

```sh
harness2-local --tasks /inputs/tasks --harness /inputs/harness \
  --output /outputs/run-1 --model gpt-6.1-sol --effort medium \
  --work 'answer operational questions from supplied source material' \
  --documents-only --k 1 --mode parallel --dry-run
```

Remove `--dry-run` to call the model. `--documents-only` restricts accepted
changes to AGENTS.md and skill entrypoints; it is not an OS sandbox.
This adapter does not yet connect production Slack, Shopify, R2, or Peco's MCP
tools. That deployment integration is separate work.

The source harness is snapshotted and never overwritten. Adopted candidates,
evidence, and `EXPERIENCE.md` live under `--output`. There is no automatic apply,
Git push, PR creation, merge, or deployment. The output directory is mode 0700
and contains potentially sensitive model inputs/outputs. Use a new output
directory if inputs or settings change. The same command resumes completed
tasks using Google's driver.

`--dry-run` calls no model and writes nothing. Counts cover the published
reference/propose/probe/compose steps, not a hard budget: selection, reflection,
and retries add calls. Subscription usage is not an API dollar bill;
`api_cost_usd` is null in the local result.

## Container and verification example

Build with `docker build -f Dockerfile.codex-login -t harness2-codex-login .`.
Codex is pinned to 0.160.0, matching the Peco version inspected for this change.
Supply the dedicated login and input/output mounts at runtime. Never bake
authentication into the image. Limit network access and credential scope for
the task, and do not share a container with live production jobs/credentials
when running an unreviewed candidate harness.

`examples/local-ledger` uses the exact two ledgers and initial helper defect
from upstream DemoAdapter. Signed totals are 85.15 and 20.25; the positive-only
baseline returns 105.25 and 35.50. These values come from upstream fixtures,
not an invented business rule. This example checks the complete method and
transport path; it does not establish Peco's shipping accuracy or production
readiness.
