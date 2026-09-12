"""Delivery regressions using temporary artifacts; no services or historical runs."""

# Optional EEG imports are required by outputs' existing integrity verifier.
# ruff: noqa: E402
import csv
import json
import zipfile
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("mne")
pytest.importorskip("mne_bids")

from app.preprocessing.methods import baseline_methods
from app.preprocessing.storage import digest, file_hash
from app.search.evaluation_contracts import EvaluationReceipt, LearnerMetadata
from app.search.method_space import basic_space, seed_entries
from app.workflows import outputs
from app.workflows.contracts import DeliveryOutput
from app.workflows.dataset import PROFILE
from app.workflows.formats import ARRAY_FORMATS, DELIVERY_FILES, PROVENANCE_FILES


def numeric_metadata(receipt, representation):
    from app.search.evaluation_contracts import CoreLearnerMetadata
    receipt.update(evaluator_version=4, secondary_learner=None, secondary_macro_ba=None, secondary_subjects={})
    receipt["representation"] = {"version": "2", **{k: representation[k] for k in ("unit", "channels", "records")}}
    receipt["learner_metadata"] = CoreLearnerMetadata(csp_components=2).model_dump(mode="json")
    receipt["diagnostics"] = {}


def complete_delivery_receipt(store, selection):
    records = store.status("test", "test-job").records
    counts = Counter()
    arrays = {}
    for record in records:
        rid = record["record_id"]
        subject = selection["panel"]["records"][rid]["subject"]
        shape = record["result"]["delta"]["after"]["shape"]
        source = next(
            a for a in record["result"]["artifacts"] if a["name"] == "signal_V.npy"
        )
        counts[subject] += shape[0]
        arrays[rid] = dict(
            subject=subject,
            array_path=str(store.root / source["path"]),
            array_sha256=source["sha256"],
            shape=shape,
            unit="V",
        )
    rep = dict(version="2", unit="V", channels=["C3", "C4"], records=arrays)
    receipt = selection["selected_receipt"]

    def coverage(n, predicted):
        return dict(
            original=n,
            eligible=n,
            available=n,
            predicted=predicted,
            missing=0,
            common_invalid=0,
            common_invalid_reasons={},
        )

    total = sum(counts.values())
    receipt.update(
        evaluation_mode=selection["panel"]["evaluation_mode"],
        folds=selection["panel"]["folds"],
        secondary_macro_ba=0.5,
        secondary_subjects={s: 0.5 for s in counts},
        subjects={
            s: dict(
                recalls={"left": 0.5, "right": 1.0},
                recall_left=0.5,
                recall_right=1.0,
                ba=0.75,
                delta=None,
                original_trials=n,
                eligible_trials=n,
                available_trials=n,
                predicted_trials=n,
                missing=0,
            )
            for s, n in counts.items()
        },
        coverage={
            **coverage(total, total),
            "development": coverage(total, total),
            "train": coverage(0, 0),
        },
    )
    numeric_metadata(receipt, rep)
    selection["selected_receipt"] = EvaluationReceipt.model_validate(
        receipt
    ).model_dump(mode="json")
    selection["representation"] = selection["selected_receipt"]["representation"]


def freeze_evidence(store, selection):
    if not (store.root.parent / "registry.json").exists():
        space = basic_space().model_dump(mode="json")
        (store.root.parent / "protocol.json").write_text(json.dumps(dict(space=space, space_hash=digest(space))), encoding="utf-8")
        (store.root.parent / "registry.json").write_text(json.dumps(seed_entries(space)), encoding="utf-8")
    panel = {
        k: v
        for k, v in selection["panel"].items()
        if k not in {"panel_hash", "file_sha256", "trial_count", "eligible_count"}
    }
    panel["trials"] = [
        {"event_id": f"{rid}:trial-{index}", "record_id": rid, "eligible": True}
        for rid in panel["records"]
        for index in range(2)
    ]
    panel["panel_hash"] = digest(panel)
    path = store.root.parent / "panel.json"
    path.write_text(json.dumps(panel, indent=2) + "\n", encoding="utf-8")
    selection["panel"] = {
        **{k: v for k, v in panel.items() if k != "trials"},
        "file_sha256": file_hash(path),
        "trial_count": len(panel["trials"]),
        "eligible_count": len(panel["trials"]),
    }
    selection["selected_receipt"]["panel_hash"] = panel["panel_hash"]
    predictions = (
        store.root.parent
        / "candidates"
        / selection["selected_candidate_id"]
        / "originalpredictions.tsv"
    )
    predictions.parent.mkdir(parents=True, exist_ok=True)
    predictions.write_text(
        "event_id\tprediction\n"
        + "".join(
            f"{t['event_id']}\t{index % 2}\n" for index, t in enumerate(panel["trials"])
        ),
        encoding="utf-8",
    )
    selection["selected_receipt"].update(
        predictions_path=str(predictions), predictions_sha256=file_hash(predictions)
    )


@pytest.fixture
def delivery_case(tmp_path, monkeypatch):
    def make(specs=(("S003", 5), ("S001", 7), ("S001", 3), ("S002", 4))):
        root = tmp_path / "preprocessing"
        source_root = tmp_path / "sources"
        source_root.mkdir()
        method_ref = {"id": "a" * 64, "sha256": "b" * 64}
        records, sources, expected = [], [], {}
        for index, (subject, count) in enumerate(specs):
            record_id = f"{subject}-R{index:03}"
            directory = root / record_id
            directory.mkdir(parents=True)
            values = (
                np.arange(count * 2 * 7, dtype=np.float64).reshape(count, 2, 7)
                + index * 1000
            ) / 1e6
            # Exercise both Fortran and C input layouts and float64 conversion.
            np.save(
                directory / "signal_V.npy",
                np.asfortranarray(values) if index % 2 else values,
            )
            expected[record_id] = values.astype(np.float32)
            events = [
                {
                    "retained": True,
                    "epoch_index": epoch,
                    "label": "left_hand" if epoch % 2 == 0 else "right_hand",
                    "event_id": f"{record_id}-event-{epoch}",
                    "original_sample": 100 + epoch * 20,
                }
                for epoch in range(count)
            ]
            events.reverse()
            events.insert(0, {"retained": False, "epoch_index": None})
            info = {"channels": ["C3", "C4"], "sfreq": 160, "shape": list(values.shape)}
            delta = {"after": info}
            for name, data in (
                ("events.json", events),
                ("delta.json", delta),
                ("provenance.json", {"record_id": record_id}),
            ):
                (directory / name).write_text(json.dumps(data), encoding="utf-8")
            records.append(
                {
                    "record_id": record_id,
                    "method_id": method_ref["id"],
                    "status": "completed",
                    "result": {
                        "delta": delta,
                        "artifacts": [
                            {
                                "name": name,
                                "path": f"{record_id}/{name}",
                                "sha256": file_hash(directory / name),
                            }
                            for name in ("signal_V.npy", *PROVENANCE_FILES)
                        ],
                    },
                }
            )
            source = source_root / f"{record_id}.edf"
            source.write_bytes(record_id.encode())
            sources.append(
                {
                    "id": record_id,
                    "subject": subject,
                    "source_path": source.name,
                    "sha256": file_hash(source),
                }
            )
        records.reverse()  # Delivery order must depend on record IDs.
        subjects = sorted({s for s, _ in specs})
        panel = {
            "panel_hash": "c" * 64,
            "evaluation_mode": "group_cross_validation",
            "records": {r["id"]: {"subject": r["subject"]} for r in sources},
            "folds": [
                {
                    "id": f"fold-{i}",
                    "train_subjects": [s for s in subjects if s != subject],
                    "development_subjects": [subject],
                }
                for i, subject in enumerate(subjects)
            ],
        }
        state = {
            "id": "test-delivery",
            "owner": "test",
            "request": {"seed": 42, "tmin": 0, "tmax": 6 / 160},
            "outputs": {
                "data_survey": {
                    "source_root": str(source_root),
                    "profile": PROFILE,
                    "records": sources,
                },
                "data_evaluation": {
                    "selection_policy": "development_score",
                    "quality_evaluated": True,
                    "search_id": "a" * 32,
                    "selected_candidate_id": "bp8-30-average",
                    "score": 0.75,
                    "evaluation_scope": "development",
                    "evaluation_protocol": {
                        "metric": "subject_macro_balanced_accuracy"
                    },
                    "panel": panel,
                    "selected_receipt": {
                        "status": "evaluated",
                        "candidate_id": "bp8-30-average",
                        "job_id": "test-job",
                        "macro_ba": 0.75,
                        "panel_hash": panel["panel_hash"],
                    },
                    "seed": 42,
                    "candidate_summary": [
                        {
                            "candidate_id": "bp8-30-average",
                            "status": "evaluated",
                            "score": 0.75,
                            "error": None,
                        }
                    ],
                    "selected_method_ref": method_ref,
                    "reason": "fixture",
                },
                "data_preprocessing": {"job_id": "test-job"},
            },
        }
        store = SimpleNamespace(
            root=root,
            status=lambda owner, job_id: SimpleNamespace(records=records),
            get=lambda owner, ref, kind: baseline_methods()[0].model_dump(mode="json"),
        )
        freeze_evidence(store, state["outputs"]["data_evaluation"])
        complete_delivery_receipt(store, state["outputs"]["data_evaluation"])
        # FIF semantic verification is covered by test_workflow's real worker.
        # Keep actual artifact/source hash checks and all delivery serialization.
        monkeypatch.setattr(
            outputs,
            "verify_result",
            lambda root, result: all(
                file_hash(root / artifact["path"]) == artifact["sha256"]
                for artifact in result["artifacts"]
            ),
        )
        folder = tmp_path / "workflow/delivery"
        (folder.parent / "report").mkdir(parents=True)
        (folder.parent / "report/report.html").write_text("<html>fixture</html>")
        return SimpleNamespace(
            state=state, store=store, folder=folder, records=records, expected=expected
        )

    return make


def test_holdout_roles_preserve_development_as_validation():
    panel = {"train_subjects": ["S001"], "development_subjects": ["S002"]}
    assert outputs._subject_roles(["S002", "S001", "S001"], panel) == {
        "S001": "train",
        "S002": "validation",
    }
    for subjects in (["S001"], ["S001", "S002", "S003"]):
        with pytest.raises(ValueError):
            outputs._subject_roles(subjects, panel)


def test_delivery_streams_and_preserves_arrays_rows_schema_and_archive(
    delivery_case, monkeypatch
):
    case = delivery_case()
    block_bytes = 224  # Two source epochs, forcing multiple blocks per recording.
    monkeypatch.setattr(outputs, "_ARRAY_BLOCK_BYTES", block_bytes)
    original_load, original_save = np.load, np.save
    original_finite, original_equal = np.isfinite, np.array_equal
    mappings, comparisons, finite_checks = [], [], []

    def load(path, *args, **kwargs):
        assert kwargs.get("mmap_mode") == "r", "delivery must not eagerly load arrays"
        assert kwargs.get("allow_pickle") is False
        value = original_load(path, *args, **kwargs)
        assert isinstance(value, np.memmap)
        mappings.append(value)
        return value

    def save(path, value, **kwargs):
        assert Path(path).name != "X.npy", "X must be written to a fixed memmap"
        return original_save(path, value, **kwargs)

    def finite(value):
        assert value.nbytes <= block_bytes
        finite_checks.append(value.shape)
        return original_finite(value)

    def equal(left, right):
        assert max(left.nbytes, right.nbytes) <= block_bytes
        comparisons.append(left.shape)
        return original_equal(left, right)

    def no_concatenate(*args, **kwargs):
        pytest.fail("delivery must not concatenate recording arrays")

    with monkeypatch.context() as guard:
        guard.setattr(np, "load", load)
        guard.setattr(np, "save", save)
        guard.setattr(np, "isfinite", finite)
        guard.setattr(np, "array_equal", equal)
        guard.setattr(np, "concatenate", no_concatenate)
        result = outputs.deliver(case.state, case.folder, case.store)
    assert all(value._mmap.closed for value in mappings)
    assert len(finite_checks) > len(case.records)
    assert len(comparisons) > len(case.records)
    DeliveryOutput.model_validate(result)
    arrays = {
        name: np.load(case.folder / name, allow_pickle=False) for name in ARRAY_FORMATS
    }
    for name, spec in ARRAY_FORMATS.items():
        assert arrays[name].dtype == np.dtype(spec["dtype"])
        assert arrays[name].ndim == len(spec["axes"])
    expected = np.concatenate([case.expected[key] for key in sorted(case.expected)])
    np.testing.assert_array_equal(arrays["X.npy"], expected)
    assert result["shape"] == list(expected.shape)
    with (case.folder / "trial-index.tsv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    cursor = 0
    for record_id in sorted(case.expected):
        for epoch in range(len(case.expected[record_id])):
            row = rows[cursor]
            assert int(row["index"]) == cursor
            assert row["record_id"] == record_id
            assert int(row["epoch_index"]) == epoch
            assert int(row["source_sample"]) == 100 + epoch * 20
            assert row["source_event"] == f"{record_id}-event-{epoch}"
            assert row["label"] == ("left_hand" if epoch % 2 == 0 else "right_hand")
            assert arrays["y.npy"][cursor] == epoch % 2
            assert row["subject"] == arrays["subjects.npy"][cursor] == record_id[:4]
            assert (
                row["split"]
                == arrays["split.npy"][cursor]
                == result["subject_split"][row["subject"]]
            )
            cursor += 1
    assert result["classes"] == {str(i): int(sum(arrays["y.npy"] == i)) for i in (0, 1)}
    assert result["split_counts"] == {
        "train": len(expected),
        "validation": 0,
        "test": 0,
    }
    manifest = json.loads((case.folder / "manifest.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(case.folder.parent / "training-data.zip") as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {
            *DELIVERY_FILES,
            "manifest.json",
            *(
                f"provenance/{r['record_id']}/{name}"
                for r in case.records
                for name in PROVENANCE_FILES
            ),
        }
        assert json.loads(archive.read("manifest.json")) == manifest
        for entry in manifest["files"]:
            path = case.folder / entry["name"]
            assert entry["sha256"] == file_hash(path)
            assert entry["bytes"] == path.stat().st_size
            assert archive.read(entry["name"]) == path.read_bytes()
    # A second delivery can replace the files on Windows and preserves the data.
    again = outputs.deliver(case.state, case.folder, case.store)
    assert again["subject_split"] == result["subject_split"]
    assert (case.folder / "manifest.json").read_text(encoding="utf-8") == json.dumps(
        manifest, ensure_ascii=False, indent=2
    ) + "\n"


def test_109_subject_delivery_splits_subjects_not_trials(delivery_case):
    case = delivery_case([(f"S{i:03}", 1) for i in range(1, 110)] + [("S001", 30)])
    result = outputs.deliver(case.state, case.folder, case.store)
    assert Counter(result["subject_split"].values()) == {
        "train": 109,
    }
    subjects = np.load(case.folder / "subjects.npy", allow_pickle=False)
    splits = np.load(case.folder / "split.npy", allow_pickle=False)
    for subject, role in result["subject_split"].items():
        assert set(splits[subjects == subject]) == {role}
    assert sum(result["split_counts"].values()) == 139


@pytest.mark.parametrize(
    "size, empty", [(2, {"validation", "test"}), (3, {"validation", "test"})]
)
def test_tiny_delivery_records_empty_groups(delivery_case, size, empty):
    case = delivery_case([(f"S{i:03}", 2) for i in range(1, size + 1)])
    result = outputs.deliver(case.state, case.folder, case.store)
    assert {
        role for role, count in result["split_counts"].items() if count == 0
    } == empty
    manifest = json.loads((case.folder / "manifest.json").read_text(encoding="utf-8"))
    assert any(
        "分组为空" in item and all(role in item for role in empty)
        for item in manifest["limitations"]
    )


@pytest.mark.parametrize("bad_value", [np.nan, np.inf, -np.inf, 1e300])
def test_nonfinite_or_float32_overflow_rejected_and_memmaps_closed(
    delivery_case, monkeypatch, bad_value
):
    case = delivery_case()
    record = case.records[0]
    artifact = record["result"]["artifacts"][0]
    source = case.store.root / artifact["path"]
    values = np.load(source, allow_pickle=False)
    values[-1, -1, -1] = bad_value  # Last block must also be checked.
    np.save(source, values)
    artifact["sha256"] = file_hash(source)
    case.state["outputs"]["data_evaluation"]["representation"]["records"][
        record["record_id"]
    ]["array_sha256"] = artifact["sha256"]
    monkeypatch.setattr(outputs, "_ARRAY_BLOCK_BYTES", 112)
    original_open = np.lib.format.open_memmap
    mappings = []

    def track(*args, **kwargs):
        value = original_open(*args, **kwargs)
        mappings.append(value)
        return value

    monkeypatch.setattr(np.lib.format, "open_memmap", track)
    with pytest.raises(ValueError, match="有限值 Epoch"):
        outputs.deliver(case.state, case.folder, case.store)
    assert mappings and all(value._mmap.closed for value in mappings)
    assert not (case.folder.parent / "training-data.zip").exists()


@pytest.mark.parametrize(
    "problem",
    ["epochs", "channels", "sfreq", "time", "label", "hash", "status", "empty"],
)
def test_invalid_delivery_inputs_still_fail(delivery_case, problem):
    case = delivery_case()
    record = case.records[0]
    artifacts = {a["name"]: a for a in record["result"]["artifacts"]}
    if problem in {"epochs", "label"}:
        artifact = artifacts["events.json"]
        path = case.store.root / artifact["path"]
        events = json.loads(path.read_text(encoding="utf-8"))
        event = next(e for e in events if e["retained"])
        event["epoch_index" if problem == "epochs" else "label"] = (
            999 if problem == "epochs" else "rest"
        )
        path.write_text(json.dumps(events), encoding="utf-8")
        artifact["sha256"] = file_hash(path)
    elif problem in {"channels", "sfreq"}:
        record["result"]["delta"]["after"][problem] = (
            ["C4", "C3"] if problem == "channels" else 128
        )
    elif problem == "time":
        artifact = artifacts["signal_V.npy"]
        path = case.store.root / artifact["path"]
        np.save(path, np.zeros((5, 2, 8)))
        artifact["sha256"] = file_hash(path)
    elif problem == "hash":
        artifacts["signal_V.npy"]["sha256"] = "0" * 64
    elif problem == "status":
        record["status"] = "failed"
    else:
        case.records.clear()
    with pytest.raises(ValueError):
        outputs.deliver(case.state, case.folder, case.store)
    assert not (case.folder.parent / "training-data.zip").exists()


def test_saved_data_corruption_in_last_block_is_detected(delivery_case, monkeypatch):
    case = delivery_case()
    original_load = np.load

    def corrupt_before_reread(path, *args, **kwargs):
        if Path(path).name == "X.npy":
            with Path(path).open("r+b") as stream:
                stream.seek(-4, 2)
                stream.write(np.float32(-999).tobytes())
        return original_load(path, *args, **kwargs)

    monkeypatch.setattr(outputs, "_ARRAY_BLOCK_BYTES", 112)
    monkeypatch.setattr(np, "load", corrupt_before_reread)
    with pytest.raises(ValueError, match="保存后读取不一致"):
        outputs.deliver(case.state, case.folder, case.store)
    assert not (case.folder.parent / "training-data.zip").exists()
