import pytest


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Every test gets its own empty SQLite database."""
    path = tmp_path / "test.sqlite3"
    monkeypatch.setenv("DEVTOOL_DB", str(path))
    monkeypatch.setenv("DEVTOOL_LANG", "ru")  # tests are written against the Russian source strings
    return path
