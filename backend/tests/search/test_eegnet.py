"""Synthetic-only integration and leakage checks for the standalone learner."""

import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from app.search import eegnet


@pytest.fixture
def data():
    rng = np.random.default_rng(99)
    X = rng.normal(size=(30, 3, 80)).astype(np.float32)
    y = np.tile([0, 1], 15)
    subjects = np.repeat(["a", "b", "c", "d", "e"], 6)
    X[y == 1, 0] += np.sin(np.arange(80) * 0.3)
    return X, y, subjects


def train(tmp_path, data, name="model.pt", **kwargs):
    return eegnet.train_fold(*data, seed=17, sfreq=160,
                            checkpoint_path=tmp_path / name,
                            training_config={"max_epochs": 3, "batch_size": 8}, **kwargs)


def test_protocol_is_lazy_and_frozen():
    script = "from app.search.eegnet import protocol; import sys,json; json.dumps(protocol()); assert 'torch' not in sys.modules"
    subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[2], check=True)
    p = eegnet.protocol()
    assert p["training"]["max_epochs"] == 100
    assert p["training"]["patience"] == 15
    p["training"]["max_epochs"] = 2
    assert eegnet.protocol()["training"]["max_epochs"] == 100
    assert eegnet.protocol({"max_epochs": 2})["training"]["max_epochs"] == 2
    with pytest.raises((TypeError, ValueError)):
        eegnet.protocol({"unknown": 1})
    assert eegnet.protocol({"max_epochs": 101, "patience": 20, "batch_size": 128})["training"]["max_epochs"] == 101
    with pytest.raises(ValueError):
        eegnet.protocol({"max_epochs": 0})


def test_architecture_and_constraints():
    import torch
    model = eegnet.build_model(3, 80)
    assert model.temporal.weight.shape == (8, 1, 1, 80)
    assert model.spatial.groups == 8
    assert model.spatial.weight.shape == (16, 1, 3, 1)
    assert model.separable.groups == 16
    assert model.separable.kernel_size == (1, 16)
    assert model.pointwise.weight.shape == (16, 16, 1, 1)
    assert model.pool1.kernel_size == (1, 5)
    assert model.pool2.kernel_size == (1, 8)
    assert model.classifier.in_features == 32
    assert model.drop1.p == model.drop2.p == 0.5
    assert model(torch.ones(2, 1, 3, 80)).shape == (2, 2)
    with torch.no_grad():
        model.spatial.weight.fill_(10)
        model.classifier.weight.fill_(10)
    model.constrain_weights()
    assert torch.all(model.spatial.weight.flatten(1).norm(dim=1) <= 1.000001)
    assert torch.all(model.classifier.weight.norm(dim=1) <= 0.250001)
    with pytest.raises(ValueError, match="160"):
        eegnet.build_model(3, 80, sfreq=128)


def test_real_train_reload_matches_direct_prediction(tmp_path, data):
    import torch
    meta = train(tmp_path, data)
    json.dumps(meta, allow_nan=False)
    path = tmp_path / "model.pt"
    cp = torch.load(path, weights_only=True)
    X, _, groups = data
    model = eegnet.build_model(**meta["architecture"])
    model.load_state_dict(cp["state_dict"])
    model.eval()
    norm = cp["normalization"]
    transformed = ((X.astype(np.float64) - norm["mean"].numpy()) / norm["std"].numpy()).astype(np.float32)
    with torch.inference_mode():
        expected = model(torch.from_numpy(transformed[:, None])).softmax(1).numpy()
    actual = eegnet.predict_checkpoint(path, X)
    np.testing.assert_allclose(actual, expected, atol=1e-7)
    np.testing.assert_array_equal(actual, eegnet.predict_checkpoint(path, X))
    np.save(tmp_path / "input.npy", X)
    script = (
        "import numpy as np,sys; from app.search.eegnet import predict_checkpoint; "
        "np.save(sys.argv[3], predict_checkpoint(sys.argv[1], np.load(sys.argv[2])))"
    )
    subprocess.run([sys.executable, "-c", script, str(path), str(tmp_path / "input.npy"),
                    str(tmp_path / "replayed.npy")],
                   cwd=Path(__file__).resolve().parents[2], check=True)
    np.testing.assert_allclose(actual, np.load(tmp_path / "replayed.npy"), atol=1e-12, rtol=0)
    assert actual.dtype == np.float64
    np.testing.assert_allclose(actual.sum(axis=1), 1, atol=1e-12, rtol=0)
    assert actual.shape == (30, 2)
    assert eegnet.predict_checkpoint(path, X[:0]).shape == (0, 2)
    fit_mask = np.isin(groups, meta["fit_subjects"])
    np.testing.assert_allclose(norm["mean"].numpy(), X[fit_mask].astype(np.float64).mean(axis=(0, 2), keepdims=True))
    assert set(meta["fit_subjects"]).isdisjoint(meta["validation_subjects"])
    assert set(meta["outer_training_subjects"]) == set(groups)
    assert meta["best_epoch"] == 1 + np.argmin([h["validation_logloss"] for h in meta["history"]])
    # Best checkpoint reproduces the recorded held-out logloss.
    val_mask = np.isin(groups, meta["validation_subjects"])
    logloss = -np.log(actual[val_mask, data[1][val_mask]]).mean()
    assert logloss == pytest.approx(meta["best_validation_logloss"], abs=1e-6)
    with pytest.raises(FileExistsError):
        train(tmp_path, data)
    with pytest.raises(ValueError, match="match checkpoint"):
        eegnet.predict_checkpoint(path, X[:, :2])


def test_fixed_seed_exact_repeat_and_rng_restoration(tmp_path, data):
    import torch
    before = torch.random.get_rng_state().clone()
    first = train(tmp_path, data, "first.pt")
    assert torch.equal(before, torch.random.get_rng_state())
    second = train(tmp_path, data, "second.pt")
    assert first == second
    assert "checkpoint_path" not in first
    checkpoints = [torch.load(tmp_path / name, weights_only=True)
                   for name in ("first.pt", "second.pt")]
    assert checkpoints[0]["metadata"] == checkpoints[1]["metadata"] == first
    np.testing.assert_array_equal(eegnet.predict_checkpoint(tmp_path / "first.pt", data[0]),
                                  eegnet.predict_checkpoint(tmp_path / "second.pt", data[0]))


def test_validation_labels_do_not_enter_optimizer_or_split(tmp_path, data):
    import torch
    cfg = {"max_epochs": 1, "batch_size": 8}
    X, y, groups = data
    def run(labels, name):
        return eegnet.train_fold(X, labels, groups, seed=17, sfreq=160,
                                checkpoint_path=tmp_path / name, training_config=cfg)
    first = run(y, "a.pt")
    changed = y.copy()
    changed[np.isin(groups, first["validation_subjects"])] ^= 1
    second = run(changed, "b.pt")
    assert first["fit_subjects"] == second["fit_subjects"]
    assert first["validation_subjects"] == second["validation_subjects"]
    a, b = [torch.load(tmp_path / name, weights_only=True) for name in ("a.pt", "b.pt")]
    # Includes BatchNorm running stats: validation must always be in eval mode.
    for key in a["state_dict"]:
        assert torch.equal(a["state_dict"][key], b["state_dict"][key]), key
    assert first["history"][0]["train_logloss"] == second["history"][0]["train_logloss"]


def test_validation_signal_not_used_for_normalization(tmp_path, data):
    import torch
    first = train(tmp_path, data, "original.pt")
    X, y, groups = data
    changed = X.copy()
    changed[np.isin(groups, first["validation_subjects"])] += 5000
    train(tmp_path, (changed, y, groups), "shifted.pt")
    a, b = [torch.load(tmp_path / name, weights_only=True) for name in ("original.pt", "shifted.pt")]
    for key in ("mean", "std"):
        assert torch.equal(a["normalization"][key], b["normalization"][key])


def test_early_stopping_first_minimum_and_no_outer_data(tmp_path, data, monkeypatch):
    import torch
    original = torch.nn.functional.cross_entropy
    def constant_validation(logits, labels, **kwargs):
        if not torch.is_grad_enabled():
            return torch.tensor(float(len(labels)))  # Constant mean logloss = 1.
        return original(logits, labels, **kwargs)
    monkeypatch.setattr(torch.nn.functional, "cross_entropy", constant_validation)
    meta = eegnet.train_fold(*data, seed=17, sfreq=160, checkpoint_path=tmp_path / "early.pt",
                             training_config={"max_epochs": 6, "patience": 2})
    assert meta["best_epoch"] == 1
    assert meta["epochs_trained"] == 3
    assert meta["stopped_early"]
    with pytest.raises(TypeError):
        eegnet.train_fold(*data, seed=17, sfreq=160, checkpoint_path=tmp_path / "bad.pt", dev_y=data[1])


def test_cancellation_per_batch_no_checkpoint_and_invalid_subjects(tmp_path, data):
    calls = 0
    def cancel():
        nonlocal calls
        calls += 1
        return calls == 4
    with pytest.raises(InterruptedError):
        train(tmp_path, data, cancel_check=cancel)
    assert calls == 4
    assert not (tmp_path / "model.pt").exists()
    with pytest.raises(ValueError, match="at least two"):
        train(tmp_path, (data[0], data[1], ["only"] * len(data[0])))


def test_split_has_no_label_dependency_or_class_repair(tmp_path, data):
    X, y, subjects = data
    cfg = eegnet.TrainingConfig()
    fit, val, fit_subjects, val_subjects = eegnet._split_subjects(subjects, len(X), cfg)
    order = np.random.default_rng(31).permutation(len(X))
    _, _, shuffled_fit, shuffled_val = eegnet._split_subjects(subjects[order], len(X), cfg)
    assert (fit_subjects, val_subjects) == (shuffled_fit, shuffled_val)
    labels = y.copy()
    labels[fit] = 0
    labels[val] = 1
    with pytest.raises(ValueError, match="label-driven resplitting is forbidden"):
        train(tmp_path, (X, labels, subjects))
    assert not (tmp_path / "model.pt").exists()


def test_train_rejects_non_panel_sampling_rate(tmp_path, data):
    with pytest.raises(ValueError, match="160"):
        eegnet.train_fold(*data, seed=17, sfreq=128, checkpoint_path=tmp_path / "bad.pt")
    assert not (tmp_path / "bad.pt").exists()
