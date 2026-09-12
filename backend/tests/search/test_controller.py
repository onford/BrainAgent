import asyncio
import json
from types import SimpleNamespace

import pytest

from app.preprocessing.schemas import PreprocessInput
from app.preprocessing.storage import digest, Storage
from app.search.catalog import BASELINE_ID, catalog, select
from app.search.contracts import Decision, SearchBudget, SearchRequest
from app.search.evaluation_contracts import EvaluationReceipt, LearnerMetadata
from app.search.io import read, write
from app.search.service import BudgetStop, SearchService
from tests.preprocessing.conftest import make_dataset


class Decisions:
    def __init__(self, actions=()):
        self.actions = list(actions)
        self.contexts = []

    async def structured_output(self, messages, schema):
        self.contexts.append(json.loads(messages[-1]["content"]))
        if not self.actions:
            return schema.model_validate(
                {
                    "decision": {
                        "action": "finish",
                        "reason": "没有新的可区分假设",
                        "unresolved": [],
                    }
                }
            )
        value = self.actions.pop(0)
        if isinstance(value, Exception):
            raise value
        if callable(value):
            value = value(self.contexts[-1])
        return schema.model_validate(value)


def propose(identity, parent=BASELINE_ID):
    return {
        "decision": {
            "action": "propose_candidate",
            "candidate_id": identity,
            "base_candidate_id": parent,
            "reason": "依据已有反馈改变频带或参考",
            "expected_result": "测量配对开发效用差",
            "hypothesis": {
                "explanation": "参考与频带可能改变跨人变化",
                "competing_explanation": "有用判别信息可能同时受损",
                "observations": [{"candidate_id": parent, "metric": "macro_ba"}],
                "predictions": [
                    {
                        "kind": "signal",
                        "metric": "diagnostics.floor_fraction",
                        "direction": "unchanged",
                        "explanation": "不引入平坦信号",
                    },
                    {
                        "kind": "utility",
                        "metric": "macro_ba",
                        "direction": "increase",
                        "explanation": "开发效用提升",
                    },
                ],
                "weakened_by": "信号符合预测但效用下降",
            },
            "decision_branches": {
                "improvement": "继续该方向",
                "no_improvement": "换参考或结束",
            },
        }
    }


class SimulatedSearch(SearchService):
    """Only numerical subprocesses are substituted; protocol/ledger/model loop are real."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.executed = []
        self.scores = {}
        self.failures = {}

    def create(self, owner, request, *, start=True):
        # These ledger tests simulate only the core numeric evaluator. The real
        # worker integration separately requires the complete multi-axis suite.
        value = super().create(owner, request, start=False)
        state = self.get(owner, value["id"])
        state["protocol"].pop("assessment", None)
        write(self.folder(value["id"]) / "protocol.json", state["protocol"])
        self.save(state)
        if start:
            self.start(owner, value["id"])
        return self.describe(owner, value["id"])

    async def child(self, state, stage, candidate_id=None):
        self.guard(state)
        root = self.folder(state["id"])
        if stage == "verify":
            return 0
        if stage == "prepare":
            write(
                root / "panel.json",
                {
                    "panel_hash": "test-panel",
                    "train_subjects": ["S001"],
                    "development_subjects": ["S002"],
                    "records": {},
                    "trials": [{"eligible": True}],
                    "output_contract": {
                        "sfreq": 160.0,
                        "tmin": 0.0,
                        "tmax": 1.0,
                        "channels": ["C3", "C4"],
                    },
                },
            )
            return 0
        self.executed.append(candidate_id)
        failure = self.failures.get(candidate_id)
        if isinstance(failure, list):
            failure = failure.pop(0) if failure else None
        score = self.scores.get(candidate_id, 0.5)
        delta = None if candidate_id == BASELINE_ID else score - 0.5
        coverage = {
            "original": 2,
            "eligible": 2,
            "available": 2,
            "predicted": 2,
            "missing": 0,
            "common_invalid": 0,
            "common_invalid_reasons": {},
        }
        value = (
            {"status": failure, "error": "injected failure"}
            if failure
            else {
                "status": "evaluated",
                "macro_ba": score,
                "mean_delta": delta,
                "evaluation_mode": "subject_holdout",
                "folds": [
                    {
                        "id": "fold-1",
                        "train_subjects": ["S001"],
                        "development_subjects": ["S002"],
                    }
                ],
                "secondary_macro_ba": score,
                "secondary_subjects": {"S002": score},
                "paired_subject_ci": None
                if delta is None
                else {"low": delta, "high": delta, "n_subjects": 1, "seed": 42},
                "learner_metadata": LearnerMetadata(
                    csp_components=2,
                    logistic_random_state=state["request"]["seed"],
                ).model_dump(mode="json"),
                "diagnostics": {
                    "floor_fraction": 0.0,
                    "subjects": {
                        subject: {
                            "channel_variance": [1e-12, 1e-12],
                            "channel_flat_fraction": [0.0, 0.0],
                            "covariance_condition": 1.0,
                            "covariance_condition_before": 1.0,
                            "covariance_condition_after": 1.0,
                            "mean_channel_variance_before": 1e-12,
                            "mean_channel_variance_after": 1e-12,
                            "effective_rank_before": 2,
                            "effective_rank_after": 2,
                        }
                        for subject in ("S001", "S002")
                    },
                    "summary": {
                        "mean_condition_before": 1.0,
                        "mean_condition_after": 1.0,
                        "mean_variance_before": 1e-12,
                        "mean_variance_after": 1e-12,
                        "gate_fraction": None,
                        "mean_effective_rank": 2.0,
                        "mean_anisotropy": 1.0,
                    },
                },
                "representation": {
                    "policy": {"adaptation": "none", "alignment_threshold": 10.0},
                    "unit": "V",
                    "transductive": False,
                    "channels": ["C3", "C4"],
                    "gate_subject_count": 0,
                    "gate_passed_subject_count": 0,
                    "gate_fraction": None,
                    "subjects": {
                        subject: {
                            "applied_adaptation": "none",
                            "gate_passed": False,
                            "covariance_anisotropy": 1.0,
                            "gate_metric_value": 1.0,
                            "fit_trials": 2,
                            "unit": "V",
                        }
                        for subject in ("S001", "S002")
                    },
                    "records": {
                        subject: {
                            "subject": subject,
                            "array_path": f"{subject}/signal_V.npy",
                            "array_sha256": "b" * 64,
                            "shape": [2, 2, 161],
                            "unit": "V",
                        }
                        for subject in ("S001", "S002")
                    },
                },
                "predictions_path": "originalpredictions.tsv",
                "predictions_sha256": "a" * 64,
                "versions": {
                    "worker_version": 1,
                    "search_engine_sha256": state["protocol"]["search_engine_hash"],
                    "engine_sha256": state["protocol"]["numeric_engine_hash"],
                    "environment_sha256": digest(state["protocol"]["environment"]),
                },
                "subjects": {
                    "S002": {
                        "ba": score,
                        "delta": delta,
                        "recalls": {"left": score, "right": score},
                        "recall_left": score,
                        "recall_right": score,
                        "original_trials": 2,
                        "eligible_trials": 2,
                        "available_trials": 2,
                        "predicted_trials": 2,
                        "missing": 0,
                    }
                },
                "coverage": {
                    **coverage,
                    "development": coverage,
                    "train": {**coverage, "predicted": 0},
                },
            }
        )
        value = EvaluationReceipt.model_validate(value).model_dump(mode="json")
        write(root / "candidates" / candidate_id / "receipt.json", value)
        write(
            root / "candidates" / candidate_id / "plan.json",
            {"estimated_disk_bytes": 1},
        )
        return 0


@pytest.fixture
def factory(tmp_path):
    original = make_dataset(tmp_path / "data")
    raw = original.model_dump(mode="json")
    raw["survey"].update(dataset_id="eegmmidb", task="left_right_motor_imagery")
    raw["collection"]["dataset_id"] = "eegmmidb"
    data = PreprocessInput.model_validate(raw)
    source = tmp_path / "source"
    write(source / "collection/input.json", data.model_dump(mode="json"))
    write(
        source / "survey/sources.json",
        {
            "documents": [
                {
                    "id": "source-1",
                    "title": "Methods",
                    "url": "https://example.org/method",
                    "text": "reference choice and filter context",
                    "sha256": "text-hash",
                }
            ]
        },
    )
    source_state = {
        "outputs": {
            "data_collection": {},
            "data_survey": {
                "records": [
                    {"id": r.id, "subject": f"S{i + 1:03}"}
                    for i, r in enumerate(data.collection.records)
                ]
            },
        },
        "request": {"tmin": 0.0, "tmax": 1.0},
    }
    workflows = SimpleNamespace(
        get=lambda *args: source_state,
        folder=lambda _: source,
        preprocessing=SimpleNamespace(allowed_roots=[tmp_path], store=Storage(tmp_path / 'evidence-store')),
        llm=None,
    )
    count = 0

    def create(actions=(), strategy="adaptive", **budget):
        nonlocal count
        count += 1
        llm = Decisions(actions)
        service = SimulatedSearch(tmp_path / f"searches{count}", workflows, llm)
        request = SearchRequest(
            workflow_id="a" * 32,
            strategy=strategy,
            budget=SearchBudget(
                **{**dict(max_candidates=6, max_proposals=8, max_retries=1), **budget}
            ),
        )
        state = service.create("owner", request, start=False)
        return service, llm, state

    return create


async def run(service, state):
    await service.run("owner", state["id"])
    return service.get("owner", state["id"])


@pytest.mark.asyncio
async def test_resume_rebuilds_interrupted_registry_projection_but_rejects_changed_entries(factory):
    service, _, state = factory(strategy="exhaustive", max_candidates=1)
    root = service.folder(state["id"])
    write(root / "registry.json", state["registry"][:1])
    completed = await run(service, state)
    assert completed["status"] == "stopped", completed.get("error")
    assert read(root / "registry.json") == completed["registry"]
    broken = read(root / "registry.json")
    broken[0]["title"] = "different content"
    write(root / "registry.json", broken)
    rejected = await run(service, completed)
    assert rejected["stop_reason"] == "integrity_failure"


@pytest.mark.asyncio
async def test_feedback_changes_next_candidate_and_fixed_tie_selection(factory):
    first = "basic-broadband"

    def next_action(context):
        score = context["results"][-1]["receipt"]["macro_ba"]
        if score <= 0.5:
            return propose("basic-acquisition-reference", first)
        result = propose(None, first)
        result["decision"].update(
            title="adjust broad-band lower edge",
            edits=[
                {
                    "action": "set_parameter",
                    "node_id": "bandpass",
                    "parameter": "l_freq",
                    "value": 4.0,
                }
            ],
        )
        return result

    chosen = []
    for score in (0.7, 0.4):
        service, llm, state = factory([propose(first), next_action], max_candidates=3)
        service.scores[first] = score
        result = await run(service, state)
        assert result["usage"]["candidates"] == 3
        assert result["stop_reason"] == "candidate_budget_exhausted"
        assert len(llm.contexts) == 2
        assert "trials" not in llm.contexts[1]["panel"]
        assert llm.contexts[1]["results"][-1]["receipt"]["macro_ba"] == score
        snapshots = sorted(service.folder(state["id"]).glob("decisions/*/request.json"))
        assert len(snapshots) == len(llm.contexts)
        assert [
            json.loads(read(p)["messages"][-1]["content"]) for p in snapshots
        ] == llm.contexts
        chosen.append(service.executed[-1])
    assert chosen[0].startswith("candidate-")
    assert chosen[1] == "basic-acquisition-reference"
    candidates = [
        {"id": e["id"], "receipt": {"status": "evaluated", "macro_ba": 0.5}}
        for e in reversed(catalog())
    ]
    assert select(candidates) == BASELINE_ID


@pytest.mark.asyncio
async def test_invalid_and_duplicate_proposals_consume_budget(factory):
    service, llm, state = factory(
        [propose(BASELINE_ID), propose("not-in-catalog")], max_proposals=2
    )
    result = await run(service, state)
    assert result["usage"]["proposals"] == 2
    assert result["usage"]["candidates"] == 1
    assert service.executed == [BASELINE_ID]
    assert result["stop_reason"] == "proposal_budget_exhausted"
    assert sum(a["status"] == "rejected" for a in result["actions"]) == 2


@pytest.mark.asyncio
async def test_schema_rejections_are_counted_without_extra_model_corrections(factory):
    service, _, state = factory(
        [{"decision": {"action": "propose_candidate"}}], max_proposals=1
    )
    result = await run(service, state)
    assert result["usage"]["llm_calls"] == result["usage"]["proposals"] == 1
    assert result["stop_reason"] == "proposal_budget_exhausted"


@pytest.mark.asyncio
async def test_evidence_read_budget_and_duplicate_are_durable(factory):
    evidence = {
        "decision": {
            "action": "request_evidence",
            "source_id": "source-1",
            "query": "reference",
            "question": "参考是什么",
            "affects_choice": "参考组合",
            "reason": "可能改变候选选择",
        }
    }
    service, _, state = factory(
        [evidence, evidence, evidence], max_evidence_reads=1, max_proposals=2
    )
    result = await run(service, state)
    assert result["usage"]["evidence_reads"] == 1
    assert result["usage"]["proposals"] == 2
    read_action = next(
        a
        for a in result["actions"]
        if a["action"] == "request_evidence" and a["status"] == "completed"
    )
    assert "reference" in read_action["result"]["excerpts"][0]


@pytest.mark.asyncio
async def test_reference_failure_stops_comparison_and_preserves_null_score(factory):
    service, llm, state = factory()
    service.failures[BASELINE_ID] = "candidate_invalid"
    result = await run(service, state)
    assert result["stop_reason"] == "reference_failed"
    assert result["selected_candidate_id"] is None
    assert not llm.contexts


@pytest.mark.asyncio
async def test_transient_retry_charged_but_successful_reference_never_reruns(factory):
    candidate = "basic-broadband"
    service, _, state = factory([propose(candidate)], max_candidates=2)
    service.failures[candidate] = ["execution_failure", None]
    result = await run(service, state)
    assert result["usage"]["retries"] == 1
    assert service.executed == [BASELINE_ID, candidate, candidate]
    assert result["candidates"][-1]["attempts"] == 2


@pytest.mark.asyncio
async def test_exhaustive_uses_catalog_order_and_candidate_budget(factory):
    service, llm, state = factory(max_candidates=3, strategy="exhaustive")
    result = await run(service, state)
    assert service.executed == [c["id"] for c in catalog()][:3]
    assert not llm.contexts
    assert result["usage"]["proposals"] == 2


@pytest.mark.asyncio
async def test_expired_resume_does_not_reset_budget_or_execute(factory):
    service, _, state = factory()
    saved = service.get("owner", state["id"])
    saved["deadline"] = 0
    service.save(saved)
    result = await run(service, state)
    assert result["stop_reason"] == "time_budget_exhausted"
    assert not service.executed


@pytest.mark.asyncio
async def test_resume_reuses_completed_candidate_and_rejects_changed_input(factory):
    service, _, state = factory()
    result = await run(service, state)
    assert result["status"] == "stopped"
    assert result["stop_reason"] == "proposal_budget_exhausted"
    result.update(status="interrupted")
    service.save(result)
    again = await run(service, state)
    assert service.executed == [BASELINE_ID]
    root = service.folder(state["id"])
    data = read(root / "input.json")
    data["collection"]["selection_reason"] = "changed"
    write(root / "input.json", data)
    again.update(status="interrupted")
    service.save(again)
    failed = await run(service, state)
    assert failed["status"] == "failed" and "冻结" in failed["error"]
    assert service.executed == [BASELINE_ID]


class ProcessCrash(BaseException):
    """Abrupt process loss, bypassing orderly cancellation/error handlers."""


def crash_at_candidate_checkpoint(service, identity, checkpoint):
    original_save = service.save

    def save(state):
        original_save(state)
        action = next(
            (
                a
                for a in state["actions"]
                if a["action"] == "propose_candidate" and a["candidate_id"] == identity
            ),
            None,
        )
        candidate = next((c for c in state["candidates"] if c["id"] == identity), None)
        if action is None:
            return
        hit = (
            checkpoint == "proposal"
            and action["status"] == "reserved"
            and candidate is None
            or checkpoint == "running"
            and candidate is not None
            and candidate["status"] == "running"
            or checkpoint == "receipt"
            and candidate is not None
            and candidate["status"] == "evaluated"
            and action["status"] != "completed"
        )
        if hit:
            raise ProcessCrash(checkpoint)

    service.save = save


@pytest.mark.asyncio
@pytest.mark.parametrize("checkpoint", ["proposal", "running", "receipt"])
async def test_resume_finishes_original_proposal_at_each_commit_boundary(
    factory, checkpoint
):
    parent, target = "basic-broadband", "basic-acquisition-reference"
    service, llm, state = factory(
        [propose(parent), propose(target, parent)], max_candidates=3
    )
    service.scores.update({parent: 0.8, target: 0.6})
    crash_at_candidate_checkpoint(service, target, checkpoint)
    with pytest.raises(ProcessCrash):
        await run(service, state)
    saved = service.get("owner", state["id"])
    original = next(a for a in saved["actions"] if a["candidate_id"] == target)
    assert original["status"] in {"reserved", "running"}
    completed = [a for a in saved["actions"] if a["status"] == "completed"]

    resumed = SimulatedSearch(service.root, service.workflows, llm)
    resumed.scores.update(service.scores)
    await resumed.resume()
    await resumed.tasks[state["id"]]
    result = resumed.get("owner", state["id"])
    action = next(a for a in result["actions"] if a["candidate_id"] == target)
    assert action["index"] == original["index"]
    assert action["request"] == original["request"]
    assert action["status"] == "completed" and action["error"] is None
    signal, utility = action["result"]["prediction_checks"]["checks"]
    assert signal["status"] == "matched" and signal["difference"] == 0
    assert utility["before"] == 0.8 and utility["after"] == 0.6
    assert utility["difference"] == pytest.approx(-0.2)
    assert (
        utility["status"] == "contradicted"
    )  # Against the named parent, not .5 baseline.
    history = action["result"]["recovery_history"]
    assert len(history) == 1 and history[0]["status"] == original["status"]
    assert history[0]["candidate_attempts"] == (0 if checkpoint == "proposal" else 1)
    assert len(result["actions"]) == len(saved["actions"])
    assert [
        a for a in result["actions"] if a["index"] in {c["index"] for c in completed}
    ] == completed
    assert result["usage"]["candidates"] == 3 and result["usage"]["proposals"] == 2
    assert result["usage"]["llm_calls"] == 2
    assert result["usage"]["retries"] == (1 if checkpoint == "running" else 0)
    assert service.executed + resumed.executed == [BASELINE_ID, parent, target]
    assert result["stop_reason"] == "candidate_budget_exhausted"


@pytest.mark.asyncio
async def test_retry_retains_interrupted_action_history_and_completes_checks(factory):
    target = "basic-broadband"
    service, llm, state = factory([propose(target)], max_candidates=2)
    entered = asyncio.Event()
    original_child = service.child

    async def child(state, stage, candidate_id=None):
        if stage == "candidate" and candidate_id == target:
            entered.set()
            await asyncio.Future()
        return await original_child(state, stage, candidate_id)

    service.child = child
    service.start("owner", state["id"])
    await asyncio.wait_for(entered.wait(), timeout=5)
    service.cancel("owner", state["id"])
    await service.tasks[state["id"]]
    saved = service.get("owner", state["id"])
    interrupted = next(a for a in saved["actions"] if a["candidate_id"] == target)
    assert interrupted["status"] == "interrupted" and interrupted["error"]
    assert all(
        c["status"] == "unavailable"
        for c in interrupted["result"]["prediction_checks"]["checks"]
    )

    resumed = SimulatedSearch(service.root, service.workflows, llm)
    resumed.scores[target] = 0.7
    resumed.retry("owner", state["id"])
    await resumed.tasks[state["id"]]
    result = resumed.get("owner", state["id"])
    action = next(a for a in result["actions"] if a["candidate_id"] == target)
    assert action["status"] == "completed" and action["error"] is None
    assert action["request"] == interrupted["request"]
    assert action["result"]["recovery_history"][0]["status"] == "interrupted"
    assert action["result"]["recovery_history"][0]["error"] == interrupted["error"]
    assert action["result"]["prediction_checks"]["checks"][1]["after"] == 0.7
    assert result["usage"]["retries"] == 1
    assert result["usage"]["proposals"] == 1 and result["usage"]["llm_calls"] == 1
    assert result["candidates"][-1]["attempts"] == 2
    assert resumed.executed == [target]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["candidate_invalid", "execution_failure", "resource_failure", "budget"]
)
async def test_resumed_failed_or_budget_stopped_action_has_no_measured_checks(
    factory, failure
):
    target = "basic-broadband"
    service, llm, state = factory([propose(target)], max_candidates=2)
    crash_at_candidate_checkpoint(service, target, "running")
    with pytest.raises(ProcessCrash):
        await run(service, state)
    resumed = SimulatedSearch(service.root, service.workflows, llm)
    if failure == "budget":
        original_child = resumed.child

        async def child(state, stage, candidate_id=None):
            if stage == "candidate" and candidate_id == target:
                raise BudgetStop("time_budget_exhausted")
            return await original_child(state, stage, candidate_id)

        resumed.child = child
    else:
        resumed.failures[target] = failure
    await resumed.resume()
    await resumed.tasks[state["id"]]
    result = resumed.get("owner", state["id"])
    action = next(a for a in result["actions"] if a["candidate_id"] == target)
    assert action["status"] == ("interrupted" if failure == "budget" else "failed")
    assert action["error"]
    checks = action["result"]["prediction_checks"]["checks"]
    assert len(checks) == 2
    for check in checks:
        assert check["status"] == "unavailable"
        assert (
            check["before"] is None
            and check["after"] is None
            and check["difference"] is None
        )
    assert result["usage"]["retries"] == 1 and result["usage"]["candidates"] == 2
    assert result["usage"]["proposals"] == 1
    assert result["candidates"][-1]["status"] != "evaluated"


def test_state_and_artifacts_are_owner_scoped(factory):
    service, _, state = factory()
    with pytest.raises(KeyError):
        service.get("another-owner", state["id"])
    with pytest.raises(ValueError):
        service.artifact("owner", state["id"], "../escape")


@pytest.mark.asyncio
async def test_terminal_state_waits_for_report_publication(factory, monkeypatch):
    from app.search import reporting

    original = reporting.render
    service, _, state = factory()

    def render(root, final):
        assert service.get("owner", state["id"])["status"] == "running"
        original(root, final)

    monkeypatch.setattr(reporting, "render", render)
    result = await run(service, state)
    assert result["status"] == "stopped"
    path = service.artifact("owner", state["id"], "selection.json")
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="校验"):
        service.artifact("owner", state["id"], "selection.json")


@pytest.mark.asyncio
async def test_publication_failure_does_not_publish_a_winner(factory, monkeypatch):
    from app.search import reporting

    service, _, state = factory()

    def fail(root, final):
        (root / "report.html").write_text("incomplete", encoding="utf-8")
        raise OSError("injected full disk")

    monkeypatch.setattr(reporting, "render", fail)
    result = await run(service, state)
    assert (
        result["status"] == "failed" and result["stop_reason"] == "publication_failed"
    )
    assert result["selected_candidate_id"] is None
    with pytest.raises(KeyError):
        service.artifact("owner", state["id"], "report.html")


def test_artifact_index_includes_numeric_files_and_logs_but_not_internal_state(factory):
    service, _, state = factory()
    root = service.folder(state["id"])
    for name in (
        "engine/records/a/epochs.fif",
        "candidate.log",
        "engine/preprocessing.db",
        "engine/preprocessing.db-wal",
        "search.lock",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    names = {a["name"] for a in service.describe("owner", state["id"])["artifacts"]}
    assert {"engine/records/a/epochs.fif", "candidate.log"} <= names
    assert (
        not {"engine/preprocessing.db", "engine/preprocessing.db-wal", "search.lock"}
        & names
    )


@pytest.mark.asyncio
async def test_provider_requests_are_charged_without_hidden_retries(factory):
    import httpx
    from app.llm.client import OpenAICompatibleClient
    from app.llm.config import LLMConfig

    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(503)

    service, _, state = factory()
    original = OpenAICompatibleClient(
        LLMConfig(api_key="test", base_url="https://llm.example/v1", model="test"),
        transport=httpx.MockTransport(handler),
    )
    service.llm = SearchService(service.root, service.workflows, original).llm
    result = await run(service, state)
    assert len(requests) == result["usage"]["llm_calls"] == 2
    assert result["usage"]["retries"] == 1
    assert result["status"] == "failed"


def test_action_schema_requires_both_decision_branches():
    proposal = propose("basic-broadband")
    del proposal["decision"]["decision_branches"]["no_improvement"]
    with pytest.raises(ValueError):
        Decision.model_validate(proposal)


@pytest.mark.asyncio
async def test_one_shot_schedule_is_frozen_before_reference_feedback(factory):
    service, llm, state = factory(
        [
            {
                "candidate_ids": ["basic-broadband", "basic-acquisition-reference"],
                "reason": "固定初始候选",
            }
        ],
        strategy="one_shot",
        max_candidates=3,
        max_proposals=2,
    )
    result = await run(service, state)
    assert result["usage"]["proposals"] == 2
    assert len(llm.contexts) == 1 and llm.contexts[0]["results"] == []
    assert service.executed == [
        BASELINE_ID,
        "basic-broadband",
        "basic-acquisition-reference",
    ]


@pytest.mark.asyncio
async def test_one_shot_can_include_reference_without_running_or_charging_it_twice(
    factory,
):
    plan = {
        "candidate_ids": [
            BASELINE_ID,
            "basic-broadband",
            "basic-acquisition-reference",
        ],
        "reason": "固定参考和两项对照",
    }
    service, llm, state = factory(
        [RuntimeError("temporary network failure"), plan],
        strategy="one_shot",
        max_candidates=3,
        max_proposals=2,
    )
    result = await run(service, state)
    assert result["usage"]["candidates"] == 3
    assert result["usage"]["proposals"] == 2
    assert result["usage"]["retries"] == 1
    assert result["usage"]["llm_calls"] == 2
    assert all(c["results"] == [] for c in llm.contexts)
    assert service.executed == [
        BASELINE_ID,
        "basic-broadband",
        "basic-acquisition-reference",
    ]


@pytest.mark.asyncio
async def test_model_timeout_stops_without_retry_or_budget_reset(factory):
    # Leave time for real protocol publication and the simulated reference;
    # this test targets timeout inside the model call, not setup exhaustion.
    service, _, state = factory(max_seconds=5)

    class Slow:
        async def structured_output(self, *args):
            await asyncio.sleep(30)

    service.llm = Slow()
    result = await run(service, state)
    assert result["stop_reason"] == "time_budget_exhausted"
    assert result["usage"]["retries"] == 0
    assert result["selected_candidate_id"] == BASELINE_ID


@pytest.mark.asyncio
async def test_model_budget_exhaustion_stops_with_measured_winner(factory):
    from app.llm.budget import BudgetExceeded
    service, llm, state = factory(actions=[BudgetExceeded('Persistent LLM budget exhausted: cumulative input bytes')])
    result = await run(service, state)
    assert result['status'] == 'stopped' and result['stop_reason'] == 'model_budget_exhausted'
    assert result['selected_candidate_id'] == BASELINE_ID
    assert len(llm.contexts) == 1 and result['usage']['retries'] == 0
    assert 'cumulative input bytes' in result['unresolved'][-1]


@pytest.mark.asyncio
async def test_cancel_interrupts_model_and_preserves_reserved_call_cost(factory):
    service, _, state = factory()
    entered = asyncio.Event()

    class Slow:
        async def structured_output(self, *args):
            entered.set()
            await asyncio.sleep(30)

    service.llm = Slow()
    service.start("owner", state["id"])
    await asyncio.wait_for(entered.wait(), timeout=5)
    service.cancel("owner", state["id"])
    await service.tasks[state["id"]]
    result = service.get("owner", state["id"])
    assert result["status"] == "cancelled"
    assert result["usage"]["llm_calls"] == 1 and result["usage"]["elapsed_seconds"] > 0
    assert all(a["status"] != "running" for a in result["actions"])


@pytest.mark.asyncio
async def test_cancel_numeric_work_preserves_budget_without_a_score(factory):
    service, _, state = factory()
    entered = asyncio.Event()
    original_child = service.child

    async def child(state, stage, candidate_id=None):
        if stage == "candidate":
            entered.set()
            await asyncio.sleep(30)
        return await original_child(state, stage, candidate_id)

    service.child = child
    service.start("owner", state["id"])
    await asyncio.wait_for(entered.wait(), timeout=5)
    service.cancel("owner", state["id"])
    await service.tasks[state["id"]]
    result = service.get("owner", state["id"])
    assert result["status"] == "cancelled"
    assert result["usage"]["candidates"] == 1
    assert result["candidates"][0]["status"] == "interrupted"
    assert result["candidates"][0]["receipt"] is None
    assert result["selected_candidate_id"] is None


@pytest.mark.asyncio
async def test_code_change_during_candidate_invalidates_mixed_version_result(
    factory, monkeypatch
):
    import app.search.service as module

    service, _, state = factory()
    original_child = service.child

    async def child(state, stage, candidate_id=None):
        outcome = await original_child(state, stage, candidate_id)
        if stage == "candidate":
            monkeypatch.setattr(module, "search_engine_hash", lambda: "changed-code")
        return outcome

    service.child = child
    result = await run(service, state)
    assert result["stop_reason"] == "integrity_failure"
    assert result["selected_candidate_id"] is None
    assert service.executed == [BASELINE_ID]


@pytest.mark.asyncio
async def test_expired_resume_cannot_reselect_unverified_cached_result(
    factory, monkeypatch
):
    import app.search.service as module

    service, _, state = factory()
    previous = await run(service, state)
    assert previous["selected_candidate_id"] == BASELINE_ID
    previous["status"] = "interrupted"
    service.save(previous)
    monkeypatch.setattr(module.time, "time", lambda: previous["deadline"] + 1)
    monkeypatch.setattr(module, "search_engine_hash", lambda: "changed-code")
    result = await run(service, previous)
    assert result["stop_reason"] == "time_budget_exhausted"
    assert result["selected_candidate_id"] is None
    assert "未完成历史产物校验" in result["error"]


@pytest.mark.asyncio
async def test_real_subprocess_rejects_undersized_panel_and_preserves_owner_boundary(factory, tmp_path):
    import httpx
    from fastapi import FastAPI
    from app.api.routes.searches import router

    fixture, _, _ = factory()
    service = SearchService(
        tmp_path / "real-subprocess", fixture.workflows, Decisions()
    )
    app = FastAPI()
    app.state.searches = service
    app.state.settings = SimpleNamespace(default_owner_id="owner")
    app.include_router(router, prefix="/api")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/searches",
            json={
                "workflow_id": "a" * 32,
                "strategy": "exhaustive",
                "budget": {"max_candidates": 2, "max_seconds": 60},
            },
        )
        assert response.status_code == 202, response.text
        identity = response.json()["id"]
        await asyncio.wait_for(service.tasks[identity], timeout=65)
        state = (await client.get(f"/api/searches/{identity}")).json()
        # The two-subject fixture cannot satisfy EEGNet's outer-train plus
        # independent early-stop split. Preparation must reject it, not fall
        # back to the historical CSP evaluator.
        assert state["status"] == "failed"
        assert "DataUnevaluable" in state["error"] and "EEGNet" in state["error"]
        assert state["selected_candidate_id"] is None
        frozen = await client.get(f"/api/searches/{identity}/artifacts/interpretation-guide.json?download=false")
        assert frozen.status_code == 200
        assert digest(frozen.json()) == state["protocol"]["interpretation_guide_hash"]
        current = await client.get("/api/searches/interpretation-guide")
        assert current.status_code == 200 and current.json() == frozen.json()
        assert (
            await client.get(
                f"/api/searches/{identity}", headers={"X-Brain-Agent-Owner-ID": "other"}
            )
        ).status_code == 404
        assert (await client.get(f"/api/searches/{identity}/artifacts/interpretation-guide.json", headers={"X-Brain-Agent-Owner-ID": "other"})).status_code == 404
