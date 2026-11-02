import os
import subprocess
from datetime import date, timedelta

import pytest

from devtool import db, gitinfo, journal, settings
from devtool.tools import ToolError

MON = date(2026, 11, 2)  # a Monday


@pytest.fixture
def conn(isolated_db):
    c = db.connect()
    yield c
    c.close()


def git(repo, *args, when=None):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "projects" / "my-app"
    r.mkdir(parents=True)
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "me@example.com")
    git(r, "config", "user.name", "Me")
    git(r, "config", "commit.gpgsign", "false")
    return r


def commit(repo, msg, when, email="me@example.com"):
    (repo / "f.txt").write_text(msg)
    git(repo, "add", ".")
    git(repo, "-c", f"user.email={email}", "commit", "-q", "-m", msg, when=when)


# ------------------------------------------------------------------ helpers

def test_previous_workday():
    assert journal.previous_workday(MON) == date(2026, 10, 30)  # Fri
    assert journal.previous_workday(MON + timedelta(days=1)) == MON
    assert journal.previous_workday(date(2026, 11, 1)) == date(2026, 10, 30)  # Sun -> Fri
    assert journal.previous_workday(date(2026, 10, 31)) == date(2026, 10, 30)  # Sat -> Fri


def test_human_day():
    assert journal.human_day(MON, MON) == "Сегодня"
    assert journal.human_day(MON - timedelta(days=1), MON) == "Вчера"
    assert journal.human_day(date(2026, 10, 30), MON) == "Пт, 30 октября"
    assert journal.human_day(date(2025, 1, 1), MON) == "Ср, 1 января 2025"


# --------------------------------------------------------------------- CRUD

def test_add_update_delete(conn):
    e = journal.add(conn, "  починил #auth баг ", "done", project="api", day="2026-11-01")
    assert e["text"] == "починил #auth баг" and e["day"] == "2026-11-01"
    assert e["tags"] == ["auth"] and e["project"] == "api" and not e["completed"]

    p = journal.add(conn, "написать тесты", "plan")
    assert journal.update(conn, p["id"], {"completed": True})["completed"]
    assert not journal.update(conn, p["id"], {"completed": False})["completed"]
    assert journal.update(conn, p["id"], {"text": "новый", "kind": "note"})["kind"] == "note"

    journal.delete(conn, e["id"])
    with pytest.raises(journal.NotFound):
        journal.get(conn, e["id"])
    with pytest.raises(journal.NotFound):
        journal.delete(conn, e["id"])


def test_validation(conn):
    with pytest.raises(ToolError):
        journal.add(conn, "   ")
    with pytest.raises(ToolError):
        journal.add(conn, "x", "party")
    with pytest.raises(ToolError):
        journal.add(conn, "x", day="вчера")
    with pytest.raises(ToolError):
        journal.add(conn, "x" * 3000)


def test_repo_detection(conn, repo):
    sub = repo / "src"
    sub.mkdir()
    e = journal.add(conn, "сделал", cwd=str(sub))
    assert e["project"] == "my-app" and e["branch"] == "main"
    assert e["repo_path"] == str(repo.resolve())

    outside = journal.add(conn, "вне репо", cwd=str(repo.parent))
    assert outside["project"] is None


# ----------------------------------------------------------------- timeline

def test_timeline_groups_and_paginates(conn, monkeypatch):
    monkeypatch.setattr(journal, "today", lambda: MON)
    journal.add(conn, "a", day=MON)
    journal.add(conn, "b", "plan", day=MON)
    journal.add(conn, "old", day=MON - timedelta(days=20))

    r = journal.timeline(conn, days=7, with_commits=False)
    assert [d["date"] for d in r["days"]] == ["2026-11-02"]
    assert r["days"][0]["label"] == "Сегодня" and len(r["days"][0]["entries"]) == 2
    assert r["has_more"] is True

    r2 = journal.timeline(conn, days=30, before=r["next_before"], with_commits=False)
    assert [e["text"] for d in r2["days"] for e in d["entries"]] == ["old"]
    assert r2["has_more"] is False

    assert journal.timeline(conn, q="ol", days=60, with_commits=False)["days"][0]["entries"][0]["text"] == "old"


def test_timeline_includes_commits(conn, repo, monkeypatch):
    monkeypatch.setattr(journal, "today", lambda: MON)
    commit(repo, "feat: login", "2026-11-02T10:00:00")
    commit(repo, "someone else", "2026-11-02T11:00:00", email="other@example.com")
    settings.set(conn, "git_roots", [str(repo.parent)])

    day = journal.timeline(conn, days=3)["days"][0]
    assert [c["subject"] for c in day["commits"]] == ["feat: login"]  # only my commits
    assert day["commits"][0]["project"] == "my-app"


# ------------------------------------------------------------------ standup

def test_standup_monday_covers_friday_and_weekend(conn, repo):
    fri, sun = date(2026, 10, 30), date(2026, 11, 1)
    journal.add(conn, "сделал API", day=fri, project="api")
    journal.add(conn, "чинил прод", day=sun)
    journal.add(conn, "это было в четверг", day=fri - timedelta(days=1))
    plan = journal.add(conn, "релиз", "plan", day=fri)
    journal.add(conn, "жду ревью", "blocker", day=MON)
    resolved = journal.add(conn, "старый блокер", "blocker", day=fri)
    journal.update(conn, resolved["id"], {"completed": True})
    journal.add(conn, "просто мысль", "note", day=MON)

    commit(repo, "fix: crash", "2026-10-30T15:00:00")
    commit(repo, "сделал API", "2026-10-30T16:00:00")  # duplicate of an entry -> skipped
    settings.set(conn, "git_roots", [str(repo.parent)])

    r = journal.standup(conn, for_day=MON, fmt="md")
    assert r["since"] == "2026-10-30" and r["since_label"] == "С пятницы"
    assert [e["text"] for e in r["done"]] == ["сделал API", "чинил прод"]
    assert [c["subject"] for c in r["commits"]] == ["fix: crash"]
    assert [e["id"] for e in r["plans"]] == [plan["id"]]
    assert [e["text"] for e in r["blockers"]] == ["жду ревью"]

    text = r["text"]
    assert text.startswith("**С пятницы:**\n- сделал API (api)\n- чинил прод\n- fix: crash (my-app)")
    assert "**Сегодня:**\n- релиз" in text
    assert "**Блокеры:**\n- жду ревью" in text
    assert "мысль" not in text and "четверг" not in text and "старый" not in text


def test_standup_formats_and_completed_plan(conn):
    tue = MON + timedelta(days=1)
    p = journal.add(conn, "задача", "plan", day=MON)
    conn.execute("UPDATE journal SET completed_at = ? WHERE id = ?", (MON.isoformat() + "T18:00:00+00:00", p["id"]))
    r = journal.standup(conn, for_day=tue, fmt="slack", with_commits=False)
    assert r["since_label"] == "Вчера"
    assert r["text"].startswith("*Вчера:*\n• задача")
    assert "*Блокеры:*\n• нет" in r["text"]
    # a plan finished on the stand-up day itself is listed under "today" with a check mark
    q = journal.add(conn, "сегодняшний план", "plan", day=tue)
    conn.execute("UPDATE journal SET completed_at = ? WHERE id = ?", (tue.isoformat() + "T09:00:00+00:00", q["id"]))
    assert "• сегодняшний план ✓" in journal.standup(conn, for_day=tue, fmt="slack", with_commits=False)["text"]
    plain = journal.standup(conn, for_day=tue, fmt="text", with_commits=False)["text"]
    assert plain.startswith("ВЧЕРА:\n  - задача")
    with pytest.raises(ToolError):
        journal.standup(conn, fmt="html")


# -------------------------------------------------------------------- stats

def test_stats_streak_and_heatmap(conn, monkeypatch):
    monkeypatch.setattr(journal, "today", lambda: MON)
    for i in range(3):
        journal.add(conn, f"d{i}", day=MON - timedelta(days=i))
    journal.add(conn, "gap", day=MON - timedelta(days=5))
    journal.add(conn, "p", "plan", day=MON)
    st = journal.stats(conn, with_commits=False)
    assert st["streak"] == 3
    assert st["total"] == 5 and st["open_plans"] == 1
    assert st["heatmap"]["counts"]["2026-11-02"] == 2
    assert date.fromisoformat(st["heatmap"]["start"]).weekday() == 0


def test_streak_counts_from_yesterday_when_today_empty(conn, monkeypatch):
    monkeypatch.setattr(journal, "today", lambda: MON)
    journal.add(conn, "x", day=MON - timedelta(days=1))
    journal.add(conn, "y", day=MON - timedelta(days=2))
    assert journal.stats(conn, with_commits=False)["streak"] == 2


def test_find_repos_skips_noise(tmp_path, repo):
    (tmp_path / "projects" / "node_modules" / "x" / ".git").mkdir(parents=True)
    (tmp_path / "projects" / "plain").mkdir()
    assert gitinfo.find_repos([str(tmp_path / "projects")]) == [str(repo.resolve())]
    assert gitinfo.find_repos([str(tmp_path / "missing")]) == []
