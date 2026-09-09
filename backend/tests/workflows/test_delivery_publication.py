"""Atomic ZIP publication and portable, byte-exact evaluation evidence."""
# ruff: noqa: E402, F811

import hashlib
import json
from pathlib import Path
import zipfile

import pytest

pytest.importorskip("mne_bids")

from app.workflows import outputs
from app.workflows.artifacts import local_files
from tests.workflows.test_outputs_scaling import delivery_case  # noqa: F401


def test_archive_contains_complete_original_panel_and_predictions(delivery_case):
    case = delivery_case()
    selection = case.state["outputs"]["data_evaluation"]
    outputs.deliver(case.state, case.folder, case.store)
    with zipfile.ZipFile(case.folder.parent / "training-data.zip") as archive:
        panel = archive.read("evaluation/panel.json")
        predictions = archive.read("evaluation/originalpredictions.tsv")
        assert panel == (case.store.root.parent / "panel.json").read_bytes()
        assert (
            predictions
            == Path(selection["selected_receipt"]["predictions_path"]).read_bytes()
        )
        assert json.loads(panel)["trials"]
        assert hashlib.sha256(panel).hexdigest() == selection["panel"]["file_sha256"]
        assert (
            hashlib.sha256(predictions).hexdigest()
            == selection["selected_receipt"]["predictions_sha256"]
        )
        assert (
            json.loads(archive.read("evaluation/receipt.json"))
            == selection["selected_receipt"]
        )


@pytest.mark.parametrize(
    "problem", ["panel", "predictions", "panel_summary", "prediction_path"]
)
def test_corrupt_evaluation_evidence_blocks_publication(delivery_case, problem):
    case = delivery_case()
    selection = case.state["outputs"]["data_evaluation"]
    if problem == "panel":
        (case.store.root.parent / "panel.json").write_text("{}")
    elif problem == "predictions":
        Path(selection["selected_receipt"]["predictions_path"]).write_text("changed")
    elif problem == "panel_summary":
        selection["panel"]["trial_count"] += 1
    else:
        selection["selected_receipt"]["predictions_path"] = "../../other.tsv"
    with pytest.raises(ValueError):
        outputs.deliver(case.state, case.folder, case.store)
    assert not (case.folder.parent / "training-data.zip").exists()


@pytest.mark.parametrize("previous", [False, True])
@pytest.mark.parametrize(
    "failure", ["zip_write", "final_sources", "member_hash", "prediction_changed"]
)
def test_failed_archive_never_replaces_previous_or_becomes_visible(
    delivery_case, monkeypatch, previous, failure
):
    case = delivery_case()
    archive = case.folder.parent / "training-data.zip"
    if previous:
        outputs.deliver(case.state, case.folder, case.store)
    original_bytes = archive.read_bytes() if previous else None
    write = zipfile.ZipFile.write
    checks = outputs.check_sources
    calls = 0

    def check_sources(survey):
        nonlocal calls
        calls += 1
        if failure == "final_sources" and calls == 2:
            raise ValueError("source changed during export")
        return checks(survey)

    def write_member(z, filename, *args, **kwargs):
        assert Path(z.filename).suffix == ".tmp"
        assert (archive.read_bytes() if archive.exists() else None) == original_bytes
        if failure == "zip_write":
            raise OSError("injected ZIP write failure")
        if Path(filename).name == "X.npy" and failure == "member_hash":
            Path(filename).write_bytes(b"changed after manifest")
        if Path(filename).name == "X.npy" and failure == "prediction_changed":
            Path(
                case.state["outputs"]["data_evaluation"]["selected_receipt"][
                    "predictions_path"
                ]
            ).write_text("changed after evidence copy")
        return write(z, filename, *args, **kwargs)

    monkeypatch.setattr(outputs, "check_sources", check_sources)
    monkeypatch.setattr(zipfile.ZipFile, "write", write_member)
    with pytest.raises((ValueError, OSError)):
        outputs.deliver(case.state, case.folder, case.store)
    assert (archive.read_bytes() if archive.exists() else None) == original_bytes
    assert not list(case.folder.parent.glob(".training-data.zip.*.tmp"))
    visible = local_files(
        case.folder.parent, {"stages": [{"name": "data_delivery", "status": "failed"}]}
    )
    assert "training-data.zip" not in {a["name"] for a in visible}
    assert any(a["name"].startswith("delivery/") for a in visible)


def test_success_replaces_archive_only_after_final_validation(
    delivery_case, monkeypatch
):
    case = delivery_case()
    archive = case.folder.parent / "training-data.zip"
    archive.write_bytes(b"previous delivery")
    checks = outputs.check_sources
    replace = Path.replace
    validated = 0
    published = []

    def check_sources(survey):
        nonlocal validated
        checks(survey)
        validated += 1

    def replace_file(source, target):
        if Path(target) == archive:
            assert validated == 2
            assert archive.read_bytes() == b"previous delivery"
            with zipfile.ZipFile(source) as z:
                assert z.testzip() is None
            published.append(source)
        return replace(source, target)

    monkeypatch.setattr(outputs, "check_sources", check_sources)
    monkeypatch.setattr(Path, "replace", replace_file)
    result = outputs.deliver(case.state, case.folder, case.store)
    assert len(published) == 1
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == result["sha256"]
    for status in ("pending", "running", "failed", "interrupted"):
        visible = local_files(
            case.folder.parent,
            {"stages": [{"name": "data_delivery", "status": status}]},
        )
        assert "training-data.zip" not in {a["name"] for a in visible}
    visible = local_files(
        case.folder.parent,
        {"stages": [{"name": "data_delivery", "status": "completed"}]},
    )
    assert "training-data.zip" in {a["name"] for a in visible}
