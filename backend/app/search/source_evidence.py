"""Carry immutable source objects across the workflow/worker storage boundary."""

from app.preprocessing.schemas import Ref
from app.preprocessing.storage import digest, file_hash, within
from .io import read, write


def freeze_evidence(root, methods, store, owner):
    result = {}
    for method in methods:
        for evidence in method.evidence:
            ref = evidence.artifact_ref
            if ref is None or ref.id in result:
                continue
            value = store.get(owner, ref, "evidence")
            path = f"source-evidence/{ref.id[:24]}.json"
            write(root / path, value)
            result[ref.id] = {"ref": ref.model_dump(), "path": path, "sha256": file_hash(root / path)}
    return result


def source_objects(root, method):
    index = read(root / "protocol.json").get("source_evidence", {})
    objects = {}
    for evidence in method.evidence:
        ref = evidence.artifact_ref
        if ref is None:
            continue
        if ref.id not in objects:
            row = index.get(ref.id)
            if row is None or Ref.model_validate(row["ref"]) != ref:
                raise ValueError("method source evidence is absent from the frozen search")
            path = within(root, row["path"])
            if file_hash(path) != row["sha256"]:
                raise ValueError("source evidence file checksum differs")
            value = read(path)
            if digest(value) != ref.id or ref.id != ref.sha256:
                raise ValueError("source evidence content differs from its immutable reference")
            objects[ref.id] = value
        if evidence.text not in str(objects[ref.id].get("content", "")):
            raise ValueError("method quote is absent from the frozen source evidence")
    return objects


def import_evidence(root, method, store, owner):
    for identity, value in source_objects(root, method).items():
        if store.put(owner, "evidence", value).id != identity:
            raise ValueError("worker source registration changed immutable identity")
