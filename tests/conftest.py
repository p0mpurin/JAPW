import pytest


@pytest.fixture(autouse=True)
def isolated_pinterest_storage(tmp_path, monkeypatch):
    """Keep Playwright session file out of the repo cwd during tests."""
    base = tmp_path / "JAPW_data"
    base.mkdir(parents=True, exist_ok=True)

    def app_dir():
        return base

    monkeypatch.setattr("japw.pinterest.get_app_data_dir", app_dir)
