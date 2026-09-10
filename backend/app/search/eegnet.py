"""Standalone CPU EEGNet-8,2; callers supply ONLY outer-training trials.

References: https://arxiv.org/abs/1611.08024v4 and
https://github.com/vlawhern/arl-eegmodels/blob/master/EEGModels.py (EEGNet).
This independent PyTorch implementation follows the final architecture, not v1.
At 160 Hz we use an 80-sample temporal kernel (0.5 s), pool by 5 to
32 Hz, then the official 16-sample separable kernel and pool by 8.
Dropout=0.5 is fixed; no filtering, resampling or subject adaptation occurs.
Training policy (100 epochs, patience 15) is a project policy, not a claim
to reproduce the paper's experiment. Explicit overrides are frozen per protocol.
Torch is imported only when constructing, training or loading a model.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from hashlib import sha256
import math
from pathlib import Path
from threading import RLock


_TORCH_LOCK = RLock()  # RNG and deterministic/thread settings are process-global.


@dataclass(frozen=True)
class TrainingConfig:
    max_epochs: int = 100
    patience: int = 15
    batch_size: int = 64
    learning_rate: float = 0.001
    validation_fraction: float = 0.2
    split_seed: int = 0  # Shared split across the parent's three model seeds.


def _config(value=None):
    cfg = value if isinstance(value, TrainingConfig) else TrainingConfig(**(value or {}))
    for name in ("max_epochs", "patience", "batch_size"):
        item = getattr(cfg, name)
        if type(item) is not int or item < 1:
            raise ValueError(f"{name} must be a positive integer")
    if type(cfg.split_seed) is not int:
        raise ValueError("split_seed must be an integer")
    for name in ("learning_rate", "validation_fraction"):
        item = getattr(cfg, name)
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
            raise ValueError(f"{name} must be finite")
    if cfg.learning_rate <= 0 or not 0 < cfg.validation_fraction < 1:
        raise ValueError("learning_rate must be positive and validation_fraction in (0,1)")
    return cfg


def protocol(training_config=None):
    """Return fresh JSON settings without importing torch (or numpy)."""
    return {
        "name": "eegnet", "version": 1, "classes": [0, 1],
        "input": "N,C,T", "sfreq": 160.0,
        "output": {"shape": "N,2", "dtype": "float64", "row_normalized": True},
        "architecture": {
            "F1": 8, "D": 2, "F2": 16, "temporal_kernel": 80,
            "temporal_kernel_seconds": 0.5, "separable_kernel": 16,
            "pool_sizes": [5, 8], "dropout": 0.5,
            "spatial_max_norm": 1.0, "classifier_max_norm": 0.25,
            "batch_norm_epsilon": 0.001, "batch_norm_torch_momentum": 0.01,
            "initialization": "glorot_uniform", "activation": "elu",
        },
        "training": asdict(_config(training_config)),
        "optimizer": {"name": "Adam", "betas": [0.9, 0.999], "eps": 1e-7,
                      "weight_decay": 0.0},
        "runtime": {"device": "cpu", "threads": 1, "deterministic": True,
                    "torch_version": "2.8.0+cpu"},
        "validation": "label-independent subject SHA256 rank; ceil(fraction * subjects)",
        "selection": "minimum inner-validation mean trial logloss; first minimum wins; no refit",
        "normalization": "per-channel population mean/std from inner-fit trials and time only; zero std -> 1",
        "sources": ["https://arxiv.org/abs/1611.08024v4",
                    "https://github.com/vlawhern/arl-eegmodels/blob/master/EEGModels.py"],
    }


def build_model(n_channels, n_times, *, sfreq=160.0):
    """Lazy model factory. Forward accepts [N,1,C,T] and returns two logits."""
    if sfreq != 160.0:
        raise ValueError("EEGNet protocol requires sfreq=160 Hz; resample upstream")
    if n_channels < 1 or n_times < 40:
        raise ValueError("EEGNet needs >=1 channel and >=40 time samples")
    import torch
    from torch import nn

    class EEGNet(nn.Module):
        def __init__(self):
            super().__init__()
            # Explicit asymmetric padding matches Keras SAME for even kernels.
            self.temporal = nn.Conv2d(1, 8, (1, 80), bias=False)
            self.bn1 = nn.BatchNorm2d(8, eps=0.001, momentum=0.01)
            self.spatial = nn.Conv2d(8, 16, (n_channels, 1), groups=8, bias=False)
            self.bn2 = nn.BatchNorm2d(16, eps=0.001, momentum=0.01)
            self.pool1 = nn.AvgPool2d((1, 5))
            self.drop1 = nn.Dropout(0.5)
            self.separable = nn.Conv2d(16, 16, (1, 16), groups=16, bias=False)
            self.pointwise = nn.Conv2d(16, 16, 1, bias=False)
            self.bn3 = nn.BatchNorm2d(16, eps=0.001, momentum=0.01)
            self.pool2 = nn.AvgPool2d((1, 8))
            self.drop2 = nn.Dropout(0.5)
            self.classifier = nn.Linear(16 * (n_times // 5 // 8), 2)
            for layer in self.modules():
                if isinstance(layer, (nn.Conv2d, nn.Linear)):
                    # Keras depthwise fan counts refer to [H,W,input,multiplier].
                    if layer is self.spatial or layer is self.separable:
                        area = math.prod(layer.kernel_size)
                        bound = math.sqrt(6 / (area * (layer.in_channels + layer.out_channels / layer.in_channels)))
                        nn.init.uniform_(layer.weight, -bound, bound)
                    else:
                        nn.init.xavier_uniform_(layer.weight)
                    if layer.bias is not None:
                        nn.init.zeros_(layer.bias)
            self.constrain_weights()

        def forward(self, x):
            f = torch.nn.functional
            x = self.bn1(self.temporal(f.pad(x, (39, 40, 0, 0))))
            x = self.drop1(self.pool1(f.elu(self.bn2(self.spatial(x)))))
            x = self.pointwise(self.separable(f.pad(x, (7, 8, 0, 0))))
            x = self.drop2(self.pool2(f.elu(self.bn3(x))))
            return self.classifier(x.flatten(1))

        @torch.no_grad()
        def constrain_weights(self):
            for weight, limit in ((self.spatial.weight, 1.0), (self.classifier.weight, 0.25)):
                norms = weight.flatten(1).norm(dim=1)
                scale = (limit / norms.clamp_min(1e-12)).clamp(max=1)
                weight.mul_(scale.reshape((-1,) + (1,) * (weight.ndim - 1)))

    return EEGNet().cpu()


@contextmanager
def _runtime(seed):
    import torch
    with _TORCH_LOCK:
        threads = torch.get_num_threads()
        deterministic = torch.are_deterministic_algorithms_enabled()
        warn_only = torch.is_deterministic_algorithms_warn_only_enabled()
        try:
            torch.set_num_threads(1)
            torch.use_deterministic_algorithms(True)
            with torch.random.fork_rng(devices=[]):
                torch.random.default_generator.manual_seed(seed)
                yield torch
        finally:
            torch.use_deterministic_algorithms(deterministic, warn_only=warn_only)
            torch.set_num_threads(threads)


def _check_cancel(callback):
    if callback is not None and callback():
        raise InterruptedError("EEGNet training cancelled")


def _array(X, *, allow_empty=False):
    import numpy as np
    X = np.asarray(X)
    if X.ndim != 3 or X.shape[1] < 1 or X.shape[2] < 40 or (not allow_empty and not len(X)):
        raise ValueError("X must have shape [N,C,T], C>=1, T>=40 and nonempty training trials")
    if X.dtype.kind not in "fiu" or not np.isfinite(X).all():
        raise ValueError("X must contain finite real numbers")
    return X


def _split_subjects(subjects, n, cfg):
    import numpy as np
    subjects = np.asarray(subjects)
    if subjects.ndim != 1 or len(subjects) != n or subjects.dtype.kind not in "iuUS":
        raise ValueError("train_subjects must be one integer/string subject ID per trial")
    subjects = subjects.astype(str)
    unique = sorted(set(subjects.tolist()))
    if len(unique) < 2 or any(not s for s in unique):
        raise ValueError("at least two nonempty training subject IDs are required")
    ordered = sorted(unique, key=lambda s: (sha256(f"{cfg.split_seed}:{s}".encode()).hexdigest(), s))
    count = min(len(unique) - 1, math.ceil(len(unique) * cfg.validation_fraction))
    validation = sorted(ordered[:count])
    val_mask = np.isin(subjects, validation)
    return np.flatnonzero(~val_mask), np.flatnonzero(val_mask), sorted(set(unique) - set(validation)), validation


def train_fold(train_X, train_y, train_subjects, *, seed, sfreq, checkpoint_path,
               cancel_check=None, training_config=None):
    """Fit from scratch on an inner subject split of ONLY outer-training data.

    `training_config` accepts protocol()['training'] or a frozen TrainingConfig.
    Cancellation callbacks may raise their own exception or return True.
    The checkpoint is exclusively created; existing artifacts are never overwritten.
    Returned metadata is JSON serializable and path-independent; the caller owns
    checkpoint artifact paths. Validation never updates normalization,
    gradients, or BatchNorm statistics. No outer-development inputs are accepted.
    """
    import numpy as np
    cfg = _config(training_config)
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError("seed must be an integer in [0,2**63)")
    if sfreq != 160.0:
        raise ValueError("EEGNet protocol requires sfreq=160 Hz; resample upstream")
    path = Path(checkpoint_path)
    if path.exists():
        raise FileExistsError(path)
    _check_cancel(cancel_check)
    X = _array(train_X)
    y = np.asarray(train_y)
    if y.shape != (len(X),) or y.dtype.kind not in "biuf" or not np.isin(y, [0, 1]).all():
        raise ValueError("train_y must contain one 0/1 label per trial")
    fit, val, fit_subjects, val_subjects = _split_subjects(train_subjects, len(X), cfg)
    if len(np.unique(y[fit])) != 2:
        raise ValueError("inner-fit subjects must contain both classes; label-driven resplitting is forbidden")
    fit_X = X[fit].astype(np.float64)
    mean = fit_X.mean(axis=(0, 2), keepdims=True)
    std = fit_X.std(axis=(0, 2), keepdims=True)
    if not np.isfinite(mean).all() or not np.isfinite(std).all():
        raise ValueError("inner-fit normalization statistics are non-finite")
    std = np.where(std == 0, 1.0, std)
    del fit_X
    with _runtime(seed) as torch:
        model = build_model(X.shape[1], X.shape[2], sfreq=sfreq)
        norm = ((X.astype(np.float64) - mean) / std).astype(np.float32)
        if not np.isfinite(norm).all():
            raise ValueError("normalization produced non-finite values")
        data = torch.from_numpy(norm[:, None])
        labels = torch.from_numpy(y.astype(np.int64))
        optimizer = torch.optim.Adam(model.parameters(), lr=cfg.learning_rate, eps=1e-7)
        best_loss, best_epoch, best_state = math.inf, 0, None
        history = []
        for epoch in range(1, cfg.max_epochs + 1):
            _check_cancel(cancel_check)
            model.train()
            order = fit[torch.randperm(len(fit)).numpy()]
            fit_loss = 0.0
            for start in range(0, len(order), cfg.batch_size):
                _check_cancel(cancel_check)
                idx = order[start:start + cfg.batch_size]
                optimizer.zero_grad(set_to_none=True)
                loss = torch.nn.functional.cross_entropy(model(data[idx]), labels[idx])
                if not torch.isfinite(loss):
                    raise ValueError("non-finite EEGNet training loss")
                loss.backward()
                optimizer.step()
                model.constrain_weights()
                fit_loss += float(loss.detach()) * len(idx)
            model.eval()
            val_loss = 0.0
            with torch.inference_mode():
                for start in range(0, len(val), cfg.batch_size):
                    _check_cancel(cancel_check)
                    idx = val[start:start + cfg.batch_size]
                    val_loss += float(torch.nn.functional.cross_entropy(model(data[idx]), labels[idx], reduction="sum"))
            val_loss /= len(val)
            if not math.isfinite(val_loss):
                raise ValueError("non-finite EEGNet validation loss")
            history.append({"epoch": epoch, "train_logloss": fit_loss / len(fit), "validation_logloss": val_loss})
            if val_loss < best_loss:
                best_loss, best_epoch = val_loss, epoch
                best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            _check_cancel(cancel_check)
            if epoch - best_epoch >= cfg.patience:
                break
        metadata = {
            "learner": "eegnet", "seed": seed, "sfreq": float(sfreq),
            "protocol": protocol(cfg),
            "torch_version": str(torch.__version__), "device": "cpu", "threads": 1,
            "architecture": {"n_channels": int(X.shape[1]), "n_times": int(X.shape[2])},
            "fit_subjects": fit_subjects, "validation_subjects": val_subjects,
            "outer_training_subjects": sorted(fit_subjects + val_subjects),
            "normalization_fit_subjects": fit_subjects.copy(),
            "n_fit_trials": len(fit), "n_validation_trials": len(val),
            "best_epoch": best_epoch, "best_validation_logloss": best_loss,
            "epochs_trained": len(history), "stopped_early": len(history) < cfg.max_epochs,
            "history": history,
        }
        checkpoint = {"format_version": 1, "state_dict": best_state,
                      "normalization": {"mean": torch.from_numpy(mean), "std": torch.from_numpy(std)},
                      "metadata": metadata}
        _check_cancel(cancel_check)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation also guards races with another fold/worker.
        with path.open("xb") as stream:
            torch.save(checkpoint, stream)
    return metadata


def predict_checkpoint(path, X):
    """Return row-normalized float64 [N,2] probabilities; no labels/refit."""
    import numpy as np
    X = _array(X, allow_empty=True)
    with _runtime(0) as torch:
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
        if checkpoint.get("format_version") != 1:
            raise ValueError("unsupported EEGNet checkpoint format")
        meta = checkpoint["metadata"]
        arch = meta["architecture"]
        if tuple(X.shape[1:]) != (arch["n_channels"], arch["n_times"]):
            raise ValueError("prediction channels/time must match checkpoint")
        model = build_model(**arch, sfreq=meta["sfreq"])
        model.load_state_dict(checkpoint["state_dict"], strict=True)
        model.eval()
        norm = checkpoint["normalization"]
        mean, std = norm["mean"].numpy(), norm["std"].numpy()
        if not np.isfinite(mean).all() or not np.isfinite(std).all() or (std <= 0).any():
            raise ValueError("invalid checkpoint normalization")
        results = []
        batch_size = _config(meta["protocol"]["training"]).batch_size
        with torch.inference_mode():
            for start in range(0, len(X), batch_size):
                batch = ((X[start:start + batch_size].astype(np.float64) - mean) / std).astype(np.float32)
                if not np.isfinite(batch).all():
                    raise ValueError("prediction normalization produced non-finite values")
                probabilities = model(torch.from_numpy(batch[:, None])).softmax(dim=1).numpy().astype(np.float64)
                if not np.isfinite(probabilities).all():
                    raise ValueError("non-finite EEGNet probabilities")
                probabilities /= probabilities.sum(axis=1, keepdims=True)
                results.append(probabilities)
        return np.concatenate(results) if results else np.empty((0, 2), dtype=np.float64)
