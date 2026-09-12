from __future__ import annotations

import json

from .schemas import (
    Evidence,
    MethodDraft,
    MethodSpec,
    Scope,
    Step,
    SurveyLiteratureBundle,
)
from .storage import Storage
from .units import OPERATIONS


def baseline_methods() -> list[MethodSpec]:
    """Project templates adapted from explicit MNE tutorials, not 'MNE defaults'."""
    evidence = [
        Evidence(
            source_url="https://mne.tools/1.10/auto_tutorials/preprocessing/30_filtering_resampling.html",
            locator="Filtering",
            text="MNE supports configurable filtering of continuous EEG before epoch extraction.",
            source_version="MNE 1.10.2",
        )
    ]
    common = [
        Step(
            id="filter",
            unit_id="EEG-FILTER",
            op="filter",
            params={
                "l_freq": "$profile.l_freq",
                "h_freq": "$profile.h_freq",
                "method": "iir",
                "phase": "zero",
                "picks": "$eeg_channels",
            },
            evidence_indices=[0],
        ),
        Step(
            id="reference",
            unit_id="EEG-REREFERENCE",
            op="reference",
            input="filter",
            params={"ref_channels": "average"},
            evidence_indices=[0],
        ),
    ]

    def tail(predecessor):
        return [
            Step(
                id="epochs",
                unit_id="EEG-EPOCH",
                op="epoch",
                input=predecessor,
                params={
                    "events": "$events",
                    "event_id": "$event_id",
                    "tmin": "$profile.tmin",
                    "tmax": "$profile.tmax",
                    "picks": "$all_channels",
                },
                evidence_indices=[0],
            ),
            Step(
                id="baseline",
                unit_id="EEG-BASELINE",
                op="baseline",
                input="epochs",
                params={"baseline": "$profile.baseline"},
                evidence_indices=[0],
            ),
        ]

    # Full procedural design is ours; citations motivate operations, not every
    # parameter choice. Parameter values are explicitly supplied by the caller.
    adapted = [
        "BrainAgent project recipe, not an exact author pipeline or MNE default",
        "4th-order Butterworth zero-phase EEG filtering; caller supplies scientific frequency/time parameters",
        "Epoch auxiliary channels are retained; baseline follows MNE channel-type semantics",
    ]
    first = MethodSpec(
        id="mne-project-baseline",
        version="1",
        title="MNE 项目基础流程",
        source="classic",
        mechanism="filter-reference-epoch",
        evidence=evidence,
        recipe=common + tail("reference"),
        output="baseline",
        adaptations=adapted,
    )
    regression_evidence = Evidence(
        source_url="https://mne.tools/1.10/auto_tutorials/preprocessing/35_artifact_correction_regression.html",
        locator="EOG regression",
        text="Fit a regression model from EOG channels and apply it to EEG channels. BrainAgent restricts fitting to the declared calibration partition.",
        source_version="MNE 1.10.2",
    )
    second = MethodSpec(
        id="mne-project-eog-regression",
        version="1",
        title="MNE EOG 回归项目流程",
        source="classic",
        mechanism="eog-regression",
        evidence=[*evidence, regression_evidence],
        recipe=[
            *common,
            Step(
                id="fit",
                unit_id="EEG-EOG-REGRESSION",
                op="eog_fit",
                input="reference",
                params={
                    "picks": "$eeg_channels",
                    "picks_artifact": "$eog_channels",
                    "reference_id": "average",
                },
                fit_scope=Scope(role="calibration", ids=["calibration"]),
                evidence_indices=[1],
            ),
            Step(
                id="correct",
                unit_id="EEG-EOG-REGRESSION",
                op="eog_apply",
                input="reference",
                model_from="fit",
                params={"reference_id": "average"},
                evidence_indices=[1],
            ),
            *tail("correct"),
        ],
        output="baseline",
        adaptations=adapted
        + [
            "Fit branch replays transforms after selecting a single calibration interval; calibration id must be explicit in Collection"
        ],
    )
    return [first, second]


def check_mapping(method: MethodSpec):
    checks = []
    seen = {"raw"}
    for step in method.recipe:
        schema = OPERATIONS.get((step.unit_id, step.op))
        if step.implementation_version == "2":
            from .units.operations_v2 import DEFINITIONS
            spec = DEFINITIONS.get((step.unit_id, step.op))
            if spec is None:
                checks.append(f"unmapped operation: {step.unit_id}/{step.op}")
            else:
                supplied = step.params.keys() | step.artifact_inputs.keys() | step.asset_inputs.keys() | step.parameter_inputs.keys()
                missing = set(spec["required"]) - supplied
                extra = supplied - set(spec["required"]) - spec["defaults"].keys()
                if missing or extra:
                    checks.append(f"parameter contract: {step.id}; missing={sorted(missing)}; extra={sorted(extra)}")
        elif schema is None:
            checks.append(f"unmapped operation: {step.unit_id}/{step.op}")
        else:
            required = {k for k, v in schema.model_fields.items() if v.is_required()}
            missing = sorted(required - step.params.keys())
            extra = sorted(step.params.keys() - schema.model_fields.keys())
            if missing or extra:
                checks.append(
                    f"parameter contract: {step.id}; missing={missing}; extra={extra}"
                )
        for key, value in step.params.items():
            if isinstance(value, list) and any(
                isinstance(v, str)
                and v
                in {"$eeg_channels", "$eog_channels", "$all_channels", "$event_id"}
                for v in value
            ):
                checks.append(
                    f"collection binding must replace the whole parameter value: {step.id}.{key}"
                )
        if step.id in seen or any(
            ref is not None and ref not in seen
            for ref in (step.input, step.model_from, step.decision_from)
        ):
            checks.append(f"invalid step dependencies: {step.id}")
        seen.add(step.id)
        if any(i < 0 or i >= len(method.evidence) for i in step.evidence_indices):
            checks.append(f"missing parameter/step evidence: {step.id}")
    if method.output == "raw" or method.output not in seen:
        checks.append("method output must reference a recipe step id")
    for role, node in method.output_roles.items():
        if not role.replace('_','').isalnum() or node not in seen or node=='raw':
            checks.append('output role must name a safe role and an executed data node: '+role)
    return checks


def automatic_cleaning_methods() -> list[MethodSpec]:
    """Optional reviewable templates; not auto-seeded or empirically validated."""
    evidence = [Evidence(
        source_url="https://www.frontiersin.org/journals/neuroinformatics/articles/10.3389/fninf.2015.00016/full",
        locator="Detection of Noisy Channels", source_version="PREP 2015",
        text="PREP motivates amplitude and correlation diagnostics; this project uses a simplified MAD/max-peer engineering detector, not PREP reproduction."),
        Evidence(source_url="https://mne.tools/1.10/generated/mne.io.Raw.html#mne.io.Raw.interpolate_bads",
                 locator="interpolate_bads", source_version="MNE 1.10.2",
                 text="MNE provides EEG spherical-spline interpolation from channel geometry."),
        Evidence(source_url="https://pypi.org/project/asrpy/0.0.8/", locator="ASR.fit/transform source",
                 source_version="ASRpy 0.0.8",
                 text="Euclidean ASR fits thresholds from calibration EEG and corrects the original signal. This adapter guards rank and calibration duration before application.")]
    methods = []
    for use_asr in (False, True):
        recipe = [
            Step(id="highpass", unit_id="EEG-FILTER", op="filter",
                 params={"l_freq": 1.0, "h_freq": None, "method": "iir", "phase": "zero", "picks": "$eeg_channels"}, evidence_indices=[2]),
            Step(id="detect", unit_id="EEG-AUTO-BAD-CHANNEL", op="detect_bad_channels", input="highpass",
                 params={"adaptation_scope": "record_unlabeled"}, evidence_indices=[0]),
            Step(id="mark", unit_id="EEG-BAD-CHANNEL-MARK", op="mark_channels", input="highpass", decision_from="detect",
                 params={"max_fraction": 0.1}, evidence_indices=[0])]
        if use_asr:
            recipe.append(Step(id="asr", unit_id="EEG-ASR-AUTO", op="asr_clean", input="mark",
                               params={"adaptation_scope": "record_unlabeled", "cutoff": 20}, evidence_indices=[2]))
        recipe.extend([
            Step(id="interpolate", unit_id="EEG-AUTO-BAD-CHANNEL", op="interpolate_bad_channels",
                 input="asr" if use_asr else "mark", params={"max_fraction": 0.1}, evidence_indices=[1]),
            Step(id="car", unit_id="EEG-REREFERENCE", op="reference", input="interpolate",
                 params={"ref_channels": "average"}, evidence_indices=[0])])
        methods.append(MethodSpec(id="auto-clean-asr" if use_asr else "auto-clean-spatial", version="1",
            title="无标签坏道修复与 ASR" if use_asr else "无标签坏道修复",
            source="classic", mechanism="detect-asr-interpolate-car" if use_asr else "detect-interpolate-car",
            evidence=evidence, recipe=recipe, output="car",
            adaptations=["Project engineering recipe, not full PREP/clean_rawdata reproduction.",
                         "Explicit whole-record unlabeled transductive adaptation; not train-only/online.",
                         "No real EOG dependency, ICA classification or trial rejection.",
                         "Append a common analysis band/epoch grid; high-pass and thresholds are search priors, not guaranteed optimal."]))
    return methods


def extraction_contracts(version="1"):
    if version == "2":
        from .units.operations_v2 import inventory
        from .units.contracts_v2 import parameter_schema
        grouped = {}
        for r in inventory():
            key = (r['unit_id'], r['op'])
            if key not in grouped:
                grouped[key] = {"unit_id": r["unit_id"], "op": r["op"],
                 "implementation_version": "2", "parameters": parameter_schema(r),
                 "input_kind": r["input_kind"], "effect": r["effect"], "fit": r["fit"],
                 "model_kind": r["model_kind"], "decision_required": r["decision"],
                 "ports": {"input_channels":"explicit named channel projection", "artifact_inputs":"prior step typed data/model/diagnostic fields", "parameter_inputs":"closed object/array/digest/comparison/nonzero constructors over typed ports", "asset_inputs":"registered forward/projections/annotations Ref", "record_decisions":"per-record human confirmation with data/model hashes"},
                 "source_contract": r["source"]["source"]["fields"], "profiles": []}
            grouped[key]['profiles'].append({'profile':r['profile'],'parameters':r['profile_parameters'],'input_kind':r['input_kind']})
        return list(grouped.values())
    semantics = {
        "notch": "Continuous finite Raw only; freqs explicit unique ordered [50], [60] or [50,60] Hz, picks explicit EEG names. Existing unmodified MNE FIR zero-phase/firwin kernel, width=freq/200, total transition bandwidth1Hz. Entire stop/transition band must remain below Nyquist. Reject acquisition joins; retain complete sample/channel/event grid. Optional when line-noise overlaps retained spectrum; not automatically required after a sufficiently attenuating lowpass. No fitting or labels.",
        "detect_bad_channels": "Continuous Raw -> unchanged Raw + candidates. Engineering consensus_v2: flat OR amplitude with low correlation OR sustained low correlation. Coherent amplitude outliers are diagnostic only, not certified normal; NOT PREP reproduction. Effective thresholds and channel diagnostic classes are saved. Explicit record_unlabeled transductive adaptation, no class labels. Bind mark_channels.decision_from to this step and use its exact input.",
        "interpolate_bad_channels": "Continuous Raw -> same grid/physical V. MNE spherical splines repair currently marked EEG only, require head geometry and max_fraction; preserve auxiliary channels and all events/trials. Clear only successfully repaired EEG marks. Place after ASR and before CAR.",
        "asr_clean": "ASRpy 0.0.8 Euclidean correction with locally adapted complete-block calibration covariance on unmarked EEG, fixed samples/channels/events. Explicit record_unlabeled transductive calibration, not train-only. Requires full-rank good EEG before CAR/interpolation, high-pass >=0.5 Hz, sufficient clean calibration >=30s, sfreq>82. No EOG/ICA classifier, no time/trial rejection. on_insufficient_calibration defaults to error; explicit identity only handles ASR_CALIBRATION_TOO_SHORT and reports status=not_applicable/asr_applied=false with actual/min seconds. Numerical/rank failures remain errors. Defaults cutoff20, window0.5s require >=1Hz high-pass; calibration mask/matrices and boundary caveat saved.",
        "detrend": "Remove constant/linear trend on EEG picks; preserve data state.",
        "filter": "Continuous Raw -> Raw; EEG picks only; IIR is fixed fourth-order Butterworth, zero phase. This phase is an implementation choice unless supported by source evidence.",
        "resample": "Continuous Raw -> Raw at sfreq Hz, fixed polyphase anti-aliasing. Pass $events; the executor synchronizes target event sample indices, preserving original event identity and recording timing error. Use the same target sfreq across mixed-rate records before epoch. Does not add original frequency information when upsampling.",
        "reference": "Average reference uses EEG channels, excluding auxiliary channels; preserve data state.",
        "epoch": "Continuous Raw -> Epochs; events from Collection and event_id from Survey; tmin/tmax in seconds. No baseline or amplitude-based rejection. MNE reject_by_annotation=True drops epochs overlapping BAD annotations and records drop_log; the common evaluation trial-coverage contract still applies and cannot be relaxed for a source method.",
        "baseline": "Epochs -> Epochs; subtract baseline mean, NOT percentage ERD/ERS normalization.",
        "eog_fit": "Continuous Raw -> model port; requires real EOG channels and one explicit calibration/train interval id in fit_scope; never fit test data.",
        "eog_apply": "Data input and model_from from a preceding eog_fit; matching reference_id required. EOG regression does not implement EMG screening.",
        "amplitude_windows": "Continuous Raw -> unchanged Raw plus channel candidates from sliding-window PEAK-TO-PEAK thresholds in volts. Does NOT implement absolute-amplitude trial rejection or apply exclusion.",
        "mark_channels": "Apply channel marks using decision_from an earlier amplitude_windows or detect_bad_channels result bound to the exact input; does not drop trials.",
    }
    return [
        {
            "unit_id": unit,
            "op": op,
            "parameters": schema.model_json_schema(),
            "semantics": semantics[op],
        }
        for (unit, op), schema in OPERATIONS.items()
    ]


class MethodLibrary:
    def __init__(self, store: Storage, llm=None):
        self.store, self.llm = store, llm

    def seed(self, owner):
        return [
            self.store.put(owner, "method", m.model_dump(mode="json"))
            for m in baseline_methods()
        ]

    async def intake(self, owner, bundle: SurveyLiteratureBundle):
        methods, supplements = [], []
        for paper in bundle.papers:
            missing = list(paper.missing_items) + [
                "resolve source conflict: " + c for c in paper.conflicts
            ]
            if not paper.fulltext_ref or not paper.evidence:
                missing.append(
                    "fulltext_ref and precise preprocessing evidence passages"
                )
            if missing:
                supplements.append(
                    {
                        "target_agent": "data_survey",
                        "survey_run_id": bundle.survey_run_id,
                        "paper_id": paper.paper_id,
                        "missing_fields": missing,
                        "source_locator": paper.landing_url,
                        "blocking_reason": "insufficient evidence to reconstruct preprocessing",
                    }
                )
                continue
            fulltext = self.store.get(owner, paper.fulltext_ref, "evidence")
            content = str(fulltext.get("content", ""))
            if not content or any(e.text not in content for e in paper.evidence):
                raise ValueError(
                    "evidence passages must be present in the stored full text"
                )
            if self.llm is None:
                supplements.append(
                    {
                        "target_agent": "data_survey",
                        "paper_id": paper.paper_id,
                        "missing_fields": ["configured method extraction model"],
                        "source_locator": paper.landing_url,
                        "blocking_reason": "extraction is unavailable",
                    }
                )
                continue
            if bundle.input_ref is None:
                supplements.append({"target_agent": "data_collection", "paper_id": paper.paper_id,
                    "missing_fields": ["input_ref"], "source_locator": paper.landing_url,
                    "blocking_reason": "shared extraction requires a frozen target Collection input"})
                continue
            from types import SimpleNamespace
            from .schemas import PreprocessInput
            from .literature import extraction_inputs, materialize
            from .research_budget import open_budget
            from .storage import digest, write_json
            from app.workflows.cognition import WorkflowCognition
            from app.workflows.source_extraction import extract_source
            data = PreprocessInput.model_validate(self.store.get(owner, bundle.input_ref, "input"))
            if (data.survey.dataset_id, data.survey.dataset_version) != (bundle.dataset_id, bundle.dataset_version):
                raise ValueError("literature bundle and target input identity differ")
            evidence = [e.model_copy(update={"artifact_ref": paper.fulltext_ref}) for e in paper.evidence]
            source = {**paper.model_dump(mode="json", exclude={"evidence"}), "url": paper.landing_url,
                      "sha256": paper.fulltext_ref.sha256, "links": fulltext.get("links", [])}
            inputs = extraction_inputs(source, evidence, data, bundle.shared_output)
            identity = {"source_ref": paper.fulltext_ref.model_dump(), "source_sha256": paper.fulltext_ref.sha256,
                        "source_url": paper.landing_url, "source_id": paper.paper_id}
            root = self.store.root / "intake" / digest([owner, bundle.model_dump(mode="json")])
            shim = SimpleNamespace(llm=self.llm, tools=None, source_reader=None,
                preprocessing=SimpleNamespace(store=self.store), folder=lambda _: root,
                event=lambda *args: None, save=lambda *args: None)
            cognition = WorkflowCognition(shim, {"id": root.name, "owner": owner}, "data_preprocessing")
            budget = open_budget(root / "budget.json", {"max_seconds": 900, "max_recovery_actions": 6}, bundle.model_dump(mode='json'))
            try:
                extraction, evidence, recovery = await extract_source(cognition, inputs, evidence, data,
                    identity, root / digest(source)[:20], budget)
            except (TimeoutError, RuntimeError) as exc:
                supplements.append({'target_agent': 'data_preprocessing', 'paper_id': paper.paper_id,
                    'missing_fields': ['completed_source_extraction'], 'source_locator': paper.landing_url,
                    'blocking_reason': f'{type(exc).__name__}: {exc}'})
                continue
            for method in materialize(extraction, evidence, data, identity):
                methods.append(self.store.put(owner, "method", method.model_dump(mode="json")))
            write_json(root / "result.json", {"methods": [r.model_dump() for r in methods], "recovery": recovery})
        return {"methods": methods, "supplement_requests": supplements}
