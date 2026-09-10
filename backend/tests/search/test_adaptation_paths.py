"""Adaptation must fit the Windows path budget with production candidate IDs."""

from pathlib import Path

import numpy as np
import pytest

from app.preprocessing.storage import digest, file_hash
from app.search.evaluation import _mapped
from app.search.evaluation_numeric import prepare_representation
from app.search.method_space import edited_entry, seed_entries
from app.search.scientific_space import build_space


def production_candidate_ids():
    context = dict(
        at_least_four_eeg=True, electrode_positions=True, asr_dependency=True
    )
    space = build_space(context)
    seeds = seed_entries(space, context)
    edited = edited_entry(
        seeds[0],
        [{"action": "set_adaptation", "policy": {"adaptation": "euclidean_alignment"}}],
        space,
        title="Path regression",
        order=len(seeds),
        context=context,
    )
    return [max(seeds, key=lambda entry: len(entry["id"]))["id"], edited["id"]]


@pytest.mark.parametrize("candidate_id", production_candidate_ids())
@pytest.mark.parametrize(
    "adaptation", ["subject_scale", "euclidean_alignment", "conditional_alignment"]
)
def test_adaptation_roundtrip_at_windows_path_budget(
    tmp_path, candidate_id, adaptation
):
    # Use the default pytest root, then deliberately consume the path budget.
    # The deepest directory stays below Windows' legacy mkdir limit (248),
    # while the old full-hash filenames exceed MAX_PATH even for seed IDs.
    suffix = Path("offline-search") / ("a" * 32) / "candidates" / candidate_id
    padding = 240 - len(str(tmp_path / suffix / "adaptation")) - 1
    assert padding > 0
    output = tmp_path / ("p" * padding) / suffix
    assert len(str(output / "adaptation")) == 240
    assert (
        len(str(output / "adaptation" / f"subject-{digest('S/01')}-transform.npy"))
        >= 260
    )
    assert (
        len(str(output / "adaptation" / f"record-{digest('r/01')}-signal.npy")) >= 260
    )

    # IDs deliberately share sanitized spellings; neither sanitizing nor
    # truncating their names/hashes may alias subjects or records.
    records = {
        "r/01": {"subject": "S/01"},
        "r:01": {"subject": "S:01"},
        "r-02": {"subject": "S/01"},
    }
    panel = {"output_contract": {"channels": ["C3", "C4"]}, "records": records}
    sources, originals = [], {}
    rng = np.random.default_rng(42)
    for index, rid in enumerate(records):
        values = rng.normal(size=(2, 2, 16)) * (index + 1) * 1e-6
        path = tmp_path / f"input{index}.npy"
        np.save(path, values, allow_pickle=False)
        sources.append(
            (path, [{"epoch_index": 0}, {"epoch_index": 1}], list(values.shape), rid)
        )
        originals[rid] = (values, file_hash(path))

    policy = {"adaptation": adaptation, "alignment_threshold": 10.0}
    derived, diagnostics, representation = prepare_representation(
        sources, panel, output, policy, _mapped
    )
    assert set(diagnostics) == {"S/01", "S:01"}
    assert [s[3] for s in derived] == list(records)
    paths = []
    for subject, info in representation["subjects"].items():
        path = Path(info["transform_path"])
        paths.append(path)
        assert path.is_relative_to(output)
        assert len(str(path)) < 260
        assert file_hash(path) == info["transform_sha256"]
        assert info["fit_trials"] == (4 if subject == "S/01" else 2)
    for target, _, _, rid in derived:
        info = representation["records"][rid]
        paths.append(target)
        assert target == Path(info["array_path"])
        assert target.is_relative_to(output)
        assert len(str(target)) < 260
        assert file_hash(target) == info["array_sha256"]
        assert info["unit"] == "dimensionless"
        transform = np.load(
            representation["subjects"][records[rid]["subject"]]["transform_path"],
            allow_pickle=False,
        )
        with _mapped(target) as delivered:
            np.testing.assert_allclose(delivered, transform @ originals[rid][0])
    assert len(set(paths)) == len(records) + len(representation["subjects"])
    assert all(file_hash(path) == originals[rid][1] for path, _, _, rid in sources)

    # Mapping is tied to sorted frozen IDs, independent of source/dict order.
    reordered_panel = {**panel, "records": dict(reversed(list(records.items())))}
    _, _, repeated = prepare_representation(
        list(reversed(sources)), reordered_panel, output, policy, _mapped
    )
    for rid, info in repeated["records"].items():
        assert info["array_path"] == representation["records"][rid]["array_path"]
        assert info["array_sha256"] == file_hash(Path(info["array_path"]))
    for subject, info in repeated["subjects"].items():
        assert (
            info["transform_path"]
            == representation["subjects"][subject]["transform_path"]
        )
        assert info["transform_sha256"] == file_hash(Path(info["transform_path"]))
