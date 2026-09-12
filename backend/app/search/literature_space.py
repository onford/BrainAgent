"""Project registered, executable source branches into the shared experiment space."""

from copy import deepcopy

from app.preprocessing.planner import compile_steps, training_grid
from app.preprocessing.schemas import MethodSpec, ParameterSource
from app.preprocessing.storage import digest
from app.preprocessing.units import OPERATIONS
from .method_space import seed_entries
from .pipeline_space import _check_value
from .recipe_compiler import compile_recipe
from .scientific_space import build_space, input_context
from .space_contracts import ExplorationSpace, OperatorDefinition


def check_execution(method, data, output):
    """Same engine contracts and common output for every selected record."""
    from types import SimpleNamespace

    reasons = list(method.checks) + [i.message for i in method.issues if i.severity == "blocking"]
    if reasons:
        raise ValueError("; ".join(reasons))
    if any(s.implementation_version == '2' for s in method.recipe):
        from .graph_evaluation import check_method
        return check_method(method, data, output)
    for record in data.collection.records:
        if record.id not in data.collection.selected_record_ids:
            continue
        steps = compile_steps(method, record, data, {})
        grid = training_grid(SimpleNamespace(steps=steps, output=method.output), record)
        expected = tuple(n for n in record.channel_order if record.channels[n] == "eeg")
        if grid != (expected, output["sfreq"], (round(output["tmin"] * output["sfreq"]), round(output["tmax"] * output["sfreq"]))):
            raise ValueError(f"{record.id}: source method output differs from the shared channel/time/sample grid: {grid}")


def _operator(step, space, output, data=None):
    if step.implementation_version != "1":
        raise ValueError(f"{step.id}: operation profile/version {step.profile}/{step.implementation_version} is not exposed by this search compiler; source ports must not be discarded")
    schema = OPERATIONS.get((step.unit_id, step.op))
    if schema is None:
        raise ValueError(f"engine operation is not enabled: {step.unit_id}/{step.op}")
    params = deepcopy(step.params)
    for key, field in schema.model_fields.items():
        if key not in params and not field.is_required():
            params[key] = field.get_default(call_default_factory=True)
    # Reuse existing exact semantics, including their ordering and parameter priors.
    for op in space["operators"]:
        if (op["unit_id"], op["op"]) != (step.unit_id, step.op) or step.op == "detect_bad_channels":
            continue
        fixed = {k: output[v[8:]] if isinstance(v, str) and v.startswith("$output.") else v
                 for k, v in op["bindings"].items()}
        if set(params) != set(fixed) | set(op["domains"]):
            continue
        if any(params[k] != v and not (v == "$event_id" and data is not None and params[k] == data.survey.event_id)
               for k, v in fixed.items()):
            continue
        definition = OperatorDefinition.model_validate(op)
        try:
            for key, domain in definition.domains.items():
                _check_value(params[key], domain, key)
        except ValueError:
            continue
        return op["id"], {k: params[k] for k in op["domains"]}, params
    if step.op in {"epoch", "resample"}:
        raise ValueError(f"{step.id}: source {step.op} parameters conflict with the frozen output contract")
    # Additional engine-supported operations are exposed only when a valid method
    # uses them. Fixed source settings stay fixed unless a bounded domain exists.
    domains, fixed, defaults = {}, {}, {}
    properties = schema.model_json_schema().get("properties", {})
    for key, value in params.items():
        spec = properties.get(key, {})
        if type(value) in (int, float) and spec.get("minimum") is not None and spec.get("maximum") is not None:
            domains[key] = {"kind": "integer" if spec.get("type") == "integer" else "number",
                "minimum": spec["minimum"], "maximum": spec["maximum"], "unit": "engine parameter",
                "origin": "implementation", "rationale": "执行引擎参数合同中的闭区间约束。"}
            defaults[key] = value
        else:
            fixed[key] = value
    identity = "source-op-" + digest([step.unit_id, step.op, fixed, domains, defaults])[:16]
    if identity not in {o["id"] for o in space["operators"]}:
        space["operators"].append(dict(id=identity, title=step.unit_id + " / " + step.op,
            unit_id=step.unit_id, op=step.op,
            input_stage="epochs" if step.op == "baseline" else "either" if step.op in {"reference", "detrend", "eog_apply", "mark_channels"} else "continuous",
            output_stage="same", fit_scope="none", domains=domains, defaults=defaults, bindings=fixed,
            emit_mark=False, max_instances=4, requires=[], evidence_ids=[]))
    return identity, defaults, params


def shared_window_variant(method, data, output):
    """An explicit engineering branch, retaining the immutable source recipe."""
    if method.checks or any(i.severity == "blocking" for i in method.issues):
        return None
    if all(s.implementation_version=='2' for s in method.recipe):
        by_id={s.id:s for s in method.recipe};cursor=method.output;epoch=None
        while cursor!='raw':
            step=by_id[cursor]
            if step.op in ('epoch','epoch_with_nonfinite'):epoch=step;break
            cursor=step.input
        if epoch and all(type(epoch.params.get(k)) in (int,float) for k in ('tmin','tmax')):
            original={k:epoch.params[k] for k in ('tmin','tmax')}
            requested={k:output[k] for k in original}
            if original!=requested and original['tmin']<=requested['tmin']<requested['tmax']<=original['tmax']:
                from app.preprocessing.schemas import EvaluationWindow
                variant=method.model_copy(deep=True)
                variant.evaluation_window=EvaluationWindow(**requested)
                if (epoch.id == method.output and epoch.unit_id == 'EEG-EPOCH' and epoch.op == 'epoch'
                    and not epoch.parameter_inputs and not epoch.artifact_inputs and not epoch.asset_inputs):
                    score = epoch.model_copy(deep=True)
                    score.id = 'scoring_epoch_' + digest([method.output, requested])[:12]
                    if score.id in by_id:
                        raise ValueError('scoring epoch node collision')
                    for key, value in requested.items():
                        score.params[key] = value
                        score.parameter_sources[key] = ParameterSource(origin='target_binding', evidence_indices=[],
                            rationale='Frozen scoring window on the same processed continuous signal; original epoch is retained.')
                    variant.recipe.append(score)
                    variant.output = score.id
                    variant.evaluation_window = EvaluationWindow(**requested,
                        policy='parallel-final-epoch-scoring-v1', source_output=method.output)
                variant.title+=' · 保留源上下文的评分窗口'
                variant.lineage.update(fidelity='engineering_adaptation',branch_id=method.lineage.get('branch_id',method.id)+'-scoring-window',
                    original_method_hash=digest(method.model_dump(mode='json')),adaptation={'policy':variant.evaluation_window.policy,
                    'original':original,'replacement':requested,'preserved':'all source operations, fit scopes, screening and baseline windows'})
                variant.adaptations.append('源窗口与全部基线/拟合依赖原样执行，另存工程评分输出；并行末端分段只允许恢复因记录边界缺少上下文的事件，禁止绕过坏段或其他筛除。')
                return variant
    if not method.recipe or method.recipe[-1].op != "epoch" or method.output != method.recipe[-1].id:
        return None
    epoch = method.recipe[-1]
    if any(type(epoch.params.get(k)) not in (int, float) for k in ("tmin", "tmax")):
        return None
    original = {k: epoch.params[k] for k in ("tmin", "tmax")}
    replacement = {k: output[k] for k in original}
    if original == replacement:
        return None
    # No unknown parameters, missing operations, channel changes or sample-rate
    # incompatibilities may be cured by a time-window adaptation.
    from types import SimpleNamespace
    for record in data.collection.records:
        if record.id not in data.collection.selected_record_ids:
            continue
        steps = compile_steps(method, record, data, {})
        grid = training_grid(SimpleNamespace(steps=steps, output=method.output), record)
        expected = tuple(n for n in record.channel_order if record.channels[n] == "eeg")
        if grid[0] != expected or (any(s.op == "resample" for s in method.recipe) and grid[1] != output["sfreq"]):
            return None
    variant = method.model_copy(deep=True)
    variant.title += " · 共同时间窗工程适配"
    variant.lineage.update(fidelity="engineering_adaptation", original_branch_id=method.lineage.get("branch_id"),
        branch_id=method.lineage.get("branch_id", method.id) + "-shared-window",
        original_method_hash=digest(method.model_dump(mode="json")),
        adaptation={"policy": "shared-final-epoch-window-v1", "original": original, "replacement": replacement,
                    "scope": "final epoch only; preserve all required source operations and event/channel identities"})
    variant.adaptations.append(f"显式工程适配：将源最终分段窗 {original} 改为冻结比较窗 {replacement}；不能称为论文窗口或忠实复现。")
    for key, value in replacement.items():
        variant.recipe[-1].params[key] = value
        variant.recipe[-1].parameter_sources[key] = ParameterSource(origin="target_binding", evidence_indices=[],
            rationale=f"Frozen common evaluation window; original source-branch value {original[key]} is retained in lineage, not used as the adapted parameter. Consult the original method for its evidence origin.")
    return variant


def build_workflow_space(data, output, methods=(), absence_reasons=()):
    context = input_context(data)
    base = build_space(context).model_dump(mode="json")
    base["semantic_identity"] = "operation_contracts_v1"
    # Retain explicit project controls only. Curated literature presets are not
    # discoveries of this workflow and must not seed the production candidate pool.
    base["methods"] = [s for s in base["methods"] if s["origin"] == "basic"]
    for seed in base["methods"]:
        seed["lineage"] = [{"kind": "basic", "method_id": seed["id"], "version": "1",
                            "basis": "standard project control, not current research", "prior_origin": seed["origin"]}]
        seed["origin"] = "basic"
    report = {"methods": [], "absence_reasons": list(absence_reasons)}
    expanded_methods = []
    for ref, method in methods:
        expanded_methods.append((ref, method))
        try:
            variant = shared_window_variant(method, data, output)
        except (ValueError, KeyError):
            variant = None  # The original branch's full compiler error is retained below.
        if variant is not None:
            expanded_methods.append((ref, variant))
    for ref, method in expanded_methods:
        row = {"method_ref": ref, "title": method.title, "lineage": method.lineage,
               "issues": [i.model_dump(mode="json") for i in method.issues], "adaptations": method.adaptations,
               "status": "blocked", "reasons": []}
        report["methods"].append(row)
        try:
            blockers = method.checks + [i.message for i in method.issues if i.severity == "blocking"]
            if blockers:
                raise ValueError("; ".join(blockers))
            if any(s.implementation_version == '2' for s in method.recipe):
                from .graph_recipe import graph_seed
                value, identity = graph_seed(method, ref, base, output)
                space = ExplorationSpace.model_validate(value)
                entry = next(e for e in seed_entries(space, context)
                    if any(t.get('method_ref') == ref and t.get('branch_id') == method.lineage.get('branch_id')
                           for t in e['lineage']))
                compiled = compile_recipe(entry, space, {'output_contract': output}, context)
                check_execution(compiled, data, output)
                row.update(status='eligible',candidate_id=entry['id'],compiled_method=compiled.model_dump(mode='json'))
                base=value
                continue
            if method.output != next(s.id for s in reversed(method.recipe) if s.op != "eog_fit"):
                raise ValueError("source output is not the final data step; cannot discard source branches during compilation")
            if any(s.op == "asr_clean" for s in method.recipe) and not context["asr_dependency"]:
                raise ValueError("ASRpy 0.0.8 dependency unavailable")
            value = deepcopy(base)
            evidence_ids = []
            for i, evidence in enumerate(method.evidence):
                key = "source-" + digest(evidence.model_dump(mode="json"))[:24]
                value["evidence"][key] = evidence.model_dump(mode="json")
                evidence_ids.append(key)
            nodes, adaptations, previous = [], list(method.adaptations), "raw"
            has_resample = any(s.op == "resample" for s in method.recipe)
            for step in method.recipe:
                if step.op == "epoch" and not has_resample:
                    nodes.append(dict(id="shared_resample", operator="resample", optional=False))
                    adaptations.append("在源分段前增加共同输出重采样；保留事件身份，目标采样率来自冻结评价合同。")
                    has_resample = True
                op, params, expanded = _operator(step, value, output, data)
                if step.op == "epoch":
                    # epoch operator binds those exact source values to the shared grid.
                    params = {}
                trace = {"method_ref": ref, "branch_id": method.lineage.get("branch_id"), "step_id": step.id,
                    "evidence_ids": [evidence_ids[i] for i in step.evidence_indices], "parameters": expanded,
                    "parameter_sources": {k: {"origin": p.origin, "rationale": p.rationale,
                        "evidence_ids": [evidence_ids[i] for i in p.evidence_indices]}
                        for k, p in step.parameter_sources.items()}}
                for key in expanded.keys() - step.params.keys():
                    trace["parameter_sources"][key] = {"origin": "engineering", "evidence_ids": [],
                        "rationale": "Default from the enabled operation contract; not a published parameter."}
                # Linear inputs remain relative to order; non-linear ports stay explicit.
                node = dict(id=step.id, operator=op, parameters=params, optional=step.optional, trace=[trace],
                    input_from=step.input if step.input != previous else None,
                    model_from=step.model_from, decision_from=step.decision_from,
                    fit_scope=step.fit_scope.model_dump() if step.fit_scope else None)
                nodes.append(node)
                if step.op != "eog_fit":
                    previous = step.id
            if not any(s.op == "epoch" for s in method.recipe):
                if not has_resample:
                    nodes.append(dict(id="shared_resample", operator="resample", optional=False))
                nodes.append(dict(id="shared_epoch", operator="epoch", optional=False))
                adaptations.append("源方法输出连续信号；附加公共采样网格和分段适配器以参加同一评价。")
            adapted = method.lineage.get("fidelity") == "engineering_adaptation"
            identity = "paper-" + (digest([ref, method.lineage]) if adapted else ref["id"])[:24]
            seed = dict(id=identity, title=method.title, origin="literature_adaptation" if adapted else "literature", recipe={"nodes": nodes},
                evidence_ids=list(dict.fromkeys(evidence_ids)), deviations=adaptations,
                lineage=[{**method.lineage, "method_ref": ref, "method_id": method.id, "version": method.version}],
                issues=[i.model_dump(mode="json") for i in method.issues])
            value["methods"].append(seed)
            space = ExplorationSpace.model_validate(value)
            entry = next(e for e in seed_entries(space, context)
                         if any(t.get("method_ref") == ref and t.get("branch_id") == method.lineage.get("branch_id") for t in e["lineage"]))
            compiled = compile_recipe(entry, space, {"output_contract": output}, context)
            check_execution(compiled, data, output)
            row.update(status="eligible", candidate_id=entry["id"], compiled_method=compiled.model_dump(mode="json"))
            base = value
        except (ValueError, KeyError, ImportError) as exc:
            row["reasons"].append(str(exc))
    if not any(r["status"] == "eligible" for r in report["methods"]):
        report["absence_reasons"].append("本轮没有通过共同执行合同检查的文献方法；逐方法阻塞原因已保留。")
    return ExplorationSpace.model_validate(base), context, report
