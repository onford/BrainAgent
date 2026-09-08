import csv
import json

import pytest

from app.workflows.formats import write_table
from app.workflows.records import check_format, write_index, write_readable
from app.workflows.schemas import STAGES, STAGE_LABELS


def test_fixed_table_columns_reject_missing_extra_or_reordered_fields(tmp_path):
    path = tmp_path / "source-inventory.tsv"
    write_table(path, [{"path": "S001/S001R04.edf", "bytes": 10}], ["path", "bytes"])
    original = path.read_bytes()
    for rows, columns in [
        ([{"path": "file"}], ["path", "bytes"]),
        ([{"path": "file", "bytes": 10, "note": "extra"}], ["path", "bytes"]),
        ([{"path": "file", "bytes": 10}], ["bytes", "path"]),
    ]:
        with pytest.raises(ValueError):
            write_table(path, rows, columns)
        assert path.read_bytes() == original
    write_table(path, [], ["path", "bytes"])
    assert path.read_bytes() == b"path\tbytes\n"
    with path.open(encoding="utf-8", newline="") as stream:
        assert list(csv.DictReader(stream, delimiter="\t")) == []


def test_supporting_json_contract_rejects_silent_shape_changes(tmp_path):
    path = tmp_path / "delivery/labels.json"
    write_readable(path, {"0": "left_hand", "1": "right_hand"})
    original = path.read_bytes()
    for value in [
        {"0": "left_hand"},
        {"0": "left_hand", "1": "right_hand", "2": "rest"},
    ]:
        with pytest.raises(ValueError):
            write_readable(path, value)
        assert path.read_bytes() == original


def test_format_snapshot_detects_changes_instead_of_replacing_the_original(tmp_path):
    state = {
        "id": "a" * 32,
        "request": {"source_root": str(tmp_path)},
        "stages": [
            {"name": n, "label": label, "status": "pending"}
            for n, label in zip(STAGES, STAGE_LABELS)
        ],
    }
    write_index(tmp_path, state)
    check_format(tmp_path)
    catalog_path = tmp_path / "process/formats.json"
    catalog_bytes = catalog_path.read_bytes()
    catalog = json.loads(catalog_bytes)
    catalog["tsv"]["source-inventory.tsv"]["columns"].reverse()
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ValueError, match="格式或报告模板已变化"):
        check_format(tmp_path)
    catalog_path.write_bytes(catalog_bytes)
    schema_path = tmp_path / "process/schema.json"
    original = schema_path.read_bytes()
    definitions = json.loads(original)
    definitions["$defs"]["TrainingLabels"]["properties"].pop("1")
    schema_path.write_text(json.dumps(definitions), encoding="utf-8")
    with pytest.raises(ValueError, match="格式或报告模板已变化"):
        check_format(tmp_path)
    write_index(tmp_path, state)
    assert (
        schema_path.read_bytes() != original
    )  # Never silently overwrite a pinned snapshot.
