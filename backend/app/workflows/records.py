"""Human-readable module records, with a compact index instead of a second copy."""

import json
from pathlib import Path
from uuid import uuid4

from .contracts import ProcessData, ProcessIndex, ReportData, STAGE_CONTRACTS


def write_readable(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_stage(name, value):
    model, _ = STAGE_CONTRACTS[name]
    return model.model_validate(value).model_dump(mode="json", exclude_unset=True)


def publish_stage(folder, name, value):
    value = validate_stage(name, value)
    write_readable(folder / STAGE_CONTRACTS[name][1], value)
    return value


def load_stage(folder, name):
    model, path = STAGE_CONTRACTS[name]
    return model.model_validate_json((folder / path).read_text(encoding="utf-8"))


def write_index(folder, state):
    index = ProcessIndex(
        workflow_id=state["id"],
        request=state["request"],
        stages=[
            {
                "name": s["name"],
                "label": s["label"],
                "status": s["status"],
                "data_path": STAGE_CONTRACTS[s["name"]][1]
                if s["status"] == "completed"
                else None,
                "schema_ref": f"schema.json#/$defs/{STAGE_CONTRACTS[s['name']][0].__name__}",
                "error": s.get("error"),
            }
            for s in state["stages"]
        ],
    )
    write_readable(folder / "process/index.json", index.model_dump(exclude_none=True))
    schema_path = folder / "process/schema.json"
    if not schema_path.exists():
        schema = ProcessData.model_json_schema()
        report_schema = ReportData.model_json_schema()
        schema["$defs"].update(report_schema.pop("$defs", {}))
        schema["$defs"]["ReportData"] = report_schema
        index_schema = ProcessIndex.model_json_schema()
        schema["$defs"].update(index_schema.pop("$defs", {}))
        schema["$defs"]["ProcessIndex"] = index_schema
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        write_readable(schema_path, schema)


def report_data(folder):
    survey = load_stage(folder, "data_survey")
    collection = load_stage(folder, "data_collection")
    prep = load_stage(folder, "data_preprocessing")
    selection = load_stage(folder, "data_evaluation")
    index = ProcessIndex.model_validate_json(
        (folder / "process/index.json").read_text(encoding="utf-8")
    )
    method = next(m for m in prep.methods if m.ref == selection.selected_method_ref)
    return ReportData(
        dataset_name=survey.profile.name,
        dataset_version=survey.profile.version,
        license=survey.profile.license,
        subjects=survey.selected_subjects,
        runs=index.request.runs,
        sfreq=survey.profile.expected_sfreq,
        channel_count=survey.profile.expected_eeg_channels,
        before=survey.statistics,
        after=collection.statistics,
        method=method,
        records=[r for r in prep.records if r.method_id == method.ref.id],
        selection_reason=selection.reason,
        seed=selection.seed,
        references=survey.profile.references,
        limitations=[
            collection.validation,
            *collection.adaptations,
            "待补充：" + ", ".join(survey.profile.unknown_fields),
            survey.profile.literature_status,
            "本轮未进行候选质量排名或模型效果评估。",
        ],
    )
