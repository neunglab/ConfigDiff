import pytest


@pytest.fixture(autouse=True)
def isolated_comparison_history(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIGDIFF_HISTORY_PATH", str(tmp_path / "history.json"))
