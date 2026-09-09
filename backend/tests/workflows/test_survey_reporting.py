import json

import pytest

from app.workflows import dataset
from app.workflows.schemas import WorkflowRequest
from app.workflows.survey_contracts import LiteratureReview, SELECTION_CRITERIA
from app.workflows.survey_research import coverage_table
from app.workflows.survey_reporting import REPORTS, render_survey_reports, link
from tests.workflows.test_survey_purposes import products  # noqa: F401
from tests.workflows.test_workflow import source  # noqa: F401


@pytest.mark.asyncio
async def test_reports_use_only_survey_records_preserve_evidence_and_separate_purposes(
    source,  # noqa: F811
    products,  # noqa: F811
    tmp_path,
):
    _, sources, local, verification, screening = products
    folder = tmp_path / "survey"
    survey = dataset.inspect(source, WorkflowRequest(source_root=str(source)), folder)
    # Zero and unknown must remain distinct; model text must remain inert HTML.
    for entry in screening.entries:
        entry.quality.stars = 0
        entry.reason = "<script>untrusted</script>"
    review = LiteratureReview(
        **screening.model_dump(),
        criteria=SELECTION_CRITERIA,
        coverage=coverage_table(screening, sources, {}),
        sources=[
            {"id": d.id, "title": d.title, "url": d.url} for d in sources.documents
        ],
    )
    values = {
        "survey.json": survey,
        "verification.json": verification.model_dump(),
        "literature.json": review.model_dump(),
        "sources.json": sources.model_dump(),
    }
    for name, value in values.items():
        (folder / name).write_text(json.dumps(value), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
    paths = render_survey_reports(folder)
    assert paths == ["survey/reports/" + name for name in REPORTS]
    documents = {
        name: (folder / "reports" / name).read_text(encoding="utf-8")
        for name in REPORTS
    }
    stats = documents["statistics.html"]
    assert "<td>目标任务 Trial 数</td><td>12</td>" in stats
    assert "含义随 Run 的任务而异；R04/R08/R12 中为左手运动想象" in stats
    assert "<td>6</td>" in stats
    assert "未知 / 未取得" in stats
    targets = {
        "literature-usage.html": {"usage_analysis", "usage_algorithm"},
        "literature-discussion.html": {"dataset_discussion"},
        "literature-preprocessing.html": {"preprocessing_methods"},
    }
    for name, allowed in targets.items():
        text = documents[name]
        for entry in review.entries:
            assert (f"{entry.id} ·" in text) == (entry.target in allowed)
        assert "<script>" not in text
    assert any(
        "&lt;script&gt;untrusted&lt;/script&gt;" in t for t in documents.values()
    )
    assert any("<td>未知</td><td>未知</td><td>0</td>" in t for t in documents.values())
    assert before == {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
    render_survey_reports(folder)
    assert documents == {
        name: (folder / "reports" / name).read_text(encoding="utf-8")
        for name in REPORTS
    }
    assert link("javascript:alert(1)", "unsafe") == "unsafe"
