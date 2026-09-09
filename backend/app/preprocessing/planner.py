from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import csv

from .inputs import validate_input, working_files
from .resources import budget, require_capacity
from .schemas import (
    ExecutionPlan,
    MethodSpec,
    PlanRequest,
    PreprocessInput,
    RecordPlan,
    Screening,
    Ref,
)
from .storage import Storage, digest
from .units import environment, engine_hash, specification, validate_params


def bind(value, bindings):
    if isinstance(value, str) and value.startswith("$") and value != "$events":
        key = value[1:]
        if key not in bindings:
            raise ValueError(f"missing parameter/fact: {key}")
        return deepcopy(bindings[key])
    if isinstance(value, list):
        return [bind(v, bindings) for v in value]
    if isinstance(value, dict):
        return {k: bind(v, bindings) for k, v in value.items()}
    return value


def compile_steps(method: MethodSpec, record, data, parameters):
    bindings = {"profile." + k: v for k, v in parameters.items()}
    bindings.update(
        eeg_channels=[n for n in record.channel_order if record.channels[n] == "eeg"],
        eog_channels=[n for n in record.channel_order if record.channels[n] == "eog"],
        all_channels=record.channel_order,
        event_id=data.survey.event_id,
    )
    nodes = {"raw": "raw"}
    steps = []
    channel_sets = {"raw": set(record.channels)}
    reference_nodes = {"raw": record.reference}
    sample_rates = {"raw": record.sfreq}
    for original in method.recipe:
        step = original.model_copy(deep=True)
        if step.id in nodes or step.input not in nodes:
            raise ValueError(
                "step names/dependencies must be unique and topologically ordered"
            )
        if any(i < 0 or i >= len(method.evidence) for i in step.evidence_indices):
            raise ValueError("step lacks resolvable evidence")
        kind = nodes[step.input]
        if kind == "fit_model":
            raise ValueError(
                "fit output is a model port; use model_from and the original data branch"
            )
        channels = channel_sets[step.input].copy()
        reference = reference_nodes[step.input]
        sfreq = sample_rates[step.input]
        step.params = validate_params(
            step.unit_id, step.op, bind(step.params, bindings)
        )
        p = step.params
        picks = p.get("picks", [])
        if len(picks) != len(set(picks)) or not set(picks) <= channels:
            raise ValueError("invalid or duplicate channel picks")
        if step.unit_id in ("EEG-DETREND", "EEG-FILTER") and any(
            record.channels[n] != "eeg" for n in picks
        ):
            raise ValueError("enabled operation requires EEG picks")
        if step.op == "filter":
            lo, hi = p["l_freq"], p["h_freq"]
            if (
                lo is None
                and hi is None
                or any(v is not None and not 0 < v < sfreq / 2 for v in (lo, hi))
                or lo is not None
                and hi is not None
                and lo >= hi
            ):
                raise ValueError("filter bounds violate sampling rate")
        if step.op == "reference":
            donors = p["ref_channels"]
            if donors != "average" and (
                not donors
                or len(set(donors)) != len(donors)
                or not set(donors) <= channels
                or any(record.channels[n] != "eeg" for n in donors)
            ):
                raise ValueError("invalid reference donors")
            reference = (
                "average" if donors == "average" else "channels:" + ",".join(donors)
            )
        if (
            step.op in ("epoch", "eog_fit", "amplitude_windows", "filter", "resample")
            and kind != "raw"
        ):
            raise ValueError(f"{step.op} requires continuous input in this release")
        if step.op == "resample":
            sfreq = p["sfreq"]
        if step.op == "epoch":
            if (
                not p["event_id"]
                or p["event_id"] != data.survey.event_id
                or p["tmin"] >= p["tmax"]
            ):
                raise ValueError("epoch events/window not defined by Survey")
            kind = "epochs"
            channels = set(picks)
        if step.op == "baseline":
            if kind != "epochs":
                raise ValueError("baseline requires Epochs")
        if step.op == "eog_fit":
            if not step.fit_scope or len(set(step.fit_scope.ids)) != len(
                step.fit_scope.ids
            ):
                raise ValueError(
                    "fitting requires unique actual calibration/train interval IDs"
                )
            partitions = {i.id: i for i in record.intervals}
            if any(
                i not in partitions or partitions[i].role != step.fit_scope.role
                for i in step.fit_scope.ids
            ):
                raise ValueError(
                    "fit scope includes unknown, test or incompatible partitions"
                )
            # Single contiguous interval avoids accidentally fitting across joins.
            if len(step.fit_scope.ids) != 1:
                raise ValueError("first release fits exactly one contiguous interval")
            if (
                any(record.channels[n] != "eeg" for n in picks)
                or not set(p["picks_artifact"]) <= channels
                or any(record.channels[n] != "eog" for n in p["picks_artifact"])
            ):
                raise ValueError("EOG regression requires real auxiliary EOG channels")
            if p["reference_id"] != reference:
                raise ValueError("fit reference_id differs from input reference state")
            predecessor = step.input
            while predecessor != "raw":
                ancestor = next(s for s in steps if s.id == predecessor)
                if ancestor.op not in ("filter", "reference", "detrend"):
                    raise ValueError(
                        "fit ancestors must be independent filter/reference/detrend operations"
                    )
                predecessor = ancestor.input
            kind = "fit_model"
        elif step.fit_scope is not None:
            raise ValueError("fit_scope is only valid on fitting operations")
        if step.op == "eog_apply":
            fit = next((s for s in steps if s.id == step.model_from), None)
            if (
                not fit
                or fit.op != "eog_fit"
                or p["reference_id"] != reference
                or fit.params["reference_id"] != reference
            ):
                raise ValueError("application requires compatible earlier EOG model")
        elif step.model_from:
            raise ValueError("unexpected model input")
        if step.op == "mark_channels":
            detection = next((s for s in steps if s.id == step.decision_from), None)
            if (
                not detection
                or detection.op != "amplitude_windows"
                or step.input != detection.input
            ):
                raise ValueError(
                    "marking requires a detection bound to the exact input"
                )
        elif step.decision_from:
            raise ValueError("unexpected decision input")
        nodes[step.id], channel_sets[step.id], reference_nodes[step.id] = (
            kind,
            channels,
            reference,
        )
        sample_rates[step.id] = sfreq
        steps.append(step)
    if (
        method.output not in nodes
        or method.output == "raw"
        or nodes[method.output] == "fit_model"
    ):
        raise ValueError("method output must name an executed step")
    return steps


def numerical_signature(configs):
    normalized = []
    for config in configs:
        names = {"raw": "raw", **{s.id: f"s{i}" for i, s in enumerate(config.steps)}}
        steps = []
        for step in config.steps:
            row = step.model_dump(exclude={"evidence_indices"})
            for field in ("id", "input", "model_from", "decision_from"):
                if row[field] is not None:
                    row[field] = names[row[field]]
            steps.append(row)
        normalized.append(
            {
                "record": config.record_id,
                "steps": steps,
                "output": names[config.output],
                "code_hashes": config.code_hashes,
            }
        )
    return digest(normalized)


def signal_bytes(record, steps, root):
    size = len(record.channels) * record.samples * 8
    rates = {"raw": record.sfreq}
    for step in steps:
        sfreq = step.params["sfreq"] if step.op == "resample" else rates[step.input]
        rates[step.id] = sfreq
        size = max(
            size,
            len(record.channels)
            * int(round(record.samples * sfreq / record.sfreq))
            * 8,
        )
        if step.op == "epoch":
            path = Path(root) / record.bids_path.replace("eeg.vhdr", "events.tsv")
            with path.open(encoding="utf-8-sig", newline="") as stream:
                events = sum(1 for _ in csv.DictReader(stream, delimiter="\t"))
            samples = (
                int(round((step.params["tmax"] - step.params["tmin"]) * sfreq)) + 1
            )
            size = max(size, events * len(step.params["picks"]) * samples * 8)
    return size


def training_grid(config, record):
    """Infer channel order and time grid through the compiled data branches."""
    nodes = {"raw": (tuple(record.channel_order), record.sfreq, None)}
    for step in config.steps:
        channels, sfreq, window = nodes[step.input]
        if step.op == "resample":
            sfreq = step.params["sfreq"]
        elif step.op == "epoch":
            channels = tuple(step.params["picks"])
            window = (
                round(step.params["tmin"] * sfreq),
                round(step.params["tmax"] * sfreq),
            )
        nodes[step.id] = channels, sfreq, window
    return nodes[config.output]


def create_plan(
    store: Storage, owner: str, request: PlanRequest, allowed_roots: list[Path]
):
    data = PreprocessInput.model_validate(store.get(owner, request.input_ref, "input"))
    validate_input(data, allowed_roots, store.root)
    env = environment()
    if request.mode == "production" and data.purpose != "production":
        raise ValueError("fixture input cannot be submitted as production")
    if request.mode == "validation" and data.purpose != "development_fixture":
        raise ValueError(
            "validation uses explicitly identified representative fixtures"
        )
    screening, candidates = [], []
    selected_records = [
        r
        for r in data.collection.records
        if r.id in data.collection.selected_record_ids
    ]
    for ref in request.methods:
        method = MethodSpec.model_validate(store.get(owner, ref, "method"))
        try:
            if method.status == "retired" or method.checks:
                raise ValueError(
                    "retired method or unresolved checks: " + "; ".join(method.checks)
                )
            if request.mode == "production" and (
                method.status != "validated"
                or digest(request.parameters) not in method.validated_profiles
            ):
                raise ValueError(
                    "production needs a validated method and validated parameter profile"
                )
            if request.mode == "production":
                valid_receipt = False
                for receipt_ref in method.validation:
                    receipt = store.get(owner, receipt_ref, "validation")
                    validation_plan = ExecutionPlan.model_validate(
                        store.get(
                            owner, Ref.model_validate(receipt["plan_ref"]), "plan"
                        )
                    )
                    if (
                        validation_plan.environment == env
                        and validation_plan.engine_sha256 == engine_hash()
                        and digest(receipt["parameters"]) == digest(request.parameters)
                    ):
                        valid_receipt = True
                if not valid_receipt:
                    raise ValueError(
                        "method has no validation receipt for current environment/implementation"
                    )
            if set(method.applicability) - {"dataset_id", "dataset_version", "task"}:
                raise ValueError(
                    "method declares applicability constraints not implemented by this planner"
                )
            if (
                method.applicability.get("dataset_id", data.survey.dataset_id)
                != data.survey.dataset_id
                or method.applicability.get("task", data.survey.task)
                != data.survey.task
            ):
                raise ValueError("method not applicable to this dataset/task")
            if (
                method.applicability.get("dataset_version", data.survey.dataset_version)
                != data.survey.dataset_version
            ):
                raise ValueError(
                    "literature method belongs to a different dataset version"
                )
            configs = []
            errors = []
            for record in selected_records:
                try:
                    steps = compile_steps(method, record, data, request.parameters)
                    estimate = (
                        signal_bytes(record, steps, data.collection.root)
                        * (len(steps) + 8)
                        * 3
                    )
                    configs.append(
                        RecordPlan(
                            method_ref=ref,
                            record_id=record.id,
                            steps=steps,
                            output=method.output,
                            estimated_memory_bytes=estimate,
                            code_hashes={
                                s.unit_id: specification(s.unit_id).source[
                                    "code_sha256"
                                ]
                                for s in steps
                            },
                        )
                    )
                except ValueError as exc:
                    errors.append(f"{record.id}: {exc}")
            if not configs:
                raise ValueError("; ".join(errors))
            # Evidence and method identity do not affect numerical equivalence.
            signature = numerical_signature(configs)
            candidates.append((ref, method, configs, signature, errors))
        except ValueError as exc:
            screening.append(
                Screening(method_ref=ref, status="blocked", reasons=[str(exc)])
            )
    unique, seen = [], {}
    for item in candidates:
        ref, method, configs, signature, errors = item
        if signature in seen:
            screening.append(
                Screening(
                    method_ref=ref,
                    status="duplicate",
                    reasons=[
                        "same resolved implementations, steps, parameters, scope and outputs"
                    ],
                    duplicate_of=seen[signature],
                )
            )
        else:
            unique.append(item)
            seen[signature] = ref
    if request.selection == "all" and len(unique) > request.max_candidates:
        raise ValueError(
            "all-selected methods exceed candidate budget; increase budget explicitly"
        )
    ordered, mechanisms = [], set()
    for item in unique:
        if item[1].mechanism not in mechanisms:
            ordered.append(item)
            mechanisms.add(item[1].mechanism)
    ordered.extend(item for item in unique if item not in ordered)
    records = []
    for i, (ref, method, configs, signature, errors) in enumerate(ordered):
        selected = i < request.max_candidates
        screening.append(
            Screening(
                method_ref=ref,
                status="selected" if selected else "deferred",
                reasons=(
                    ["eligible; mechanism diversity then request order"]
                    if selected
                    else ["candidate budget reached"]
                )
                + ["blocked recording " + error for error in errors],
            )
        )
        if selected:
            records.extend(configs)
    # Bound work copies and diagnostics as well as final output. Candidate count
    # is small; this conservative estimate intentionally favors explicit budgets.
    record_index = {r.id: r for r in data.collection.records}
    input_bytes = {
        r.id: sum(
            (Path(data.collection.root) / name).stat().st_size
            for name in working_files(r)
        )
        for r in data.collection.records
    }
    for config in records:
        config.estimated_disk_bytes = input_bytes[config.record_id] + signal_bytes(
            record_index[config.record_id], config.steps, data.collection.root
        ) * (len(config.steps) + 6)
    estimated_disk = sum(c.estimated_disk_bytes for c in records)
    resources = budget(store.root, request)
    require_capacity("disk", estimated_disk, resources.disk_limit_bytes)
    require_capacity(
        "memory",
        max((c.estimated_memory_bytes for c in records), default=0),
        resources.memory_limit_bytes,
    )
    plan = ExecutionPlan(
        request=request,
        input_snapshot=data,
        screening=screening,
        records=records,
        environment=env,
        engine_sha256=engine_hash(),
        estimated_disk_bytes=estimated_disk,
        resource_budget=resources,
    )
    return store.put(owner, "plan", plan.model_dump(mode="json")), plan
