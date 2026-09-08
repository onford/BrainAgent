import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def isolated_default_storage(tmp_path, monkeypatch):
    """API lifespan tests must never resume jobs from the developer's .env."""
    monkeypatch.setenv("WORKFLOW_ROOT", str(tmp_path / "default-workflows"))
    monkeypatch.setenv("PREPROCESSING_ROOT", str(tmp_path / "default-preprocessing"))
    monkeypatch.setenv("WORKFLOW_INPUT_ROOTS", "[]")
    monkeypatch.setenv("PREPROCESSING_INPUT_ROOTS", "[]")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
