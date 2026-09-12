import json

from fastapi.testclient import TestClient
import pytest

from app.agents import build_agent_registry
from app.agents.data_preprocessing.classic_survey import ClassicPipelineSurveyAgent
from app.agents.data_survey.agent import DataSurveyAgent
from app.agents.orchestrator import Orchestrator
from app.agents.planner.agent import PlannerAgent
from app.core.config import Settings
from app.main import create_app
from app.preprocessing.methods import baseline_methods
from app.preprocessing.schemas import (
    Evidence,
    Paper,
    PlanRequest,
    Ref,
    SurveyLiteratureBundle,
)
from app.preprocessing.worker import Worker
from app.runtime.context import AgentContext, AgentTask
from app.tools.base import BaseTool, ToolResult
from app.tools.registry import ToolRegistry
from tests.fakes import ScriptedLLMClient, delegate
from .conftest import OWNER, PARAMETERS
from .test_execution import prepare

KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="


def test_api_plan_submit_worker_status_and_download(tmp_path, dataset):
    settings = Settings(
        database_url_override=f"sqlite+aiosqlite:///{tmp_path / 'chat.db'}",
        brain_agent_credential_encryption_key=KEY,
        preprocessing_root=str(tmp_path / "output"),
        preprocessing_input_roots=[dataset.collection.root],
    )
    app = create_app(settings, ScriptedLLMClient([]))
    headers = {"X-Brain-Agent-Owner-ID": OWNER}
    with TestClient(app) as client:
        input_reply = client.post(
            "/api/preprocessing/inputs",
            json=dataset.model_dump(mode="json"),
            headers=headers,
        )
        assert input_reply.status_code == 201, input_reply.text
        methods = client.get("/api/preprocessing/methods", headers=headers).json()
        reply = client.post(
            "/api/preprocessing/plans",
            json={
                "input_ref": input_reply.json(),
                "methods": [m["ref"] for m in methods],
                "mode": "validation",
                "parameters": PARAMETERS,
            },
            headers=headers,
        )
        assert reply.status_code == 201, reply.text
        plan_ref = reply.json()["plan_ref"]
        assert (
            client.get(
                f"/api/preprocessing/plans/{plan_ref['id']}/job", headers=headers
            ).json()
            is None
        )
        first = client.post(
            "/api/preprocessing/jobs", json={"plan_ref": plan_ref}, headers=headers
        )
        assert first.status_code == 202 and first.json()["status"] == "queued"
        job_id = first.json()["job_id"]
        assert (
            client.post(
                "/api/preprocessing/jobs", json={"plan_ref": plan_ref}, headers=headers
            ).json()["job_id"]
            == job_id
        )
        assert (
            client.get(
                f"/api/preprocessing/jobs/{job_id}",
                headers={"X-Brain-Agent-Owner-ID": "other"},
            ).status_code
            == 404
        )
    # API connection/lifespan is closed. The durable independent worker still runs.
    result = Worker(
        app.state.preprocessing.store, app.state.preprocessing.allowed_roots
    ).run_once()
    assert result.status == "completed"
    with TestClient(create_app(settings, ScriptedLLMClient([]))) as client:
        status = client.get(f"/api/preprocessing/jobs/{job_id}", headers=headers).json()
        record = status["records"][0]
        file_reply = client.get(
            f"/api/preprocessing/jobs/{job_id}/artifacts/{record['key']}/data-epo.fif",
            headers=headers,
        )
        assert file_reply.status_code == 200 and len(file_reply.content) > 10_000
        assert (
            client.get(
                f"/api/preprocessing/jobs/{job_id}/artifacts/{record['key']}/data-epo.fif",
                headers={"X-Brain-Agent-Owner-ID": "other"},
            ).status_code
            == 404
        )
        assert (
            client.get(
                "/api/preprocessing/plans/not-an-id", headers=headers
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/preprocessing/jobs",
                json={"plan_ref": {"id": "f" * 64, "sha256": "f" * 64}},
                headers=headers,
            ).status_code
            == 404
        )


@pytest.mark.asyncio
async def test_orchestrator_passes_structured_refs_and_does_not_evaluate_queued_data(
    service, dataset
):
    job, _, _ = prepare(service, dataset)
    decision = {
        **delegate("data_preprocessing", "submit frozen plan"),
        "inputs": {"action": "submit", "plan_ref": job.plan_ref.model_dump()},
    }
    llm = ScriptedLLMClient([decision, delegate("data_evaluation", "must not run")])
    registry = build_agent_registry(preprocessing=service)
    registry.register(PlannerAgent(llm))
    context = await Orchestrator(registry).execute(
        AgentContext(
            owner_id=OWNER, session_id="test", user_message="execute this plan"
        )
    )
    assert [r.agent_name for r in context.agent_results] == ["data_preprocessing"]
    assert context.agent_results[0].output["job_id"] == job.job_id
    assert context.plan.steps[0].status == "submitted"
    assert len(llm.responses) == 1


@pytest.mark.asyncio
async def test_survey_bundle_to_extracted_draft_to_real_execution(service, dataset):
    evidence = Evidence(
        source_url="fixture://paper",
        locator="Methods section",
        text="Bandpass EEG, apply average reference, epoch on events, then baseline.",
        source_version="1",
    )
    fulltext = service.store.put(
        OWNER, "evidence", {"content": evidence.text + " Additional methods."}
    )
    paper = Paper(
        paper_id="paper-1",
        title="Fixture literature",
        survey_bucket="preprocessing_papers",
        relation_to_dataset="same modality",
        inclusion_reason="known deterministic protocol",
        landing_url="fixture://paper",
        fulltext_ref=fulltext,
        evidence=[evidence],
    )
    bundle = SurveyLiteratureBundle(
        survey_run_id="survey-1",
        dataset_id="synthetic",
        dataset_version="1",
        papers=[paper], input_ref=service.register_input(OWNER, dataset),
        shared_output={"sfreq":160.,"tmin":PARAMETERS['tmin'],"tmax":PARAMETERS['tmax']},
    )
    context = AgentContext(
        owner_id=OWNER, session_id="test", user_message="extract literature"
    )
    published = await DataSurveyAgent(preprocessing=service).run(
        AgentTask(
            instruction="publish",
            inputs={"literature_bundle": bundle.model_dump(mode="json")},
        ),
        context,
    )
    assert (
        service.store.get(
            OWNER, Ref.model_validate(published.output["literature_ref"]), "literature"
        )["papers"][0]["paper_id"]
        == "paper-1"
    )
    method = baseline_methods()[0]
    draft=method.model_dump(mode="json",exclude={'evidence','evaluation_window'})
    for step in draft['recipe']:
        step['implementation_version']='2'
        step['params']={k:PARAMETERS[v.removeprefix('$profile.')] if isinstance(v,str) and v.startswith('$profile.') else v for k,v in step['params'].items()}
        if step['op']=='epoch':step['params']['picks']='$eeg_channels'
        step['parameter_sources']={k:{'origin':'target_binding' if isinstance(v,str) and v.startswith('$') else 'engineering',
            'evidence_indices':[],'rationale':'Explicit integration fixture setting'} for k,v in step['params'].items()}
    extraction={'branches':[{'branch_id':'fixture','analysis':'Fixture method','evidence_indices':[0],'method':draft}]}
    review={'claims':[{'claim_id':'fixture/'+step['id'],'status':'supported','evidence_index':0,'quote':evidence.text,
        'reason':'Simulated source reviewer for transport integration'} for step in draft['recipe']]}
    review['claims'].append({'claim_id':'fixture/__complete_source_branch','status':'supported','evidence_index':0,'quote':evidence.text,'reason':'Transport-only complete-branch test double'})
    service.methods.llm = ScriptedLLMClient([extraction,review])
    result = await service.methods.intake(OWNER, bundle)
    assert not result["supplement_requests"]
    extracted = service.store.get(OWNER, result["methods"][0], "method")
    assert extracted["source"] == "survey_literature" and extracted["status"] == "draft"
    assert extracted["evidence"][0]["text"] == evidence.text
    assert extracted["evidence"][0]["artifact_ref"] == fulltext.model_dump()
    extraction_input = json.loads(service.methods.llm.messages_seen[0][1]["content"])
    assert extraction_input["indexed_evidence"][0]["index"] == 0
    filter_contract = next(c for c in extraction_input["enabled_operations"] if c["op"] == "filter")
    assert "l_freq" in filter_contract["parameters"]["required"]
    assert filter_contract["parameters"]["additionalProperties"] is False
    plan_ref, plan = service.plan(
        OWNER,
        PlanRequest(
            input_ref=service.register_input(OWNER, dataset),
            methods=result["methods"],
            mode="validation",
            parameters=PARAMETERS,
        ),
    )
    service.submit(OWNER, plan_ref)
    assert Worker(service.store, service.allowed_roots).run_once().status == "completed"
    reused = await service.methods.intake(OWNER, bundle)
    assert reused["methods"] == result["methods"]
    assert len(service.methods.llm.messages_seen) == 2
    paper.fulltext_ref = None
    result = await service.methods.intake(OWNER, bundle)
    assert result["methods"] == []
    assert result["supplement_requests"][0]["paper_id"] == "paper-1"


@pytest.mark.asyncio
async def test_invalid_model_mapping_is_retained_as_blocked_draft(service, dataset):
    evidence = Evidence(source_url="fixture://paper", locator="Methods", text="Filter then reference.", source_version="1")
    paper = Paper(
        paper_id="invalid-mapping", title="Mapping regression", survey_bucket="preprocessing_papers",
        relation_to_dataset="same modality", inclusion_reason="regression test", landing_url=evidence.source_url,
        fulltext_ref=service.store.put(OWNER, "evidence", {"content": evidence.text}), evidence=[evidence],
    )
    method = baseline_methods()[0].model_dump(mode="json", exclude={"evidence", "evaluation_window"})
    for step in method['recipe']:
        step['implementation_version']='2'
        step['params']={k:PARAMETERS[v.removeprefix('$profile.')] if isinstance(v,str) and v.startswith('$profile.') else v for k,v in step['params'].items()}
        step['parameter_sources']={k:{'origin':'engineering','evidence_indices':[],'rationale':'Fixture'} for k in step['params']}
    method["recipe"][0]["params"] = {"cutoff_hz": 1, "picks": ["$eeg_channels"]}
    method["recipe"][1]["input"] = "future_step"
    method["output"] = "Filtered EEG in prose"
    extraction={'branches':[{'branch_id':'fixture','analysis':'Invalid fixture','evidence_indices':[0],'method':method}]}
    review={'claims':[{'claim_id':'fixture/'+step['id'],'status':'supported','evidence_index':0,'quote':evidence.text,
        'reason':'Transport-only test double'} for step in method['recipe']]}
    review['claims'].append({'claim_id':'fixture/__complete_source_branch','status':'supported','evidence_index':0,'quote':evidence.text,'reason':'Transport-only complete-branch test double'})
    service.methods.llm = ScriptedLLMClient([extraction,review,{'action':'retain_blocked','reason':'No source repair','question':'Missing mapping'}])
    result = await service.methods.intake(OWNER, SurveyLiteratureBundle(
        survey_run_id="mapping-test", dataset_id="synthetic", dataset_version="1", papers=[paper],
        input_ref=service.register_input(OWNER,dataset),
    ))
    extracted = service.store.get(OWNER, result["methods"][0], "method")
    blockers=[i['message'] for i in extracted['issues'] if i['severity']=='blocking']
    assert any(c.startswith("parameter contract: filter") for c in blockers)
    assert "collection binding must replace the whole parameter value: filter.picks" in blockers
    assert "invalid step dependencies: reference" in blockers
    assert "method output must reference a recipe step id" in blockers
    _, plan = service.plan(OWNER, PlanRequest(
        input_ref=service.register_input(OWNER, dataset), methods=result["methods"], mode="validation", parameters=PARAMETERS,
    ))
    assert plan.screening[0].status == "blocked" and plan.records == []


@pytest.mark.asyncio
async def test_classic_subagent_creates_versioned_drafts_with_evidence_gaps(service):
    method = baseline_methods()[0]
    llm = ScriptedLLMClient(
        [
            {
                "action": "finish",
                "rationale": "source collected",
                "summary": "Official MNE workflow reference.",
            },
            {
                "methods": [method.model_dump(mode="json")],
                "missing_items": ["Full author code version verification"],
            },
        ]
    )
    agent = ClassicPipelineSurveyAgent(llm, ToolRegistry(), service.store)
    result = await agent.update_library(
        AgentContext(owner_id=OWNER, session_id="library", user_message="research"),
        "classic EEG workflows",
    )
    assert len(result["methods"]) == 1
    draft = service.store.get(OWNER, result["methods"][0], "method")
    assert draft["status"] == "draft" and draft["checks"]
    assert "PREP" in llm.messages_seen[0][-1]["content"]


class FullTextTool(BaseTool):
    name, description = "fulltext_fixture", "Full-text fixture"

    async def execute(self, **kwargs):
        return ToolResult(
            success=True,
            output={
                "body": "A" * 50_000,
                "authorization": "Bearer secret",
                "nested": {
                    "api_key": "sensitive",
                    "url": "https://paper.test/?token=secret",
                },
            },
        )


@pytest.mark.asyncio
async def test_full_evidence_is_not_truncated_and_secrets_are_redacted(service):
    registry = ToolRegistry(evidence_store=service.store)
    registry.register(FullTextTool())
    context = AgentContext(owner_id=OWNER, session_id="evidence", user_message="search")
    result = await registry.execute("fulltext_fixture", context)
    evidence = service.store.get(
        OWNER, Ref.model_validate(result.metadata["evidence_ref"]), "evidence"
    )
    assert len(evidence["content"]["body"]) == 50_000
    assert len(result.output["body"]) < 50_000
    assert "secret" not in json.dumps(evidence) and "sensitive" not in json.dumps(
        evidence
    )


@pytest.mark.asyncio
async def test_accepted_agent_result_is_persisted_as_submitted_not_completed(tmp_path):
    from app.db.session import Database
    from app.db.repository.agent_run import AgentRunRepository
    from app.runtime.result import AgentResult
    from datetime import datetime

    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'chat.db'}")
    await db.create_tables()
    async for session in db.sessions():
        # Use the existing schema; the job lifecycle stays in preprocessing storage.
        from app.db.models import SessionModel

        model = SessionModel()
        session.add(model)
        await session.flush()
        run = await AgentRunRepository(session).create_from_result(
            "run",
            model.id,
            "submit",
            AgentResult(
                agent_name="data_preprocessing",
                success=True,
                output={"job_id": "job"},
                metadata={"execution_status": "submitted"},
            ),
            datetime.now(),
        )
        assert run.status == "submitted" and run.finished_at is None
    await db.dispose()
