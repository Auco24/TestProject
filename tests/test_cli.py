from typer.testing import CliRunner

from devtool.cli import app

runner = CliRunner()


def test_json_stdin():
    r = runner.invoke(app, ["json", "-m"], input='{ "a": 1 }')
    assert r.exit_code == 0 and r.stdout.strip() == '{"a":1}'


def test_json_error_exit_code():
    r = runner.invoke(app, ["json", "{bad"])
    assert r.exit_code == 1


def test_b64_and_ts_and_uuid():
    assert runner.invoke(app, ["b64", "hello"]).stdout.strip() == "aGVsbG8="
    assert runner.invoke(app, ["b64", "-d", "aGVsbG8="]).stdout.strip() == "hello"
    assert "2024-11-02T00:00:00Z" in runner.invoke(app, ["ts", "1730505600"]).stdout
    assert len(runner.invoke(app, ["uuid", "-n", "3"]).stdout.split()) == 3


def test_regex_and_hash():
    assert "Совпадений: 2" in runner.invoke(app, ["regex", r"\d+", "a1 b22"]).stdout
    assert runner.invoke(app, ["hash", "abc", "-a", "md5"]).stdout.strip() == "900150983cd24fb0d6963f7d28e17f72"
