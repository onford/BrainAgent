"""Real compiled BIDS processing, three-seed EEGNet utility, assessment and ZIP export."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
import zipfile

import joblib
import mne
from mne_bids import BIDSPath, write_raw_bids
import numpy as np
import pytest

from app.preprocessing.planner import compile_steps
from app.preprocessing.runner import run_record, verify_result
from app.preprocessing.schemas import ExecutionPlan, PlanRequest, PreprocessInput, RecordPlan
from app.preprocessing.storage import Storage, digest, file_hash, write_json
from app.search.assessment import assess_candidate
from app.search.evaluation import evaluate
from app.search.evaluation_contracts import EvaluationReceipt
from app.search.evaluation_numeric import covariance, csp_features
from app.search.method_space import basic_space, seed_entries, edited_entry
from app.search.panel import freeze_panel
from app.search.recipe_compiler import compile_recipe
from app.search.reconstruction_evaluation import freeze_probe_panel
from app.search.utility_evaluation import utility_protocol
from app.workflows import outputs, reporting
from app.workflows.context import evaluation_context
from app.workflows.contracts import EvaluationOutput
from app.workflows.dataset import PROFILE


@pytest.fixture(scope="module")
def real_delivery(tmp_path_factory):
    base = tmp_path_factory.mktemp("assessment-export")
    root = base / "bids"
    specs, sources = [], []
    fs, channels = 160.0, ["C3", "Cz", "C4"]
    for number in range(1, 4):
        subject, rid = f"S{number:03d}", f"S{number:03d}-R004"
        onsets = 5.0 + np.arange(8)*5
        rng = np.random.default_rng(number)
        x = rng.normal(0, 4e-6, (3, 7200))
        wave = np.sin(2*np.pi*10*np.arange(321)/fs)
        labels = ["left_hand", "right_hand"]*4
        for i, onset in enumerate(onsets):
            amplitude = np.array([2, 1, 5] if i % 2 else [5, 1, 2])*1e-6
            x[:, int(onset*fs):int(onset*fs)+321] += amplitude[:, None]*wave
        raw = mne.io.RawArray(x, mne.create_info(channels, fs, "eeg"), verbose="ERROR")
        raw.set_montage("standard_1020")
        raw.set_annotations(mne.Annotations(onsets, [2.0]*8, labels))
        bids = BIDSPath(root=root, subject=subject, run="4", task="mi", datatype="eeg")
        write_raw_bids(raw, bids, format="BrainVision", allow_preload=True,
                       event_id={"left_hand": 1, "right_hand": 2}, overwrite=True, verbose="ERROR")
        path = bids.copy().update(suffix="eeg", extension=".vhdr").fpath
        meta = json.loads(path.with_suffix(".json").read_text())
        meta.update(EEGReference="acquisition", SoftwareFilters={}, HardwareFilters={}, PowerLineFrequency=50)
        write_json(path.with_suffix(".json"), meta)
        specs.append(dict(id=rid, bids_path=path.relative_to(root).as_posix(), files={"pending": "0"*64},
                          sfreq=fs, samples=x.shape[1], channels=dict.fromkeys(channels, "eeg"),
                          channel_order=channels, reference="acquisition"))
        sources.append(dict(id=rid, subject=subject, source_path=path.relative_to(root).as_posix(), sha256=file_hash(path)))
    inventory = {p.relative_to(root).as_posix(): file_hash(p) for p in root.rglob("*") if p.is_file()}
    for spec in specs:
        spec["files"] = inventory.copy()
    evidence = dict(source_url="fixture:assessment-export", locator="synthetic-generator", text="Synthetic EEG", source_version="1")
    data = PreprocessInput.model_validate(dict(purpose="development_fixture",
        survey=dict(dataset_id="fixture", dataset_version="1", survey_run_id="fixture", task="mi",
                    event_id={"left_hand": 1, "right_hand": 2}, processing_history=[], facts=[evidence]),
        collection=dict(dataset_id="fixture", dataset_version="1", root=str(root), standard_version="1.9.0",
                        validation_evidence=evidence, selection_reason="all", selected_record_ids=[s["id"] for s in specs], records=specs)))
    panel = freeze_panel(data, {s["id"]: s["subject"] for s in sources}, seed=42, tmin=0., tmax=2., sfreq=160.)
    store = Storage(base / "search/engine")
    space = basic_space()
    seeds = seed_entries(space)
    entry = edited_entry(seeds[2], [dict(action="set_parameter", node_id="bandpass", parameter="l_freq", value=9.0)],
                         space, title="Dynamic nine Hz recipe", order=len(seeds))
    execution = {"eegnet_training": {"max_epochs": 2, "patience": 1, "batch_size": 8}}
    protocol = dict(version=3, space=space.model_dump(mode="json"), space_hash=digest(space.model_dump(mode="json")),
                    assessment=dict(primary_suite=["eegnet"], reconstruction_design="balanced"),
                    utility_execution=execution, utility_protocol=utility_protocol(execution=execution))
    write_json(store.root.parent / "protocol.json", protocol)
    write_json(store.root.parent / "registry.json", [*seeds, entry])
    write_json(store.root.parent / "panel.json", panel)
    probe = freeze_probe_panel(panel, design="balanced")
    write_json(store.root.parent / "probe-panel.json", probe)
    method = compile_recipe(entry, space, panel)
    method_ref = store.put("offline-search", "method", method.model_dump(mode="json"))
    input_ref = store.put("offline-search", "input", data.model_dump(mode="json"))
    plan = ExecutionPlan(request=PlanRequest(input_ref=input_ref, methods=[method_ref], mode="validation"),
        input_snapshot=data, screening=[], environment={}, engine_sha256="b"*64,
        records=[RecordPlan(method_ref=method_ref, record_id=r.id, steps=compile_steps(method, r, data, {}),
                            output=method.output, code_hashes={}) for r in data.collection.records])
    plan_ref = store.put("offline-search", "plan", plan.model_dump(mode="json"))
    job = store.submit("offline-search", plan_ref, plan)
    for config in plan.records:
        row = next(r for r in job.records if r["record_id"] == config.record_id)
        store.record_start(job.job_id, row["key"])
        produced = run_record(plan, config, root, store.root / config.record_id, store.root)
        assert verify_result(store.root, produced)
        store.record_finish(job.job_id, row["key"], "completed", produced)
    result = store.finish_job("offline-search", job.job_id)
    candidate_root = store.root.parent / "candidates" / entry["id"]
    core = evaluate(result, plan, store.root, panel, candidate_root, policy=entry["parameters"])
    assert core["status"] == "evaluated", core
    write_json(candidate_root / "core-receipts/a1.json", core)
    write_json(candidate_root / "result.json", result.model_dump(mode="json"))
    assessment = assess_candidate(plan, result, store.root, panel, entry, core, candidate_root / "assessment/a1", probe,
                                  utility_execution=execution)
    assert assessment["utility"]["status"] == "evaluated", assessment["utility"]
    assert assessment["quality"]["status"] in {"evaluated", "partial"}, assessment["quality"]
    assert assessment["reconstruction"]["status"] in {"evaluated", "partial"}, assessment["reconstruction"]
    receipt = EvaluationReceipt.model_validate(dict(core, candidate_id=entry["id"], job_id=result.job_id,
        plan_ref=plan_ref.model_dump(), assessment=assessment, assessment_path="assessment/a1",
        core_receipt_path="core-receipts/a1.json")).model_dump(mode="json")
    write_json(candidate_root / "receipt.json", receipt)
    panel_summary = {k: v for k, v in panel.items() if k != "trials"}
    panel_summary.update(file_sha256=file_hash(store.root.parent / "panel.json"), trial_count=len(panel["trials"]),
                         eligible_count=sum(t["eligible"] for t in panel["trials"]))
    search = dict(id="a"*32, status="completed", selected_candidate_id=entry["id"], request={"seed": 42},
                  protocol=protocol, panel=panel_summary, candidates=[dict(id=entry["id"], parameters=entry["parameters"],
                      status="evaluated", job_id=result.job_id, plan_ref=plan_ref.model_dump(), receipt=receipt)])
    selection = outputs.choose(search, plan, store)
    folder = base / "workflow/delivery"
    (folder.parent / "report").mkdir(parents=True)
    (folder.parent / "report/report.html").write_text(reporting.evaluation_summary(EvaluationOutput.model_validate(selection)), encoding="utf-8")
    state = dict(id="fixture", owner="offline-search", request=dict(seed=42, tmin=0., tmax=2.), outputs=dict(
        data_survey=dict(source_root=str(root), profile=PROFILE, records=sources), data_evaluation=selection,
        data_preprocessing=dict(job_id=result.job_id)))
    delivered = outputs.deliver(state, folder, store)
    return SimpleNamespace(base=base, store=store, plan=plan, result=result, search=search, selection=selection,
        state=state, folder=folder, candidate_root=candidate_root, assessment=assessment, entry=entry, delivered=delivered,
        source_hashes=inventory)


def test_real_dynamic_recipe_selected_and_all_models_downloadable(real_delivery):
    c = real_delivery
    assert c.entry["id"].startswith("candidate-")
    assert c.selection["score"] == c.assessment["selection_score"]
    with zipfile.ZipFile(c.folder.parent / "training-data.zip") as archive:
        manifest = json.loads(archive.read("manifest.json"))
        expected = {f["name"]: f for f in manifest["files"]}
        assert len(expected) == len(manifest["files"])
        assert set(archive.namelist()) == set(expected) | {"manifest.json"}
        for name, item in expected.items():
            assert not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts
            assert ":" not in name and "\\" not in name
            assert hashlib.sha256(archive.read(name)).hexdigest() == item["sha256"]
            assert len(archive.read(name)) == item["bytes"]
        for item in c.assessment["artifacts"]:
            assert expected["evaluation/assessment/a1/" + item["path"]]["sha256"] == item["sha256"]
        index = json.loads(archive.read("evaluation/assessment-index.json"))
        assert index["selection_score"] == c.selection["score"]
        assert str(c.base) not in json.dumps(index)
        utility = json.loads(archive.read(index["utility_receipt"]))
        attempt = c.candidate_root / "assessment/a1"
        def member(ref):
            relative = Path(ref["path"]).relative_to(attempt).as_posix()
            name = "evaluation/assessment/a1/" + relative
            assert expected[name]["sha256"] == ref["sha256"]
            return name
        assert utility["utility_version"] == 2
        assert utility["primary_suite"] == ["eegnet"]
        assert set(utility["learners"]) == {"eegnet", "csp_lda"}
        eegnet = utility["learners"]["eegnet"]
        assert eegnet["folds"] == []
        assert set(eegnet["seeds"]) == {"17", "42", "2026"}
        all_rows = json.loads(archive.read(member(eegnet["predictions"])))
        assert len(all_rows) == 3 * 24
        seed_scores = []
        for seed in [17, 42, 2026]:
            learner = eegnet["seeds"][str(seed)]
            assert learner["status"] == "evaluated" and learner["seed"] == seed
            predictions = json.loads(archive.read(member(learner["predictions"])))
            assert len(predictions) == 24
            assert [r for r in all_rows if r["seed"] == seed] == predictions
            assert index["learners"]["eegnet"]["seeds"][str(seed)]["predictions"]["path"] == member(learner["predictions"])
            replay_rows = []
            for fold in learner["folds"]:
                model_member = member(fold["model"])
                assert model_member.endswith("/model.pt")
                metadata = json.loads(archive.read(member(fold["metadata"])))
                assert metadata["train_subjects"] == fold["train_subjects"]
                assert metadata["development_subjects"] == fold["development_subjects"]
                fit_subjects = set(metadata["fit_subjects"])
                validation_subjects = set(metadata["validation_subjects"])
                assert fit_subjects and validation_subjects
                assert not fit_subjects & validation_subjects
                assert fit_subjects | validation_subjects == set(fold["train_subjects"])
                assert not (fit_subjects | validation_subjects) & set(fold["development_subjects"])
                assert set(metadata["normalization_fit_subjects"]) == fit_subjects
                rows = json.loads(archive.read(member(fold["predictions"])))
                from app.search.eegnet import predict_checkpoint

                inputs = json.loads(archive.read(member(utility["inputs"])))
                with outputs._mapped_npy(c.folder / member(inputs["arrays"]["representation"])) as array:
                    x = array[[r["array_index"] for r in rows]]
                    probability = predict_checkpoint(c.folder / model_member, x)
                assert probability.shape == (len(rows), 2)
                np.testing.assert_allclose(probability, [[r["proba_left"], r["proba_right"]] for r in rows], rtol=1e-5, atol=1e-7)
                predicted = np.asarray(["left_hand", "right_hand"])[probability.argmax(axis=1)]
                assert list(predicted) == [r["prediction"] for r in rows]
                replay_rows.extend(dict(r, prediction=str(p)) for r, p in zip(rows, predicted))
            subject_ba = []
            for subject in sorted({r["subject"] for r in replay_rows}):
                recalls = []
                for label in ("left_hand", "right_hand"):
                    subset = [r for r in replay_rows if r["subject"] == subject and r["label"] == label]
                    assert subset
                    recalls.append(sum(r["prediction"] == label for r in subset) / len(subset))
                subject_ba.append(sum(recalls) / 2)
            seed_scores.append(sum(subject_ba) / len(subject_ba))
        assert c.selection["score"] == pytest.approx(float(np.mean(seed_scores)))
        assert index["seed_summary"]["mean_ba"] == pytest.approx(float(np.mean(seed_scores)))
        assert index["seed_summary"]["seed_sd"] == pytest.approx(float(np.std(seed_scores)))
        # CSP remains a separately replayable hard-prediction anchor.
        csp = utility["learners"]["csp_lda"]
        assert csp["seeds"] == {} and csp["seed_summary"] is None
        for fold in csp["folds"]:
            rows = json.loads(archive.read(member(fold["predictions"])))
            model = joblib.load(c.folder / member(fold["model"]))
            inputs = json.loads(archive.read(member(utility["inputs"])))
            with outputs._mapped_npy(c.folder / member(inputs["arrays"]["representation"])) as array:
                x = array[[r["array_index"] for r in rows]]
                replay = model["classifier"].predict(csp_features(np.array([covariance(v) for v in x]), model["filters"]))
            assert list(replay) == [r["prediction"] for r in rows]
        for name in ("core-receipts/a1.json", "candidate.json", "plan.json", "result.json", "registry.json", "search-protocol.json", "probe-panel.json"):
            assert "evaluation/" + name in expected
    assert c.source_hashes == {name: file_hash(c.base / "bids" / name) for name in c.source_hashes}


def test_report_and_context_use_three_seed_score(real_delivery):
    c = real_delivery
    message = reporting.evaluation_summary(EvaluationOutput.model_validate(c.selection))
    assert f"selection_score：{c.selection['score']:.4f}" in message
    assert "EEGNet" in message and "核心 CSP 锚点" in message
    assert "FBCSP=" not in message and "TS/LR=" not in message
    assert "主评价器" not in message
    compact = evaluation_context(c.selection)
    assert compact["assessment"]["utility"]["learner_coverage"] == c.assessment["utility"]["learner_coverage"]
    serialized = json.dumps(compact)
    assert "receipt_artifact" not in serialized and "artifact_manifest" not in serialized
    assert "primary_learner" not in compact["metrics"]
    wrong = deepcopy(c.selection)
    wrong["score"] = 0.123
    with pytest.raises(ValueError):
        reporting.evaluation_summary(EvaluationOutput.model_validate(wrong))


@pytest.mark.parametrize('change', ['score', 'claim', 'hash', 'candidate'])
def test_conclusion_projection_cannot_promote_or_detach_evidence(real_delivery, change):
    selected = deepcopy(real_delivery.selection)
    qualification = selected['conclusion_eligibility']
    assert qualification['primary_development_score'] == selected['score']
    claims = {c['id']: c for c in qualification['claims']}
    assert claims['development_predictability']['status'] == 'supported_within_scope'
    assert claims['independent_generalization']['status'] == 'not_established'
    if change == 'score':
        qualification['primary_development_score'] = .123
    elif change == 'claim':
        claims['neural_preservation']['status'] = 'supported_within_scope'
    elif change == 'hash':
        qualification['selected_assessment_sha256'] = '0' * 64
    else:
        qualification['selected_candidate_id'] = 'another'
    with pytest.raises(ValueError, match='conclusion eligibility'):
        EvaluationOutput.model_validate(selected)


def test_dynamic_registry_and_required_assessment_cannot_be_bypassed(real_delivery):
    c = real_delivery
    for change in ("missing_assessment", "wrong_parameters", "wrong_winner"):
        search = deepcopy(c.search)
        candidate = search["candidates"][0]
        if change == "missing_assessment":
            candidate["receipt"]["assessment"] = None
        elif change == "wrong_parameters":
            candidate["parameters"]["adaptation"] = "euclidean_alignment"
        else:
            search["selected_candidate_id"] = "bp8-30-average"
        with pytest.raises(ValueError):
            outputs.choose(search, c.plan, c.store)
    # Explicitly reject a missing registry; never infer a static fallback.
    registry = c.store.root.parent / "registry.json"
    saved = registry.read_bytes()
    try:
        registry.unlink()
        with pytest.raises(FileNotFoundError):
            outputs.choose(c.search, c.plan, c.store)
    finally:
        registry.write_bytes(saved)


def test_rendered_html_labels_actual_utility_and_core_anchor(real_delivery, tmp_path, monkeypatch):
    from app.workflows.contracts import ReportData

    c = real_delivery
    method = c.store.get("offline-search", c.plan.request.methods[0], "method")
    stats = dict(subjects=3, recordings=3, trials=24, duration_s=135., unknown_recordings=0)
    data = ReportData(dataset_name="Synthetic EEG", dataset_version="1", license="fixture", subjects=["S001", "S002", "S003"],
        runs=[4], sfreq=160., channel_count=3, before=stats, after=stats,
        method=dict(ref=c.plan.request.methods[0], title=method["title"], recipe=method["recipe"]),
        records=[], selection_reason=c.selection["reason"], seed=42, selection=c.selection, references=[], limitations=[])
    # Only the report's stage reader is replaced with a strict typed record;
    # selection, metrics and serialization come from the real numerical run.
    monkeypatch.setattr(reporting, "report_data", lambda _: data)
    reporting.render_report(tmp_path / "report")
    document = (tmp_path / "report/report.html").read_text(encoding="utf-8")
    assert "EEGNet" in document and "selection_score" in document
    assert f"{c.selection['score']:.4f}" in document
    assert "核心 CSP 锚点" in document and "主评价器" not in document


@pytest.mark.parametrize("relative", ["core-receipts/a1.json", "result.json", "assessment/a1/utility/utility.json"])
def test_actual_native_tampering_prevents_reexport(real_delivery, relative):
    c = real_delivery
    path = c.candidate_root / relative
    before, archive_hash = path.read_bytes(), file_hash(c.folder.parent / "training-data.zip")
    try:
        path.write_text("{}", encoding="utf-8")
        with pytest.raises((ValueError, KeyError)):
            outputs.deliver(c.state, c.folder, c.store)
        assert file_hash(c.folder.parent / "training-data.zip") == archive_hash
    finally:
        path.write_bytes(before)


@pytest.mark.parametrize("seed", ["17", "42", "2026"])
@pytest.mark.parametrize("kind", ["model", "metadata", "predictions"])
def test_each_seed_fold_artifact_is_required_for_reexport(real_delivery, seed, kind):
    c = real_delivery
    utility = json.loads((c.candidate_root / "assessment/a1/utility/utility.json").read_text(encoding="utf-8"))
    ref = utility["learners"]["eegnet"]["seeds"][seed]["folds"][0][kind]
    path = Path(ref["path"])
    if not path.is_absolute():
        path = c.candidate_root / "assessment/a1/utility" / path
    before = path.read_bytes()
    archive_hash = file_hash(c.folder.parent / "training-data.zip")
    try:
        path.write_bytes(b"corrupted seed artifact")
        with pytest.raises((ValueError, OSError)):
            outputs.deliver(c.state, c.folder, c.store)
        assert file_hash(c.folder.parent / "training-data.zip") == archive_hash
    finally:
        path.write_bytes(before)


@pytest.mark.parametrize("change", ["missing_seed", "wrong_seed", "ensemble_score", "missing_inventory", "wrong_hash", "escape"])
def test_seed_export_index_rejects_unbound_or_partial_evidence(real_delivery, change):
    c = real_delivery
    root = c.candidate_root / "assessment/a1"
    utility = json.loads((root / "utility/utility.json").read_text(encoding="utf-8"))
    inventory = deepcopy(c.assessment["artifacts"])
    eegnet = utility["learners"]["eegnet"]
    if change == "missing_seed":
        del eegnet["seeds"]["2026"]
    elif change == "wrong_seed":
        eegnet["seeds"]["17"]["seed"] = 42
    elif change == "ensemble_score":
        utility["selection_score"] = (utility["selection_score"] + .25) % 1
    elif change == "missing_inventory":
        inventory = []
    elif change == "wrong_hash":
        eegnet["seeds"]["17"]["folds"][0]["model"]["sha256"] = "0" * 64
    else:
        eegnet["seeds"]["17"]["folds"][0]["model"]["path"] = str(root.parent / "outside.pt")
    with pytest.raises((ValueError, OSError)):
        outputs._utility_export_index(root, utility, "evaluation/assessment/a1/", inventory)


@pytest.mark.parametrize("target", ["bids", "search/engine", "search/candidates"])
def test_export_cannot_overwrite_real_sources(real_delivery, target):
    c = real_delivery
    with pytest.raises(ValueError, match="重叠"):
        outputs.deliver(c.state, c.base / target, c.store)
    assert c.source_hashes == {name: file_hash(c.base / "bids" / name) for name in c.source_hashes}


def test_operator_usage_native_delivery_and_tamper_bindings(real_delivery, tmp_path):
    from app.search.operator_usage import aggregate_operator_usage

    c = real_delivery
    # Aggregate the actual plan/result and provenance, including any evidence
    # issues; the exporter must preserve these native counts without re-scoring.
    native = aggregate_operator_usage(c.plan, c.result, c.store.root)
    relative = "operator-usage/u1.json"
    path = c.candidate_root / relative
    write_json(path, native)
    original = path.read_bytes()
    usage = dict(summary=native["summary"], artifact=dict(path=relative, sha256=file_hash(path), bytes=len(original)))
    state = deepcopy(c.state)
    state["outputs"]["data_evaluation"]["selected_receipt"]["operator_usage"] = usage
    folder = tmp_path / "delivery"
    (tmp_path / "report").mkdir()
    (tmp_path / "report/report.html").write_bytes((c.folder / "report.html").read_bytes())
    outputs.deliver(state, folder, c.store)
    archive_path = tmp_path / "training-data.zip"
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        files = {f["name"]: f for f in manifest["files"]}
        assert len(files) == len(manifest["files"])
        assert set(archive.namelist()) == set(files) | {"manifest.json"}
        index = json.loads(archive.read("evaluation/assessment-index.json"))
        member = index["operator_usage"]
        assert member == "evaluation/" + relative
        assert archive.read(member) == original
        assert files[member] == dict(name=member, sha256=usage["artifact"]["sha256"], bytes=len(original))
        exported = json.loads(archive.read(member))
        receipt = json.loads(archive.read("evaluation/receipt.json"))
        assert exported["summary"] == receipt["operator_usage"]["summary"]
        assert exported["plan_sha256"] == digest(json.loads(archive.read("evaluation/plan.json")))
        assert exported["result_sha256"] == digest(json.loads(archive.read("evaluation/result.json")))
        assert "evaluation/" + receipt["operator_usage"]["artifact"]["path"] in files
        assert str(c.base) not in json.dumps(index)
    archive_hash = file_hash(archive_path)
    try:
        for tamper in ("sha", "bytes", "summary", "plan", "result", "escape"):
            path.write_bytes(original)
            bad = deepcopy(state)
            altered = bad["outputs"]["data_evaluation"]["selected_receipt"]["operator_usage"]
            if tamper == "sha":
                altered["artifact"]["sha256"] = "0"*64
            elif tamper == "bytes":
                altered["artifact"]["bytes"] += 1
            elif tamper == "summary":
                altered["summary"]["evidence_issue_records"] = (native["summary"]["evidence_issue_records"] + 1) % (len(c.plan.records) + 1)
            elif tamper == "escape":
                altered["artifact"]["path"] = "../../../outside.json"
            else:
                changed = deepcopy(native)
                changed[tamper + "_sha256"] = "0"*64
                write_json(path, changed)
                # Even an attacker who updates the file ref cannot rebind the
                # usage report to a different executed plan or result.
                altered["artifact"].update(sha256=file_hash(path), bytes=path.stat().st_size)
            with pytest.raises(ValueError):
                outputs.deliver(bad, folder, c.store)
            assert file_hash(archive_path) == archive_hash
    finally:
        path.write_bytes(original)
    assert c.source_hashes == {name: file_hash(c.base / "bids" / name) for name in c.source_hashes}
