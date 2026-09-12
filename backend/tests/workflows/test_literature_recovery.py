"""Unit doubles exercise recovery policy; these are not live literature evidence."""

from time import monotonic
from types import SimpleNamespace

import pytest

from app.preprocessing.literature import LiteratureExtraction, extraction_inputs
from app.preprocessing.schemas import Evidence
from app.preprocessing.service import PreprocessingService
from app.workflows.cognition_contracts import SourceDocument
from app.workflows.literature_recovery import recover, dependency_links
from tests.preprocessing.conftest import make_dataset
from tests.search.test_literature_space import branch, EVIDENCE


def test_repository_dependencies_need_literal_paths_and_preserve_origin():
    source = {"url": "https://api.github.com/repos/owner/repo/readme",
              "links": ["https://github.com/owner/repo/blob/main/README.md"]}
    evidence = [Evidence(source_url=source["url"], source_version="hash", locator="README offsets 10:80",
        text="Run pipeline.py using configs/full.yaml and read docs/methods.md. Do not invent paths.")]
    found = dependency_links(source, evidence)
    assert {row["url"] for row in found} == {
        "https://github.com/owner/repo/blob/main/configs/full.yaml", "https://github.com/owner/repo/blob/main/docs/methods.md",
        "https://github.com/owner/repo/blob/main/pipeline.py"}
    assert all(row["evidence_locator"] == evidence[0].locator for row in found)
    assert dependency_links({**source, "links": []}, evidence) == []


@pytest.mark.asyncio
async def test_targeted_read_repairs_parameter_and_keeps_located_supplement(tmp_path):
    data = make_dataset(tmp_path / "bids", subjects=3)
    broken = branch()
    broken["method"]["recipe"][0]["params"]["l_freq"] = "$profile.unresolved"
    broken["method"]["recipe"][0]["parameter_sources"]["l_freq"]["origin"] = "unresolved"
    extraction = LiteratureExtraction.model_validate({"branches": [broken]})
    source = {"url": "https://example.org/paper", "links": ["https://example.org/supplement"]}
    inputs = extraction_inputs(source, EVIDENCE, data, {"sfreq": 160., "tmin": 0., "tmax": 2.})
    prep = PreprocessingService(tmp_path / "methods", [data.collection.root])
    calls = []

    async def read(url, kind):
        calls.append(url)
        return SourceDocument(id="supplement", url=url, kind=kind, title="Unit test supplementary methods",
            retrieved_at="2026-09-12T00:00:00Z", sha256="b" * 64, links=[], truncated=False, text="The low cutoff is 6 Hz.")

    async def ask(operation, model, context, instruction, validate=None):
        if model.__name__ == 'SemanticReview':
            from tests.search.test_literature_space import review_double
            return review_double(model, context)
        if model.__name__ == "RecoveryAction":
            return model(action="read_source", reason="Resolve the missing cutoff", question="What is the low cutoff?", url=source["links"][0])
        assert context['allowed_evidence_indices'] == [row['index'] for row in context['indexed_evidence']] == [0, 1, 2]
        fixed = branch()
        fixed["evidence_indices"].append(2)
        fixed["method"]["recipe"][0]["parameter_sources"]["l_freq"]["evidence_indices"] = [2]
        value = model.model_validate({"branches": [fixed]})
        validate(value)
        return value

    cognition = SimpleNamespace(ask=ask, reader=SimpleNamespace(read=read), service=SimpleNamespace(preprocessing=prep), owner="owner")
    budget = {"used": 0, "max_actions": 1, "deadline": monotonic() + 60}
    result, evidence, log = await recover(cognition, extraction, inputs, list(EVIDENCE), data,
        {"workflow_id": "test", "kind": "literature"}, tmp_path / "recovery", budget)
    assert budget["used"] == 1 and calls == source["links"]
    assert result.branches[0].method.recipe[0].params["l_freq"] == 6.
    assert evidence[-1].artifact_ref and "offsets 0:" in evidence[-1].locator
    assert log[0]["status"] == "reextracted" and (tmp_path / "recovery/supplement-1.json").exists()
    assert extraction.branches[0].method.recipe[0].params["l_freq"] == "$profile.unresolved"


@pytest.mark.asyncio
async def test_budget_exhaustion_never_promotes_blocked_method(tmp_path):
    data = make_dataset(tmp_path / "bids")
    broken = branch()
    broken["prerequisites"] = [{"description": "Required EMG screening", "status": "missing", "evidence_indices": [0], "target_basis": "No EMG channels"}]
    extraction = LiteratureExtraction.model_validate({"branches": [broken]})
    inputs = extraction_inputs({"url": "https://example.org/paper"}, EVIDENCE, data, {"sfreq": 160., "tmin": 0., "tmax": 2.})
    result, _, log = await recover(None, extraction, inputs, list(EVIDENCE), data,
        {"workflow_id": "test"}, tmp_path / "recovery", {"used": 0, "max_actions": 0, "deadline": monotonic() + 60})
    assert result == extraction
    assert log[0]["status"] == "budget_exhausted"
    assert "EMG" in str(log[0]["blockers"])


@pytest.mark.asyncio
@pytest.mark.parametrize('source_window', [(-1., 4.), (.5, 2.5)])
async def test_executable_window_adapter_does_not_trigger_source_repair(tmp_path, source_window):
    from app.preprocessing.literature import materialize
    from app.search.literature_space import build_workflow_space
    from tests.search.test_literature_space import review_double, refs
    data = make_dataset(tmp_path / 'bids')
    value = branch()
    for step in value['method']['recipe']:
        step['implementation_version'] = '2'
    params = dict(events='$events', event_id='$event_id', picks='$eeg_channels',
                  tmin=source_window[0], tmax=source_window[1])
    value['method']['recipe'].append(dict(id='epochs', unit_id='EEG-EPOCH', op='epoch',
        implementation_version='2', input='car', evidence_indices=[0], params=params,
        parameter_sources={k:dict(origin='engineering', evidence_indices=[], rationale='Test fixture window') for k in params}))
    value['method']['output'] = 'epochs'
    extraction = LiteratureExtraction.model_validate({'branches':[value]})
    original = extraction.model_dump(mode='json')
    output = dict(sfreq=160., tmin=0., tmax=2.)
    inputs = extraction_inputs({'url':'https://example.org/paper'}, EVIDENCE, data, output)
    async def ask(operation, model, context, instruction, validate=None):
        assert model.__name__ == 'SemanticReview', 'Already executable adapter must not trigger scientific source repair'
        return review_double(model, context)
    identity = {'workflow_id':'test', 'source_id':'window'}
    budget = dict(used=0, max_actions=3, deadline=monotonic()+60)
    result, evidence, log = await recover(SimpleNamespace(ask=ask), extraction, inputs,
        list(EVIDENCE), data, identity, tmp_path/'recovery', budget)
    assert result.model_dump(mode='json') == original
    assert budget['used'] == 0 and log == []
    _, _, report = build_workflow_space(data, output, refs(materialize(result,evidence,data,identity)))
    assert [r['status'] for r in report['methods']] == ['blocked', 'eligible']
    assert report['methods'][1]['lineage']['fidelity'] == 'engineering_adaptation'
