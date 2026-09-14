import json
import re
from pathlib import Path

from .inputs import validate_input
from .methods import MethodLibrary, check_mapping
from .planner import create_plan
from .schemas import ExecutionPlan, MethodSpec, PlanRequest, PreprocessInput, Ref
from .storage import Storage, digest


class PreprocessingService:
    def __init__(self, root, allowed_roots=(), llm=None, *, knowledge_snapshot=None):
        self.store = Storage(root)
        self.allowed_roots = [Path(p).resolve() for p in allowed_roots]
        self.methods = MethodLibrary(self.store, llm)
        from app.search.knowledge_registry import KnowledgeRegistry, verify_snapshot
        from app.search.scientific_space import knowledge
        self.frozen_knowledge = verify_snapshot(knowledge_snapshot) if knowledge_snapshot is not None else None
        self.knowledge_registry = None if self.frozen_knowledge else KnowledgeRegistry(self.store.root.parent/'knowledge-registry',knowledge())

    def knowledge(self, owner):
        from copy import deepcopy
        return deepcopy(self.frozen_knowledge) if self.frozen_knowledge else self.knowledge_registry.get(owner,require_current=True)

    def check_knowledge(self, owner, method):
        from app.search.knowledge_registry import method_issues
        problems=method_issues(method,self.knowledge(owner)['catalog'])
        if problems:
            raise ValueError('; '.join(p['message'] for p in problems))

    def register_input(self, owner, data: PreprocessInput):
        validate_input(data, self.allowed_roots, self.store.root)
        return self.store.put(owner, "input", data.model_dump(mode="json"))

    def _invasive_source(self, value: str) -> Path:
        path = Path(value).resolve(strict=True)
        if not any(path.is_relative_to(root) for root in self.allowed_roots):
            raise ValueError("NWB source is not in PREPROCESSING_INPUT_ROOTS")
        if path.is_relative_to(self.store.root) or self.store.root.is_relative_to(path):
            raise ValueError("input and output roots must be disjoint")
        return path

    def inspect_invasive(self, owner, request):
        from .invasive.nwb import inspect_nwb
        from .invasive.schemas import NWBInspectRequest

        request = NWBInspectRequest.model_validate(request)
        snapshot = inspect_nwb(
            self._invasive_source(request.path),
            hash_source=request.hash_source,
            max_scalar_reads=request.max_scalar_reads,
        )
        ref = self.store.put(owner, "invasive_snapshot", snapshot.model_dump(mode="json"))
        return ref, snapshot

    def plan_invasive(self, owner, request):
        from .invasive.planner import create_invasive_plan
        from .invasive.schemas import InvasivePlanRequest, NeuroDatasetSnapshot

        request = InvasivePlanRequest.model_validate(request)
        snapshot = NeuroDatasetSnapshot.model_validate(
            self.store.get(owner, request.snapshot_ref, "invasive_snapshot")
        )
        self._invasive_source(snapshot.source.path)
        for ref in [*request.literature_evidence_refs, *request.code_evidence_refs]:
            found = False
            for kind in ("evidence", "literature"):
                try:
                    self.store.get(owner, ref, kind)
                    found = True
                    break
                except KeyError:
                    pass
            if not found:
                raise KeyError("invasive method evidence resource not found")
        plan = create_invasive_plan(snapshot, request)
        ref = self.store.put(owner, "invasive_plan", plan.model_dump(mode="json"))
        return ref, plan

    def run_invasive(self, owner, request):
        from .invasive.executor import execute_invasive
        from .invasive.schemas import InvasiveExecutionPlan, InvasiveRunRequest, NeuroDatasetSnapshot

        request = InvasiveRunRequest.model_validate(request)
        plan = InvasiveExecutionPlan.model_validate(
            self.store.get(owner, request.plan_ref, "invasive_plan")
        )
        snapshot = NeuroDatasetSnapshot.model_validate(
            self.store.get(owner, plan.snapshot_ref, "invasive_snapshot")
        )
        self._invasive_source(snapshot.source.path)
        owner_key = digest({"owner": owner})[:20]
        output_key = request.plan_ref.id if request.output_name is None else f"{request.output_name}-{request.plan_ref.id}"
        output = self.store.root / "invasive" / owner_key / output_key
        result = {
            **execute_invasive(snapshot, plan, output),
            "plan_ref": request.plan_ref.model_dump(mode="json"),
            "snapshot_ref": plan.snapshot_ref.model_dump(mode="json"),
        }
        result_ref = self.store.put(owner, "invasive_result", result)
        return result_ref, result

    def invasive_result(self, owner, ref: Ref):
        return self.store.get(owner, ref, "invasive_result")

    def _invasive_result_refs(self, owner, result):
        plan_value = result.get("plan_ref")
        if plan_value is None:
            match = re.search(r"([a-f0-9]{64})$", Path(result["output_dir"]).name)
            if match:
                plan_value = {"id": match.group(1), "sha256": match.group(1)}
        plan_ref = Ref.model_validate(plan_value)
        plan = self.store.get(owner, plan_ref, "invasive_plan")
        snapshot_ref = Ref.model_validate(
            result.get("snapshot_ref") or plan["snapshot_ref"]
        )
        return plan_ref, plan, snapshot_ref

    def invasive_result_bundle(self, owner, ref: Ref):
        result = self.invasive_result(owner, ref)
        plan_ref, plan, snapshot_ref = self._invasive_result_refs(owner, result)
        snapshot = self.store.get(owner, snapshot_ref, "invasive_snapshot")
        output = Path(result["output_dir"]).resolve(strict=True)
        manifest_path = self.invasive_artifact(owner, ref, "manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        indexed = manifest.get("files", {})
        artifacts = []
        for path in sorted(item for item in output.iterdir() if item.is_file()):
            saved = indexed.get(path.name, {})
            artifacts.append(
                {
                    "name": path.name,
                    "bytes": saved.get("size_bytes", path.stat().st_size),
                    "sha256": saved.get("sha256"),
                }
            )
        return {
            "result_ref": ref.model_dump(mode="json"),
            "result": result,
            "plan_ref": plan_ref.model_dump(mode="json"),
            "plan": plan,
            "snapshot_ref": snapshot_ref.model_dump(mode="json"),
            "snapshot": snapshot,
            "artifacts": artifacts,
        }

    def list_invasive_results(self, owner):
        summaries = []
        for item in self.store.list_objects(owner, "invasive_result"):
            try:
                bundle = self.invasive_result_bundle(
                    owner, Ref.model_validate(item["ref"])
                )
            except (KeyError, ValueError, OSError):
                continue
            result, plan, snapshot = (
                bundle["result"],
                bundle["plan"],
                bundle["snapshot"],
            )
            summaries.append(
                {
                    "result_ref": bundle["result_ref"],
                    "status": result.get("status"),
                    "created_at": result.get("created_at"),
                    "dataset_id": snapshot.get("dataset_id"),
                    "session_id": snapshot.get("session_id"),
                    "subject_id": snapshot.get("subject_id"),
                    "modality": snapshot.get("modality"),
                    "task": plan.get("task"),
                    "strategy": plan.get("strategy"),
                    "final_shapes": result.get("final_shapes", {}),
                    "unit_retention_ratio": result.get("unit_retention_ratio"),
                }
            )
        return sorted(
            summaries,
            key=lambda item: (item.get("created_at") or "", item["result_ref"]["id"]),
            reverse=True,
        )

    def invasive_artifact(self, owner, ref: Ref, name: str) -> Path:
        from .storage import within

        result = self.invasive_result(owner, ref)
        output = Path(result["output_dir"]).resolve(strict=True)
        invasive_root = (self.store.root / "invasive").resolve()
        if not output.is_relative_to(invasive_root):
            raise ValueError("invasive result points outside the artifact root")
        path = within(output, name)
        if not path.is_file():
            raise KeyError("invasive artifact not found")
        return path

    def register_method(self, owner, method: MethodSpec):
        # Publication is exclusively backed by this service's validation receipts.
        if (
            method.status == "validated"
            or method.validation
            or method.validated_profiles
        ):
            raise ValueError("use validation receipts to publish a validated method")
        method.checks = sorted(set(method.checks + check_mapping(method)))
        for evidence in method.evidence:
            if evidence.artifact_ref:
                artifact = self.store.get(owner, evidence.artifact_ref, "evidence")
                if evidence.text not in str(artifact.get("content", "")):
                    raise ValueError(
                        "method evidence is absent from its source artifact"
                    )
        return self.store.put(owner, "method", method.model_dump(mode="json"))

    def plan(self, owner, request: PlanRequest):
        return create_plan(self.store, owner, request, self.allowed_roots,self.knowledge(owner))

    def register_bundle(self, owner, bundle):
        for paper in bundle.papers:
            for ref in [
                paper.pdf_ref,
                paper.fulltext_ref,
                *(e.artifact_ref for e in paper.evidence),
                *(r.code_ref for r in paper.repositories),
            ]:
                if ref:
                    self.store.get(owner, ref, "evidence")
        return self.store.put(owner, "literature", bundle.model_dump(mode="json"))

    def submit(self, owner, ref: Ref):
        plan = ExecutionPlan.model_validate(self.store.get(owner, ref, "plan"))
        if not plan.records:
            raise ValueError("no eligible methods in plan; resolve screening gaps")
        for method_ref in {r.method_ref.id:r.method_ref for r in plan.records}.values():
            self.check_knowledge(owner,MethodSpec.model_validate(self.store.get(owner,method_ref,'method')))
        validate_input(plan.input_snapshot, self.allowed_roots, self.store.root)
        return self.store.submit(owner, ref, plan)

    def control(self, owner, job_id, action):
        if action == 'retry':
            job = self.store.status(owner, job_id)
            plan = ExecutionPlan.model_validate(self.store.get(owner, job.plan_ref, 'plan'))
            for method_ref in {r.method_ref.id:r.method_ref for r in plan.records}.values():
                self.check_knowledge(owner, MethodSpec.model_validate(self.store.get(owner,method_ref,'method')))
        return self.store.control(owner, job_id, action)

    def publish(self, owner, method_ref: Ref, job_ids: list[str]):
        from .runner import verify_result

        method = MethodSpec.model_validate(self.store.get(owner, method_ref, "method"))
        self.check_knowledge(owner,method)
        if method.status != "draft" or method.checks or not job_ids:
            raise ValueError(
                "a complete draft and successful validation receipts are required"
            )
        receipts, profiles = [], []
        for job_id in job_ids:
            result = self.store.status(owner, job_id)
            plan = ExecutionPlan.model_validate(
                self.store.get(owner, result.plan_ref, "plan")
            )
            from .units import engine_hash, environment

            if plan.engine_sha256 != engine_hash() or plan.environment != environment():
                raise ValueError(
                    "validation receipt implementation/environment has changed"
                )
            records = [r for r in result.records if r["method_id"] == method_ref.id]
            if (
                plan.request.mode != "validation"
                or not records
                or len(records)
                != len(plan.input_snapshot.collection.selected_record_ids)
                or any(
                    r["status"] != "completed"
                    or not verify_result(self.store.root, r["result"])
                    for r in records
                )
            ):
                raise ValueError(
                    "method validation must cover the full representative selection and verified artifacts"
                )
            receipt = self.store.put(
                owner,
                "validation",
                {
                    "method_ref": method_ref.model_dump(),
                    "job_id": job_id,
                    "plan_ref": result.plan_ref.model_dump(),
                    "records": records,
                    "parameters": plan.request.parameters,
                },
            )
            receipts.append(receipt)
            profiles.append(digest(plan.request.parameters))
        method.status = "validated"
        method.validation, method.validated_profiles = receipts, sorted(set(profiles))
        return self.store.put(owner, "method", method.model_dump(mode="json"))
