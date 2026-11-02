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


def test_snip_flow(tmp_path):
    r = runner.invoke(app, ["snip", "add", "git status -sb", "-t", "Short status", "-g", "git"])
    assert r.exit_code == 0 and "#1" in r.stdout
    r = runner.invoke(app, ["snip", "add", "-", "-t", "Py", "-l", "python", "--fav"], input="print('x')\n")
    assert r.exit_code == 0

    out = runner.invoke(app, ["snip", "find", "status"]).stdout
    assert "Short status" in out and "Py" not in out
    assert "Py" in runner.invoke(app, ["snip", "find", "lang:python"]).stdout
    assert runner.invoke(app, ["snip", "show", "1", "--raw"]).stdout == "git status -sb\n"
    assert "#git" in runner.invoke(app, ["snip", "tags"]).stdout
    assert runner.invoke(app, ["snip", "copy", "1"]).exit_code == 0

    export = tmp_path / "s.json"
    assert runner.invoke(app, ["snip", "export", str(export)]).exit_code == 0
    assert "пропущено дубликатов: 2" in runner.invoke(app, ["snip", "import", str(export)]).stdout

    assert runner.invoke(app, ["snip", "rm", "1", "-y"]).exit_code == 0
    assert runner.invoke(app, ["snip", "show", "1"]).exit_code == 1
    assert "Ничего не найдено" in runner.invoke(app, ["snip", "find", "status"]).stdout


def test_journal_cli(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert "Сделал записано" in runner.invoke(app, ["log", "починил", "баг"]).stdout
    assert "План записано" in runner.invoke(app, ["log", "-p", "тесты"]).stdout
    assert runner.invoke(app, ["log", "-y", "вчерашнее"]).exit_code == 0

    out = runner.invoke(app, ["journal", "show", "--no-commits"]).stdout
    assert "Сегодня" in out and "починил баг" in out and "вчерашнее" in out

    assert "Готово: тесты" in runner.invoke(app, ["journal", "done", "2"]).stdout
    report = runner.invoke(app, ["standup", "-f", "md"]).stdout
    assert "**Сегодня:**" in report and "починил баг ✓" in report

    assert runner.invoke(app, ["journal", "rm", "1"]).exit_code == 0
    assert runner.invoke(app, ["journal", "rm", "1"]).exit_code == 1
    assert runner.invoke(app, ["journal", "roots", "--add", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["journal", "roots", "--add", "/missing/dir"]).exit_code == 1
