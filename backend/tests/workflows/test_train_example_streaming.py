"""Bounded feature extraction and compatibility of the standalone training script."""

# ruff: noqa: E402
import ast
from pathlib import Path
import shutil

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("sklearn")

from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.workflows.templates import train_example as example


@pytest.fixture
def dataset(tmp_path):
    y = np.arange(23, dtype=np.int64) % 2
    X = np.random.default_rng(47).normal(0, 5e-6, (23, 4, 37)).astype(np.float32)
    X[:, 0, :] *= np.where(y == 0, 1, 4)[:, None]
    X[:, 1, :] *= np.where(y == 0, 3, 1)[:, None]
    X[:, 2, :] = 3e-6  # Zero variance exercises the original 1e-20 floor.
    X[-5:, 3, :] *= 100  # Held-out distribution must not affect scaler fitting.
    subjects = np.asarray(
        ["S001"] * 7 + ["S002"] * 6 + ["S003"] * 5 + ["S004"] * 5, dtype="<U4"
    )
    split = np.asarray(["train"] * 13 + ["validation"] * 5 + ["test"] * 5, dtype="<U10")
    arrays = {"X": X, "y": y, "subjects": subjects, "split": split}
    for name, values in arrays.items():
        np.save(tmp_path / f"{name}.npy", values, allow_pickle=False)
    return tmp_path, arrays


@pytest.mark.parametrize("fortran", [False, True])
@pytest.mark.parametrize("block_trials", [1, 4, 100])
def test_chunked_features_match_original_float64_variance(
    dataset, monkeypatch, fortran, block_trials
):
    folder, arrays = dataset
    X = np.asfortranarray(arrays["X"]) if fortran else arrays["X"]
    np.save(folder / "X.npy", X)
    expected = np.log(np.maximum(X.astype(np.float64).var(axis=2), 1e-20))
    monkeypatch.setattr(example, "_FEATURE_BLOCK_BYTES", block_trials * 4 * 37 * 8)
    with example._mapped_array(folder / "X.npy") as mapped:
        actual = example._log_variance(mapped)
    assert mapped._mmap.closed
    assert type(actual) is np.ndarray and actual.dtype == np.float64
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-14)


def test_training_matches_original_and_never_loads_or_casts_full_signal(
    dataset, monkeypatch
):
    folder, arrays = dataset
    original_features = np.log(
        np.maximum(arrays["X"].astype(np.float64).var(axis=2), 1e-20)
    )
    mask = arrays["split"] == "train"
    original_model = make_pipeline(
        StandardScaler(), LogisticRegression(max_iter=1000, random_state=42)
    )
    original_model.fit(original_features[mask], arrays["y"][mask])
    block_trials = 4
    block_bytes = block_trials * 4 * 37 * 8
    monkeypatch.setattr(example, "_FEATURE_BLOCK_BYTES", block_bytes)
    real_load, real_finite = np.load, np.isfinite
    mappings, converted_shapes, checked_shapes, models = [], [], [], []

    class GuardedSignal(np.memmap):
        def astype(self, dtype, *args, **kwargs):
            assert self.ndim == 3 and self.shape[0] <= block_trials
            assert self.size * np.dtype(dtype).itemsize <= block_bytes
            converted_shapes.append(self.shape)
            return super().astype(dtype, *args, **kwargs)

    def load(path, *args, **kwargs):
        assert kwargs.get("mmap_mode") == "r"
        assert kwargs.get("allow_pickle") is False
        values = real_load(path, *args, **kwargs)
        assert isinstance(values, np.memmap)
        mappings.append(values)
        return values.view(GuardedSignal) if Path(path).name == "X.npy" else values

    def finite(values, *args, **kwargs):
        if isinstance(values, np.ndarray) and values.ndim == 3:
            assert values.shape[0] <= block_trials
            checked_shapes.append(values.shape)
        return real_finite(values, *args, **kwargs)

    def capture_model(*steps):
        model = make_pipeline(*steps)
        models.append(model)
        return model

    with monkeypatch.context() as guard:
        guard.setattr(np, "load", load)
        guard.setattr(np, "isfinite", finite)
        guard.setattr(example, "make_pipeline", capture_model)
        receipt = example.train(folder)
    assert len(mappings) == 4 and all(values._mmap.closed for values in mappings)
    assert converted_shapes == checked_shapes == [(4, 4, 37)] * 5 + [(3, 4, 37)]
    assert receipt == {
        "model": "log-variance + StandardScaler + LogisticRegression",
        "training_trials": 13,
        "feature_count": 4,
        "prediction_count": 23,
        "classes": [0, 1],
        "fit_subjects": ["S001", "S002"],
        "quality_evaluated": False,
    }
    actual_model = models[0]
    for attribute in ("mean_", "var_", "scale_"):
        np.testing.assert_allclose(
            getattr(actual_model[0], attribute),
            getattr(original_model[0], attribute),
            rtol=0,
            atol=1e-13,
        )
    np.testing.assert_allclose(
        actual_model[1].coef_, original_model[1].coef_, rtol=0, atol=1e-12
    )
    np.testing.assert_allclose(
        actual_model[1].intercept_, original_model[1].intercept_, rtol=0, atol=1e-12
    )
    np.testing.assert_array_equal(
        actual_model.predict(original_features),
        original_model.predict(original_features),
    )
    np.testing.assert_allclose(
        actual_model.predict_proba(original_features),
        original_model.predict_proba(original_features),
        rtol=0,
        atol=1e-12,
    )
    # Check that Windows can replace the mapped source immediately after training.
    replacement = folder / "replacement.npy"
    np.save(replacement, arrays["X"])
    replacement.replace(folder / "X.npy")


@pytest.mark.parametrize(
    "problem, expected",
    [
        ("dimensions", "aligned by trial"),
        ("alignment", "aligned by trial"),
        ("nan", "Invalid signal or split"),
        ("inf", "Invalid signal or split"),
        ("split", "Invalid signal or split"),
        ("subject", "subject crosses"),
        ("one_class", "both left-hand and right-hand"),
        ("missing_file", None),
    ],
)
def test_validation_rules_and_failed_load_release_all_mappings(
    dataset, monkeypatch, problem, expected
):
    folder, arrays = dataset
    if problem == "dimensions":
        arrays["X"] = arrays["X"][:, 0, :]
    elif problem == "alignment":
        arrays["y"] = arrays["y"][:-1]
    elif problem in {"nan", "inf"}:
        arrays["X"][-1, -1, -1] = np.nan if problem == "nan" else np.inf
    elif problem == "split":
        arrays["split"][-1] = "unknown"
    elif problem == "subject":
        arrays["subjects"][-1] = "S001"
    elif problem == "one_class":
        arrays["y"][:13] = 0
    for name, values in arrays.items():
        np.save(folder / f"{name}.npy", values)
    if problem == "missing_file":
        (folder / "subjects.npy").unlink()
    monkeypatch.setattr(example, "_FEATURE_BLOCK_BYTES", 4 * 37 * 8)
    real_load = np.load
    mappings = []

    def load(*args, **kwargs):
        values = real_load(*args, **kwargs)
        mappings.append(values)
        return values

    monkeypatch.setattr(np, "load", load)
    with pytest.raises(
        FileNotFoundError if problem == "missing_file" else ValueError, match=expected
    ):
        example.train(folder)
    assert mappings and all(values._mmap.closed for values in mappings)


@pytest.mark.parametrize("failure", ["fit", "nonfinite_predictions"])
def test_model_failure_releases_mappings_and_checks_prediction_finiteness(
    dataset, monkeypatch, failure
):
    folder, _ = dataset
    mappings = []
    real_load = np.load

    def load(*args, **kwargs):
        values = real_load(*args, **kwargs)
        mappings.append(values)
        return values

    def failing_pipeline(*steps):
        model = make_pipeline(*steps)
        if failure == "fit":

            def fail(*args):
                raise RuntimeError("fit failed")

            model.fit = fail
        else:
            model.predict_proba = lambda values: np.full((len(values), 2), np.nan)
        return model

    monkeypatch.setattr(np, "load", load)
    monkeypatch.setattr(example, "make_pipeline", failing_pipeline)
    with pytest.raises(
        RuntimeError if failure == "fit" else ValueError,
        match="fit failed" if failure == "fit" else "Nonfinite model predictions",
    ):
        example.train(folder)
    assert len(mappings) == 4 and all(values._mmap.closed for values in mappings)


def test_readme_mmap_example_is_bounded_executable_and_releases_files(
    dataset, monkeypatch
):
    folder, arrays = dataset
    # Read the delivered README literal without importing the preprocessing worker.
    source = Path(example.__file__).parents[1] / "outputs.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    readme = next(
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "readme"
            for target in node.targets
        )
    )
    assert "布尔或整数数组索引会复制" in readme
    snippet = readme.split("```python\n", 1)[1].split("```", 1)[0]
    # More than 32 trials makes an accidental full boolean selection detectable.
    for name, values in arrays.items():
        np.save(folder / f"{name}.npy", np.concatenate([values] * 3))
    monkeypatch.chdir(folder)
    real_load = np.load
    mappings = []

    def load(*args, **kwargs):
        assert kwargs.get("mmap_mode") == "r"
        values = real_load(*args, **kwargs)
        mappings.append(values)
        return values

    monkeypatch.setattr(np, "load", load)
    namespace = {}
    exec(snippet, namespace)
    assert len(namespace["X_batch"]) <= 32
    expected_signal = np.concatenate([arrays["X"]] * 3)[:32]
    expected_mask = np.concatenate([arrays["split"]] * 3)[:32] == "train"
    np.testing.assert_array_equal(namespace["X_batch"], expected_signal[expected_mask])
    assert len(mappings) == 3 and all(values._mmap.closed for values in mappings)


def test_copied_training_script_works_without_application_imports(dataset):
    folder, _ = dataset
    script = folder / "train_example.py"
    shutil.copy2(example.__file__, script)
    namespace = {"__name__": "standalone_example"}
    exec(compile(script.read_text(encoding="utf-8"), str(script), "exec"), namespace)
    assert namespace["train"](folder) == example.train(folder)
