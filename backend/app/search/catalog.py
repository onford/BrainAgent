"""Frozen method seeds and verified executable candidate recipes."""

from pathlib import Path

from app.preprocessing.storage import digest, file_hash
from .io import read
from .method_space import BASELINE_ID, basic_space, seed_entries, verify_registry
from .recipe_compiler import compile_recipe


def catalog():
    return seed_entries(basic_space())


def search_engine_hash():
    root = Path(__file__).parent
    hashes = {
        p.relative_to(root).as_posix(): file_hash(p)
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.suffix in {".py", ".json"}
    }
    hashes["../file_publish.py"] = file_hash(root.parent / "file_publish.py")
    return digest(hashes)


def entries_at(root):
    protocol = read(Path(root) / "protocol.json")
    if digest(protocol["space"]) != protocol["space_hash"]:
        raise ValueError("operator space checksum differs from frozen protocol")
    return verify_registry(protocol, read(Path(root) / "registry.json"))


def method(entry, panel, space=None, context=None):
    return compile_recipe(entry, space or basic_space(), panel, context)


def selection_score(receipt):
    if not receipt or receipt.get("status") != "evaluated":
        return None
    assessment = receipt.get("assessment")
    return assessment.get("selection_score") if assessment is not None else receipt.get("macro_ba")


def select(candidates, *, require_complete_assessment=False):
    eligible = [
        c
        for c in candidates
        if (c.get("receipt") or {}).get("status") == "evaluated"
        and c.get("status", "evaluated") == "evaluated"
        and selection_score(c.get("receipt")) is not None
        and (not require_complete_assessment or (c["receipt"].get("assessment") or {}).get("status") == "complete")
    ]
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda c: (
            -selection_score(c["receipt"]),
            c["id"] != BASELINE_ID,
            len(c.get("parameters", {}).get("operators", [])),
            c["id"],
        ),
    )["id"]
