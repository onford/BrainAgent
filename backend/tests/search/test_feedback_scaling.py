from copy import deepcopy
import json

import pytest

from app.search.method_space import basic_space, seed_entries
from app.search.reasoning import feedback, read_context_evidence


def state_with_history():
    space = basic_space().model_dump(mode="json")
    seeds = seed_entries(space)
    registry, candidates = [], []
    for index in range(256):
        entry = deepcopy(seeds[index % len(seeds)])
        entry["id"] = seeds[0]["id"] if index == 0 else f"candidate-{index:04d}"
        entry["title"] = f"Experiment {index}"
        registry.append(entry)
        candidates.append({"id": entry["id"], "status": "evaluated", "receipt": {
            "status": "evaluated", "macro_ba": .6, "assessment": {
                "selection_score": .6 + index / 10000,
                "quality": {"summary": {"metrics": {"channel_curve": {"value": list(range(6400))},
                                                          "rms": {"value": index + 1.0}}}},
                "utility": {}, "reconstruction": {},
            }}})
    return {"protocol": {"catalog": seeds, "space": space}, "registry": registry,
            "candidates": candidates, "panel": {"panel_hash": "a" * 64, "train_subjects": [],
            "development_subjects": [f"S{i:03d}" for i in range(1, 110)], "output_contract": {},
            "trial_count": 4918, "eligible_count": 4918}, "budget": {}, "usage": {}, "actions": []}


def test_large_history_keeps_all_scores_and_retrievable_exact_records():
    state = state_with_history()
    before = deepcopy(state)
    context = feedback(state, [])
    assert len(json.dumps(context, ensure_ascii=False)) < 180000
    assert len(context["history_scores"]) == len(context["candidate_index"]) == 256
    assert len(context["results"]) < 256
    assert context["history_scores"][-1]["selection_score"] == .6255
    reading = read_context_evidence({"source_id": "candidate:candidate-0001", "query": '"rms"'}, state, [])
    assert reading["status"] == "read" and '"value": 2.0' in reading["excerpts"][0]
    assert state == before
    state["candidates"][1]["receipt"]["assessment"]["quality"]["summary"]["metrics"]["rms"]["value"] = 3.0
    updated = read_context_evidence({"source_id": "candidate:candidate-0001", "query": '"rms"'}, state, [])
    assert updated["source_sha256"] != reading["source_sha256"]


def test_candidate_retrieval_rejects_arbitrary_paths():
    with pytest.raises(ValueError, match="未知"):
        read_context_evidence({"source_id": "candidate:../../secrets", "query": "anything"}, state_with_history(), [])
