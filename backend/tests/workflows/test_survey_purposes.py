import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.workflows.cognition import WorkflowCognition
from app.workflows.cognition_contracts import ResearchSources
from app.workflows.survey_contracts import (
    DatasetVerification,
    LiteratureScreening,
    LocalInspection,
    SurveyPlan,
    LiteratureReview,
    SELECTION_CRITERIA,
)
from app.workflows.survey_research import (
    validate_verification,
    validate_screening,
    coverage_table,
    missing_tasks,
)
from app.workflows.records import write_readable
from tests.workflows.fakes import Reader, ResearchTools, WorkflowLLM
from tests.workflows.test_parallel_research import make_cognition


@pytest.fixture
async def products():
    sources = ResearchSources(
        documents=[
            await Reader().read("https://physionet.org", "official"),
            await Reader().read("https://example.org/paper", "paper"),
            await Reader().read("https://example.org/repo", "code"),
        ],
        observations=[],
    )
    local = LocalInspection(
        scope="selected records",
        facts=[
            {
                "id": "local-sfreq",
                "field": "sampling_rate",
                "scope": "S001R04",
                "value": "160 Hz",
                "locator": "S001R04.edf",
            }
        ],
    )
    llm = WorkflowLLM()
    verification = await llm.structured_output(
        [{}, {"content": json.dumps({"local_inspection": local.model_dump()})}],
        DatasetVerification,
    )
    screening = await llm.structured_output(
        [{}, {"content": "{}"}], LiteratureScreening
    )
    agent = SimpleNamespace(validate_findings=WorkflowCognition.validate_findings)
    return agent, sources, local, verification, screening


@pytest.mark.asyncio
async def test_three_way_comparison_requires_actual_local_and_official_paper_evidence(
    products,
):
    agent, sources, local, verification, _ = products
    validate_verification(agent, verification, sources, local)
    row = next(r for r in verification.comparisons if r.field == "sampling_rate")
    row.official_sources.statement = "160 Hz"
    row.official_sources.finding_ids = ["f1"]
    row.status = "consistent"
    other = next(r for r in verification.comparisons if r.field == "channels")
    other.status = "consistent"
    with pytest.raises(ValueError, match="all three sides") as error:
        validate_verification(agent, verification, sources, local)
    assert "channels:" in str(error.value) and "sampling_rate:" in str(error.value)
    other.status = "unverifiable"
    row.status = "partial"
    row.official_paper.statement = "Acquisition-system methods"
    row.official_paper.finding_ids = ["f3"]
    verification.official_publication.source_id = "paper"
    verification.official_publication.role = "acquisition_system"
    verification.official_publication.basis_finding_ids = ["f1", "f3"]
    with pytest.raises(ValueError, match="acquisition-system paper"):
        validate_verification(agent, verification, sources, local)
    verification.official_publication.role = "dataset_paper"
    validate_verification(agent, verification, sources, local)
    row.local_fact_ids = ["imagined-local-id"]
    with pytest.raises(ValueError, match="observed facts"):
        validate_verification(agent, verification, sources, local)


@pytest.mark.asyncio
async def test_literature_has_eight_cells_and_requires_selected_substantive_sources(
    products,
):
    agent, sources, _, _, screening = products
    validate_screening(agent, screening, sources)
    catalog = await ResearchTools().catalog(None)
    rows = coverage_table(screening, sources, catalog)
    assert len(rows) == 8 and sum(r.status == "covered" for r in rows) == 1
    assert next(r for r in rows if r.target == "dataset_discussion").destinations == [
        "2.3"
    ]
    screening.entries[0].reading_scope = "abstract"
    with pytest.raises(ValueError, match="abstract-only"):
        validate_screening(agent, screening, sources)
    screening.entries[0].decision = "deferred"
    validate_screening(agent, screening, sources)
    assert all(r.status == "gap" for r in coverage_table(screening, sources, catalog))


@pytest.mark.asyncio
async def test_repository_quality_and_links_cannot_be_invented(products):
    agent, sources, _, _, screening = products
    bad = deepcopy(screening)
    bad.entries[0].medium = "repository"
    with pytest.raises(ValueError, match="classification"):
        validate_screening(agent, bad, sources)
    bad = deepcopy(screening)
    bad.entries[0].quality.citations = 5000
    with pytest.raises(ValueError, match="citations"):
        validate_screening(agent, bad, sources)
    bad = deepcopy(screening)
    bad.entries[0].related_urls = ["https://example.org/repo"]
    with pytest.raises(ValueError, match="this source's links"):
        validate_screening(agent, bad, sources)


@pytest.mark.asyncio
async def test_plan_and_completion_keep_purposes_distinct(products):
    _, sources, _, _, _ = products
    plan = await WorkflowLLM().structured_output([{}, {"content": "{}"}], SurveyPlan)
    assert len(plan.verification) == 2 and len(plan.literature) == 8
    missing = missing_tasks(
        sources,
        plan.literature,
        await ResearchTools().catalog(None),
        "literature_review",
    )
    assert (
        len(missing) == 8
    )  # An already-read paper does not replace the purpose-specific searches.
    invalid = plan.model_dump()
    invalid["literature"] = [g for g in invalid["literature"] if g["medium"] == "paper"]
    with pytest.raises(ValueError, match="paper AND repository"):
        SurveyPlan.model_validate(invalid)


@pytest.mark.asyncio
async def test_downstream_receives_only_selected_literature_for_its_use(
    products, tmp_path
):
    _, sources, _, verification, screening = products
    discussion = screening.entries[0].model_copy(
        update={"id": "discussion", "target": "dataset_discussion"}
    )
    excluded = screening.entries[0].model_copy(
        update={"id": "excluded", "decision": "excluded"}
    )
    screening.entries.extend([discussion, excluded])
    review = LiteratureReview(
        **screening.model_dump(),
        criteria=SELECTION_CRITERIA,
        coverage=coverage_table(
            screening, sources, await ResearchTools().catalog(None)
        ),
        sources=[
            {"id": d.id, "title": d.title, "url": d.url} for d in sources.documents
        ],
    )
    write_readable(tmp_path / "survey/verification.json", verification.model_dump())
    write_readable(tmp_path / "survey/literature.json", review.model_dump())
    agent = make_cognition(tmp_path, Reader())
    assert [
        e["id"]
        for e in agent.survey_context({"dataset_discussion"})[
            "literature_for_this_stage"
        ]
    ] == ["discussion"]
    assert [
        e["id"]
        for e in agent.survey_context({"preprocessing_methods"})[
            "literature_for_this_stage"
        ]
    ] == ["entry-method"]


def test_official_source_discovery_accepts_author_repository_providers():
    from app.workflows.survey_research import available_tools
    catalog=[{'name':'papers','category':'literature','available':True},
             {'name':'github','category':'code','available':True},
             {'name':'disabled','category':'code','available':False}]
    assert available_tools(catalog,'official') == {'papers','github'}
    assert available_tools(catalog,'paper') == {'papers'}
    assert available_tools(catalog,'repository') == {'github'}
