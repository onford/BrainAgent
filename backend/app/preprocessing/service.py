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
