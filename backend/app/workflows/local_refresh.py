"""Add a separately dated observation/report to a completed legacy run."""

import json
from pathlib import Path
from string import Template
from tempfile import TemporaryDirectory

from . import dataset
from .local_contracts import read_local
from .schemas import WorkflowRequest
from .survey_contracts import DatasetVerification
from .cognition_contracts import ResearchSources
from .survey_reporting import TEMPLATE, information
from .reporting import escape


def refresh_local_report(folder):
    folder = Path(folder).resolve()
    state = json.loads((folder / "workflow.json").read_text(encoding="utf-8"))
    if state["status"] != "completed":
        raise ValueError("Only completed runs can receive a separate local observation")
    survey_folder = folder / "survey"
    destination = survey_folder / "observation-v2"
    if destination.exists():
        raise ValueError("Supplement already exists; keep its dated snapshot")
    survey = json.loads((survey_folder / "survey.json").read_text(encoding="utf-8"))
    dataset.check_sources(survey)
    # Preserve the historical selection even if new subject directories appeared.
    request = WorkflowRequest.model_validate(
        {
            **state["request"],
            "subjects": survey["selected_subjects"],
            "runs": sorted({r["run"] for r in survey["records"]}),
        }
    )
    verification = DatasetVerification.model_validate_json(
        (survey_folder / "verification.json").read_text(encoding="utf-8")
    )
    sources = ResearchSources.model_validate_json(
        (survey_folder / "sources.json").read_text(encoding="utf-8")
    )
    with TemporaryDirectory(prefix=".observation-", dir=survey_folder) as temp:
        output = Path(temp) / "observation-v2"
        fresh = dataset.inspect(Path(survey["source_root"]), request, output)
        fields = (
            "id",
            "status",
            "sha256",
            "sfreq",
            "samples",
            "duration_s",
            "event_counts",
        )

        def project(value):
            return [{k: r.get(k) for k in fields} for r in value["records"]]

        if project(fresh) != project(survey):
            raise ValueError(
                "Fresh measurements differ from historical records; create a new workflow"
            )
        local = read_local(output / "local-inspection.json")
        body = '<p class="muted">本地观测为补充检查，日期见下方。外部资料与模型核对结论沿用原运行，尚未重新调研。原始过程文件及训练产物保留在记录文件中。</p>'
        body += information(local, verification, {s.id: s for s in sources.documents})
        body += '<h2>结构化原始记录</h2><p><a href="../local-inspection.json?download=true">本次本地观测</a> · <a href="../source-inventory.tsv?download=true">本次文件清单</a> · <a href="../../verification.json?download=true">原运行核对记录</a></p>'
        reports = output / "reports"
        reports.mkdir()
        (reports / "data-information.html").write_text(
            Template(TEMPLATE.read_text(encoding="utf-8")).substitute(
                title="数据信息与三方核对",
                subtitle=escape(survey["profile"]["name"]),
                navigation="",
                body=body,
            ),
            encoding="utf-8",
        )
        dataset.check_sources(survey)
        output.rename(destination)
    return destination / "reports/data-information.html"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="保留历史产物，为已完成运行补充结构化本地观测与报告"
    )
    parser.add_argument("workflow_folder", type=Path)
    print(refresh_local_report(parser.parse_args().workflow_folder))
