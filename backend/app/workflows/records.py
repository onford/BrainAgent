"""Human-readable module records, with a compact index instead of a second copy."""

import json
from pathlib import Path
from uuid import uuid4
from app.preprocessing.storage import file_hash

from .contracts import ProcessData, ProcessIndex, ReportData, STAGE_CONTRACTS
from .cognition_contracts import ResearchFindings, ReportNarrative, ResearchSources
from .survey_contracts import DatasetVerification, LiteratureReview, LocalInspection
from .formats import (
    ARRAY_FORMATS,
    FORMAT_VERSION,
    JSON_MODELS,
    TABLE_MODELS,
    validate_json,
)


def write_readable(path, value):
    path = Path(path)
    value = validate_json(path, value)
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
    check_format(folder)
    value = validate_stage(name, value)
    write_readable(folder / STAGE_CONTRACTS[name][1], value)
    return value


def load_stage(folder, name):
    model, path = STAGE_CONTRACTS[name]
    return model.model_validate_json((folder / path).read_text(encoding="utf-8"))


def format_schema():
    schema = ProcessData.model_json_schema()
    for model in [
        ReportData,
        ProcessIndex,
        *JSON_MODELS.values(),
        *TABLE_MODELS.values(),
    ]:
        definition = model.model_json_schema()
        schema["$defs"].update(definition.pop("$defs", {}))
        schema["$defs"][model.__name__] = definition
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return schema


def check_format(folder):
    manifest = folder / "process/formats.json"
    if not manifest.exists():
        return  # Historical runs predate the supporting-file format contract.
    definition = json.loads(manifest.read_text(encoding="utf-8"))
    schema = folder / "process/schema.json"
    if (
        definition["format_version"] != FORMAT_VERSION
        or definition["schema_sha256"] != file_hash(schema)
        or json.loads(schema.read_text(encoding="utf-8")) != format_schema()
        or definition["report"]["template_sha256"]
        != file_hash(Path(__file__).parent / "templates/report.html")
        or definition["arrays"] != ARRAY_FORMATS
        or definition["json"] != json_formats()
        or definition["tsv"] != table_formats()
    ):
        raise ValueError("产物格式或报告模板已变化，请新建运行；已有产物保留原格式")


def json_formats():
    return {
        **{
            path: f"schema.json#/$defs/{model.__name__}"
            for model, path in STAGE_CONTRACTS.values()
        },
        **{
            path: f"schema.json#/$defs/{model.__name__}"
            for path, model in JSON_MODELS.items()
        },
    }


def table_formats():
    return {
        name: {
            "columns": list(model.model_fields),
            "row_schema": f"schema.json#/$defs/{model.__name__}",
            "encoding": "UTF-8",
            "delimiter": "tab",
            "newline": "LF",
        }
        for name, model in TABLE_MODELS.items()
    }


def write_index(folder, state):
    schema_path = folder / "process/schema.json"
    formats_path = folder / "process/formats.json"
    if not schema_path.exists():
        schema = format_schema()
        write_readable(schema_path, schema)
        template = Path(__file__).parent / "templates/report.html"
        write_readable(
            formats_path,
            {
                "format_version": FORMAT_VERSION,
                "schema_sha256": file_hash(schema_path),
                "json": json_formats(),
                "tsv": table_formats(),
                "arrays": ARRAY_FORMATS,
                "report": {"format": "HTML", "template_sha256": file_hash(template)},
                "external_formats": {
                    "collection/bids/": "BIDS-EEG / BrainVision, mne-bids 0.17.0",
                    "preprocessing/runs/": "MNE FIF / NumPy / executor JSON; step payloads follow the frozen execution plan",
                },
            },
        )
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


def report_data(folder):
    survey = load_stage(folder, "data_survey")
    collection = load_stage(folder, "data_collection")
    prep = load_stage(folder, "data_preprocessing")
    selection = load_stage(folder, "data_evaluation")
    index = ProcessIndex.model_validate_json(
        (folder / "process/index.json").read_text(encoding="utf-8")
    )
    method = next(m for m in prep.methods if m.ref == selection.selected_method_ref)

    def optional(relative, model):
        path = folder / relative
        return (
            model.model_validate_json(path.read_text(encoding="utf-8"))
            if path.exists()
            else None
        )

    references = [r.model_dump() for r in survey.profile.references]
    extra_sources = optional("preprocessing/sources.json", ResearchSources) or optional(
        "collection/sources.json", ResearchSources
    )
    if extra_sources:
        references.extend(
            {"title": d.title, "url": d.url}
            for d in extra_sources.documents
            if d.url not in {r["url"] for r in references}
        )
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
        references=references,
        research=optional("preprocessing/research.json", ResearchFindings)
        or optional("collection/research.json", ResearchFindings)
        or optional("survey/research.json", ResearchFindings),
        narrative=optional("report/narrative.json", ReportNarrative),
        verification=optional("survey/verification.json", DatasetVerification),
        literature=optional("survey/literature.json", LiteratureReview),
        local_inspection=optional("survey/local-inspection.json", LocalInspection),
        limitations=[
            collection.validation,
            *collection.adaptations,
            "待补充：" + ", ".join(survey.profile.unknown_fields),
            survey.profile.literature_status,
            "本轮未进行候选质量排名或模型效果评估。",
        ],
    )
