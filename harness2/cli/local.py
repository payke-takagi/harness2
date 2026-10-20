"""Run Google's published Harness² workflow on local tasks using ChatGPT-authenticated Codex."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..core import schedule
from ..core.proposer import Proposer
from ..local import LocalCodexAdapter
from ..substrate.codex_login import check_login


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--harness", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", default="medium", choices=("low", "medium", "high"))
    parser.add_argument(
        "--improver-model", help="proposal/selection/reflection model; defaults to --model"
    )
    parser.add_argument(
        "--improver-effort", choices=("low", "medium", "high"), help="defaults to --effort"
    )
    parser.add_argument("--work", required=True)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--k", type=int, default=1)
    parser.add_argument("--mode", choices=("parallel", "sequential", "both"), default="parallel")
    parser.add_argument("--documents-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.k < 1 or args.timeout < 1:
        parser.error("--k and --timeout must be positive")
    # No agent or model service is called by dry-run.
    if args.dry_run:
        task_ids = sorted(path.parent.name for path in args.tasks.glob("*/task.md"))
        modes = 2 if args.mode == "both" else 1
        print(
            json.dumps(
                {
                    "tasks": task_ids,
                    "k": args.k,
                    "mode": args.mode,
                    "reference_rollouts_per_task": args.k,
                    "candidate_rollouts_per_task": 3 * args.k * modes,
                    "improvement_sessions_per_task": 3 * args.k * modes,
                    "note": "selection/reflection and retries add calls; this is not a spending cap",
                },
                indent=2,
            )
        )
        return 0
    check_login()
    adapter = LocalCodexAdapter(
        args.tasks.resolve(),
        args.harness.resolve(),
        args.output,
        model=args.model,
        effort=args.effort,
        timeout=args.timeout,
        work=args.work,
        documents_only=args.documents_only,
        improver_model=args.improver_model,
        improver_effort=args.improver_effort,
    )
    proposer = Proposer(
        adapter.spec.channels["proposer"], audit_dir=adapter.root / "audit", attempts=1
    )
    modes = ("agg", "seq") if args.mode == "both" else (schedule.mode_token(args.mode),)
    result = schedule.run_sweep(
        args.k,
        adapter=adapter,
        prop=proposer,
        runs_root=adapter.spec.runs_root,
        library_root=adapter.root / "library" / f"k{args.k}",
        modes=modes,
    )
    result["improver_calls_this_invocation"] = len(proposer._calls)
    result["api_cost_usd"] = None  # Codex token/subscription usage is not an API dollar bill.
    (adapter.root / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    failed = sum(domain.get("failed", 0) for domain in result["domains"])
    failed += sum("error" in domain for domain in result["domains"])
    print(
        f"Local Codex workflow: {len(adapter.tasks())} tasks; {failed} failed. {adapter.root / 'result.json'}"
    )
    return int(failed > 0)


if __name__ == "__main__":
    raise SystemExit(main())
