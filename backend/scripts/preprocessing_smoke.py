"""Create a complete synthetic BIDS acceptance run, without using private EEG.

Run from backend: python scripts/preprocessing_smoke.py --root workspace/eeg-smoke
Requires the dev and eeg extras. The output root must not already exist.
"""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.preprocessing.schemas import PlanRequest
from app.preprocessing.service import PreprocessingService
from app.preprocessing.storage import write_json
from app.preprocessing.worker import Worker
from tests.preprocessing.conftest import make_dataset, PARAMETERS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("workspace/eeg-smoke"))
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    data = make_dataset(root / "bids")
    service = PreprocessingService(root / "output", [root / "bids"])
    owner = "smoke-fixture"
    input_ref = service.register_input(owner, data)
    methods = service.methods.seed(owner)
    request = PlanRequest(
        input_ref=input_ref, methods=methods, mode="validation", parameters=PARAMETERS
    )
    plan_ref, plan = service.plan(owner, request)
    job = service.submit(owner, plan_ref)
    result = Worker(service.store, service.allowed_roots).run_once()
    if result.status != "completed":
        raise RuntimeError(result.model_dump_json())
    published = [service.publish(owner, method, [job.job_id]) for method in methods]
    write_json(root / "input.json", data.model_dump(mode="json"))
    write_json(root / "plan-request.json", request.model_dump(mode="json"))
    write_json(root / "plan.json", plan.model_dump(mode="json"))
    write_json(root / "result.json", result.model_dump(mode="json"))
    write_json(
        root / "acceptance.json",
        {
            "status": result.status,
            "completed": result.completed,
            "total": result.total,
            "published_methods": [r.model_dump() for r in published],
            "environment": plan.environment,
            "engine_sha256": plan.engine_sha256,
            "purpose": "synthetic development fixture; not scientific method ranking",
        },
    )
    print(
        f"{result.status}: {result.completed}/{result.total}; acceptance record: {root / 'acceptance.json'}"
    )


if __name__ == "__main__":
    main()
