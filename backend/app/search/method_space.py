"""Executable search vocabulary and method starting points."""

from copy import deepcopy

from app.preprocessing.storage import digest
from .pipeline_space import recipe_hash, validate_recipe
from .space_contracts import CandidateRecipe, ExplorationSpace


BASELINE_ID = "bp8-30-average"


def basic_space():
    """Engineering baselines are explicitly distinguished from literature recipes."""

    def number(lo, hi, unit, rationale):
        return dict(
            kind="number",
            minimum=lo,
            maximum=hi,
            unit=unit,
            rationale=rationale,
            origin="engineering",
        )

    def choice(values, rationale):
        return dict(
            kind="choice",
            choices=values,
            unit="category",
            rationale=rationale,
            origin="engineering",
        )

    def op(identity, title, unit, operation, stage="continuous", output="same", **kw):
        return dict(
            id=identity,
            title=title,
            unit_id=unit,
            op=operation,
            input_stage=stage,
            output_stage=output,
            fit_scope="none",
            domains={},
            defaults={},
            **kw,
        )

    operators = [
        op(
            "resample",
            "输出采样网格",
            "EEG-RESAMPLE",
            "resample",
            required=True,
            bindings={"sfreq": "$output.sfreq", "events": "$events"},
        ),
        {
            **op("bandpass", "带通滤波", "EEG-FILTER", "filter"),
            "domains": {
                "l_freq": number(
                    0.5, 15, "Hz", "覆盖慢活动至运动节律的比较范围；不是最优频带声明"
                ),
                "h_freq": number(
                    20, 60, "Hz", "低于160 Hz输出网格的奈奎斯特频率并留出过渡区域"
                ),
            },
            "defaults": {"l_freq": 8.0, "h_freq": 30.0},
            "bindings": {"method": "iir", "phase": "zero", "picks": "$eeg_channels"},
        },
        op(
            "average_reference",
            "全脑平均参考",
            "EEG-REREFERENCE",
            "reference",
            stage="either",
            bindings={"ref_channels": "average"},
        ),
        {
            **op("detrend", "去常数或线性趋势", "EEG-DETREND", "detrend"),
            "domains": {
                "type": choice(["constant", "linear"], "比较常数偏移与线性趋势去除")
            },
            "defaults": {"type": "linear"},
            "bindings": {"picks": "$eeg_channels"},
        },
        op(
            "epoch",
            "共同任务切窗",
            "EEG-EPOCH",
            "epoch",
            output="epochs",
            required=True,
            bindings={
                "events": "$events",
                "event_id": "$event_id",
                "picks": "$eeg_channels",
                "tmin": "$output.tmin",
                "tmax": "$output.tmax",
            },
        ),
    ]
    nodes = [
        dict(id="resample", operator="resample"),
        dict(id="bandpass", operator="bandpass"),
        dict(id="reference", operator="average_reference"),
        dict(id="epochs", operator="epoch"),
    ]
    methods = [
        dict(
            id=BASELINE_ID,
            title="基本运动频带 · 平均参考",
            origin="basic",
            recipe={"nodes": nodes},
            applicability=["左右手运动想象"],
            deviations=["工程参考配方；8–30 Hz不是文献最优结论。"],
        )
    ]
    broadband = deepcopy(nodes)
    broadband[1]["parameters"] = {"l_freq": 1.0, "h_freq": 40.0}
    methods.append(
        dict(
            id="basic-broadband",
            title="基本宽频带 · 平均参考",
            origin="basic",
            recipe={"nodes": broadband},
            applicability=["左右手运动想象"],
            deviations=["较宽频率内容的竞争起点；1–40 Hz为工程比较参数。 "],
        )
    )
    original = [n for n in deepcopy(nodes) if n["operator"] != "average_reference"]
    methods.append(
        dict(
            id="basic-acquisition-reference",
            title="基本运动频带 · 采集参考",
            origin="basic",
            recipe={"nodes": original},
        )
    )
    priors = [
        dict(
            id="continuous-before-epoch",
            operator_match="unit_operation",
            implementation_versions=["1", "2"],
            strength="hard",
            relation="before",
            operators=["resample", "epoch"],
            condition="共同事件时间网格",
            rationale="先同步重采样信号与事件，再按冻结网格切窗。",
            origin="implementation",
        )
    ]
    return ExplorationSpace.model_validate(
        dict(operators=operators, methods=methods, priors=priors, evidence={})
    )


def seed_entries(space, context=None):
    space = ExplorationSpace.model_validate(space)
    entries = []
    for seed in space.methods:
        recipe, warnings = validate_recipe(seed.recipe, space, context)
        entries.append(
            _entry(
                seed.id,
                seed.title,
                recipe,
                seed.origin,
                seed.id,
                seed.evidence_ids,
                seed.deviations,
                warnings,
                len(entries),
                lineage=seed.lineage,
                issues=seed.issues,
                space=space,
            )
        )
    unique = {}
    for entry in entries:
        existing = unique.get(entry["recipe_hash"])
        if existing is None:
            entry["order"] = len(unique)
            unique[entry["recipe_hash"]] = entry
            continue
        if not existing["lineage"] and not entry["lineage"]:
            raise ValueError("duplicate seed semantics lack source lineage for deduplication")
        for field in ("lineage", "issues", "evidence_ids", "deviations"):
            for value in entry[field]:
                if value not in existing[field]:
                    existing[field].append(value)
        for target, source in zip(existing["recipe"]["nodes"], entry["recipe"]["nodes"], strict=True):
            for trace in source.get("trace", []):
                if trace not in target["trace"]:
                    target["trace"].append(trace)
            target["optional"] = target.get("optional", True) and source.get("optional", True)
    return list(unique.values())


def _entry(
    identity,
    title,
    recipe,
    origin,
    seed_id,
    evidence,
    deviations,
    warnings,
    order,
    lineage=None,
    issues=None,
    space=None,
):
    return CandidateRecipe.model_validate(
        dict(
            id=identity,
            title=title,
            recipe=recipe.model_dump(mode="json"),
            recipe_hash=recipe_hash(recipe, space),
            origin=origin,
            seed_id=seed_id,
            evidence_ids=evidence,
            deviations=deviations,
            prior_warnings=warnings,
            parameters={
                "operators": [n.operator for n in recipe.nodes],
            },
            operator_count=len(recipe.nodes),
            order=order,
            lineage=lineage or [], issues=issues or [],
        )
    ).model_dump(mode="json")


def verify_entry(entry, space, previous=None, context=None):
    """Only a complete frozen method can enter the execution registry."""
    expected = next((s for s in seed_entries(space, context) if s['id'] == entry['id']), None)
    if expected is None or digest(entry) != digest(expected):
        raise ValueError('candidate differs from its frozen method')
    return expected


def verify_registry(protocol, registry):
    space = ExplorationSpace.model_validate(protocol['space'])
    seeds = seed_entries(space, protocol.get('space_context', {}))
    if registry != seeds:
        raise ValueError('registry must equal the complete frozen method catalog')
    return {entry['id']: entry for entry in registry}
