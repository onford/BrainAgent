"""Submit budgeted searches through the local application API."""

import argparse
import json
import time

import httpx

from .contracts import SearchBudget, SearchRequest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow")
    parser.add_argument("--resume", help="Resume without resetting budget")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--owner", default="local-development-user")
    parser.add_argument(
        "--strategy",
        choices=("adaptive", "one_shot", "random", "exhaustive"),
        default="adaptive",
    )
    parser.add_argument("--max-candidates", type=int, default=6)
    parser.add_argument("--max-proposals", type=int, default=8)
    parser.add_argument("--max-evidence-reads", type=int, default=2)
    parser.add_argument("--max-seconds", type=float, default=3600)
    parser.add_argument("--max-memory-mb", type=int)
    parser.add_argument("--max-disk-mb", type=int)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-subjects", nargs="*", default=[])
    parser.add_argument("--development-subjects", nargs="*", default=[])
    parser.add_argument("--no-wait", action="store_true")
    args = parser.parse_args()
    if bool(args.workflow) == bool(args.resume):
        parser.error("provide exactly one of --workflow or --resume")
    with httpx.Client(
        base_url=args.api,
        timeout=60,
        trust_env=False,
        headers={"X-Brain-Agent-Owner-ID": args.owner},
    ) as client:
        if args.resume:
            response = client.post(f"/api/searches/{args.resume}/retry")
        else:
            request = SearchRequest(
                workflow_id=args.workflow,
                strategy=args.strategy,
                seed=args.seed,
                train_subjects=args.train_subjects,
                development_subjects=args.development_subjects,
                budget=SearchBudget(
                    max_candidates=args.max_candidates,
                    max_proposals=args.max_proposals,
                    max_evidence_reads=args.max_evidence_reads,
                    max_seconds=args.max_seconds,
                    max_memory_mb=args.max_memory_mb,
                    max_disk_mb=args.max_disk_mb,
                ),
            )
            response = client.post(
                "/api/searches", json=request.model_dump(mode="json")
            )
        response.raise_for_status()
        state = response.json()
        print("search", state["id"], flush=True)
        if args.no_wait:
            return
        last = None
        while state["status"] in {"preparing", "running", "interrupted"}:
            progress = (
                state["status"],
                state["message"],
                state["usage"]["candidates"],
                state["usage"]["proposals"],
            )
            if progress != last:
                print(*progress, flush=True)
                last = progress
            time.sleep(2)
            response = client.get(f"/api/searches/{state['id']}")
            response.raise_for_status()
            state = response.json()
        print(
            json.dumps(
                {
                    k: state[k]
                    for k in (
                        "id",
                        "status",
                        "selected_candidate_id",
                        "stop_reason",
                        "usage",
                        "error",
                    )
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        if state["status"] in {"failed", "cancelled"}:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
