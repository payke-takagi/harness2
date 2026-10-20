# Codex-login verification — 2026-10-20

## Verified

- Upstream starting point: `google-research/harness2@1cfe254`.
- Python 3.12: all 12 unittest cases passed (5 unchanged upstream cases and
  7 added transport/input-protection cases). Ruff checks passed.
- The published recursion, prompts, selection, library, ledger and schedule
  files are unchanged relative to that upstream commit.
- Built `Dockerfile.codex-login`, pinned to Codex 0.160.0.
- Ran the real model-backed local-task batch in an isolated Docker environment
  with ChatGPT authentication, `gpt-6.1-sol`, medium effort, parallel mode, k=1.
  No Vertex configuration or API-key provider was used. The live run used the
  existing Peco test image with Codex 0.160.0; the standalone image was built
  and then used for the offline resume check.
- Both tasks completed successfully in 416 seconds, including proposal,
  probing, composition and reflection. The successful invocation contained
  8 executor calls and 8 proposal/reflection calls.

The successful proposal/composition sessions took 40.9–54.3 seconds each;
reflection took 47.3 and 52.0 seconds. The two proposal directions already ran
in parallel under the upstream driver. These measurements do not yet support
a claim that refinement is fast enough for every live Peco response. Retaining
the published method is the baseline; synchronous versus separate-batch Peco
integration remains undecided, conditional on measured latency and usefulness.

| Task | Initial answer | Adopted answer | Signed sum of upstream input |
|---|---|---|---|
| ledger-1 | 105.25 | 85.15 | 85.15 |
| ledger-2 | 35.50 | 20.25 | 20.25 |

Expected values and input files come from the original DemoAdapter. We checked
the final answers against Decimal sums of those same CSV files, outside the
improvement loop. The input harness was mounted read-only and was not changed.

Re-running the batch in the standalone image with `--network none` skipped both
completed tasks. It made zero proposal calls and left all executor/audit file
hashes and modification times unchanged. The explicit external-sandbox setting
of the live invocation was recorded in its input manifest before this resume
check, after that field was added to the resume identity.

## Limits

- At k=1 there is only one composed final, so upstream makes a trivial selection
  without an additional selector model call. Model-backed k>1 selection and
  sequential mode were not exercised here; upstream deterministic tests cover
  their workflow contracts.
- Reflection ran on both tasks but returned no transferable experience entry.
  No experience-library entries were stored, as required by the upstream
  evidence gate. This run demonstrates better task outputs, not proven
  cross-task learning. The original upstream tests exercise library carryover.
- This is an integration example, not a measurement of Peco's shipping accuracy.
  Production Slack/MCP connections, business-data replay, scheduling, candidate
  adoption and deployment have not been implemented or verified.
- The batch may be run separately from live Peco replies. No decision to put
  refinement in every normal Slack request has been made.
- Runtime logs and credentials are excluded from Git. Authentication was
  provided only to the disposable runtime, not baked into an image.
