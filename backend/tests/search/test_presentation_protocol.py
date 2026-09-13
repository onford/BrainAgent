"""Frozen metadata/feedback checks; no numerical worker or real search is run."""

from copy import deepcopy

from app.search.contracts import SearchRequest
from app.search.initial_recommendation import SYSTEM
from app.search.service import SearchService
from tests.search.test_controller import factory  # noqa: F401


def test_new_service_freezes_eegnet_seed_protocol_and_two_workers(request, tmp_path, monkeypatch):
    existing, llm, _ = request.getfixturevalue("factory")()
    service = SearchService(tmp_path / "metadata-only", existing.workflows, llm)
    monkeypatch.setattr("app.search.service.os.cpu_count", lambda: 16)
    monkeypatch.setattr(service, "start", lambda *a: (_ for _ in ()).throw(AssertionError("must not start")))
    result = service.create("owner", SearchRequest(workflow_id="a"*32), start=False)
    protocol = result["protocol"]
    assert protocol["utility_execution"]["max_workers"] == 2
    training = protocol["utility_execution"]["eegnet_training"]
    assert training["max_epochs"] == 100 and training["patience"] == 15
    assert training["validation_fraction"] == .2
    assert protocol["utility_protocol"]["eegnet"]["training"] == training
    assert protocol["utility_protocol"]["eegnet"]["runtime"]["device"] == "cpu"
    assert protocol["utility_version"] == 2
    assert protocol["evaluator"] == "fixed-eegnet-three-seed-subject-macro-utility-v2"
    assert protocol["metric"] == "mean_subject_macro_ba_across_eegnet_seeds_17_42_2026"
    assert protocol["benchmark_evaluators"] == ["csp_lda"]
    assert protocol["assessment"]["schema_version"] == "assessment-v2"
    assert protocol["assessment"]["primary_suite"] == ["eegnet"]
    assert protocol["assessment"]["seeds"] == [17, 42, 2026]
    assert protocol["assessment"]["weighting"] == "equal_subjects_then_equal_seeds"
    assert not service.tasks and not service.children and not llm.contexts
