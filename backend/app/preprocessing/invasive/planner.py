from __future__ import annotations

from .schemas import InvasiveExecutionPlan, InvasivePlanRequest, NeuroDatasetSnapshot, PlannedStep


def create_invasive_plan(snapshot: NeuroDatasetSnapshot, request: InvasivePlanRequest) -> InvasiveExecutionPlan:
    representations = {item.representation for item in snapshot.collections}
    event_representation = next(
        (value for value in ("spike_times", "threshold_crossings") if value in representations),
        None,
    )
    has_units = event_representation is not None
    has_raw = "raw_voltage" in representations
    has_trials = "trials" in representations
    streams = [item.path for item in snapshot.collections if item.representation in {"behavior", "stimulus"}]
    warnings = list(snapshot.warnings)
    steps = [
        PlannedStep(
            id="survey",
            stage="survey",
            operation="bounded_nwb_inspection",
            status="run",
            reason="Use shapes, dtypes, metadata and bounded timestamp endpoints; do not preload signal arrays.",
            parameters={"inspected_scalar_values": snapshot.inspected_values},
        )
    ]

    if has_units:
        strategy = "consume_released_derivative"
        representation = event_representation
        executable = True
        steps.append(
            PlannedStep(
                id="spike_sorting",
                stage="plan",
                operation="spike_sorting",
                status="skip",
                reason=(
                    "NWB Units contains released threshold-crossing/multiunit events; preserve channel identity and do not run single-unit spike sorting."
                    if event_representation == "threshold_crossings"
                    else "NWB Units/spike_times already exists; preserve the publisher's processed object and unit identity."
                ),
            )
        )
        steps.extend(
            [
                PlannedStep(
                    id="unit_qc",
                    stage="qc",
                    operation="unit_quality_metrics_and_selection",
                    status="run",
                    reason=(
                        "Measure event rate, temporal presence/stability and invalid events per threshold channel; single-unit refractory-period rejection is not applicable to merged multiunit events."
                        if event_representation == "threshold_crossings"
                        else "Measure firing rate, refractory-period violations, temporal presence/stability and invalid events; retain per-unit reasons."
                    ),
                    parameters=request.qc.model_dump(mode="json"),
                ),
                PlannedStep(
                    id="alignment",
                    stage="alignment",
                    operation="validate_and_align_timebases",
                    status="run",
                    reason="Check monotonicity, finite timestamps, coverage, gaps and neural-to-stream offsets before interpolation/trialization.",
                    parameters={"available_streams": streams, "target_series_path": request.transform.target_series_path},
                ),
                PlannedStep(
                    id="transform",
                    stage="transform",
                    operation="spike_event_transform",
                    status="run",
                    reason="Materialize only the task-requested event, T×N binned/smoothed, and trial-aligned representations.",
                    parameters=request.transform.model_dump(mode="json"),
                ),
                PlannedStep(
                    id="validate",
                    stage="validate",
                    operation="integrity_distribution_and_optional_linear_baseline",
                    status="run",
                    reason="Verify identity, retention, alignment and finite signal distributions; run a ridge diagnostic with the published evaluation mask when present, otherwise a chronological split, only when a numeric target is available.",
                ),
                PlannedStep(
                    id="report",
                    stage="report",
                    operation="write_reproducible_derivative_bundle",
                    status="run",
                    reason="Write manifest, configuration, QC decisions, alignment diagnostics, final shapes and warnings without modifying the NWB source.",
                ),
            ]
        )
    elif has_raw:
        strategy = "reprocess_from_raw"
        representation = "raw_voltage"
        executable = False
        missing = []
        if not request.method_profile:
            missing.append("dataset/probe-specific method profile")
        if not request.literature_evidence_refs:
            missing.append("literature evidence for filter/reference/artifact/sorting choices")
        if not request.code_evidence_refs:
            missing.append("official or closely matched preprocessing code")
        steps.extend(
            [
                PlannedStep(
                    id="raw_method_research",
                    stage="plan",
                    operation="literature_and_code_search",
                    status="blocked" if missing else "run",
                    reason="Raw extracellular voltage requires probe geometry, acquisition state and experiment-specific evidence; there is no universal invasive default.",
                    evidence_needed=missing,
                ),
                PlannedStep(
                    id="raw_ephys",
                    stage="transform",
                    operation="filter_artifact_reference_detect_sort",
                    status="blocked",
                    reason="The base worker intentionally does not invoke an unpinned sorter. A validated SpikeInterface/container profile and representative-data receipt are required.",
                    parameters={"candidate_operations": ["filtering", "artifact removal", "referencing", "spike detection", "spike sorting", "waveform/quality extraction"]},
                    evidence_needed=["validated executable method profile", "pinned sorter/container", "probe geometry and acquisition metadata"],
                ),
            ]
        )
        warnings.append("Raw voltage was found without Units/spike_times; execution is blocked rather than silently choosing a sorter or parameters.")
    else:
        strategy = "inspect_only"
        representation = "unknown"
        executable = False
        steps.append(
            PlannedStep(
                id="unsupported_representation",
                stage="plan",
                operation="resolve_representation",
                status="blocked",
                reason="The first release executes sorted spike/event NWB data. Ophys metadata is recognized for future extension but is not numerically reprocessed.",
            )
        )

    target_matches = not request.transform.target_series_path or any(
        path == request.transform.target_series_path
        or path.startswith(request.transform.target_series_path.rstrip("/") + "/")
        for path in streams
    )
    if not target_matches:
        executable = False
        steps.append(
            PlannedStep(
                id="target_binding",
                stage="alignment",
                operation="bind_target_series",
                status="blocked",
                reason="Requested target_series_path is not a discovered behavior/stimulus TimeSeries.",
                parameters={"requested": request.transform.target_series_path, "available": streams},
            )
        )
    elif not streams:
        warnings.append("No behavior/stimulus TimeSeries was discovered; baseline decoding will be skipped.")
    if not has_trials:
        warnings.append("No trials table was discovered; trial-aligned tensors will be skipped.")

    return InvasiveExecutionPlan(
        snapshot_ref=request.snapshot_ref,
        task=request.task,
        modality=snapshot.modality,
        input_representation=representation,
        strategy=strategy,
        executable=executable,
        method_profile=request.method_profile,
        literature_evidence_refs=request.literature_evidence_refs,
        code_evidence_refs=request.code_evidence_refs,
        qc=request.qc,
        transform=request.transform,
        steps=steps,
        warnings=warnings,
    )
