import pytest
from fastapi.testclient import TestClient

from devtool import db, repos, settings
from devtool.api import app
from devtool.tools import ToolError
from gitutil import clone, commit, git, init


@pytest.mark.parametrize("remote,expected", [
    ("git@github.com:user/repo.git", "https://github.com/user/repo"),
    ("https://github.com/user/repo.git", "https://github.com/user/repo"),
    ("https://user:s3cret@gitlab.com/group/sub/repo.git", "https://gitlab.com/group/sub/repo"),
    ("ssh://git@bitbucket.org/team/repo.git", "https://bitbucket.org/team/repo"),
    ("/local/path/repo.git", None),
    (None, None),
])
def test_web_url(remote, expected):
    assert repos.web_url(remote) == expected


def test_safe_remote_hides_token():
    assert repos.safe_remote("https://user:tok@github.com/a/b.git") == "https://github.com/a/b.git"
    assert repos.safe_remote("git@github.com:a/b.git") == "git@github.com:a/b.git"


@pytest.fixture
def world(tmp_path):
    """origin (non-bare, on a side branch so pushes are allowed) + a working clone."""
    origin = init(tmp_path / "origin")
    commit(origin, "init")
    work = clone(origin, tmp_path / "projects" / "work")
    git(origin, "checkout", "-q", "-b", "side")
    return origin, work


def test_clean_status(world):
    _, work = world
    s = repos.repo_status(str(work))
    assert s["health"] == "clean" and s["branch"] == "main" and s["upstream"] == "origin/main"
    assert s["changes"] == 0 and s["ahead"] == 0 and s["behind"] == 0
    assert s["last_commit"]["subject"] == "init"
    assert len(s["activity"]) == repos.ACTIVITY_DAYS and s["activity"][-1] >= 1


def test_dirty_ahead_behind_stash(world):
    origin, work = world
    git(origin, "checkout", "-q", "main")
    commit(origin, "remote change", file="r.txt")
    git(origin, "checkout", "-q", "side")
    commit(work, "local change", file="l.txt")
    git(work, "fetch", "-q")
    (work / "f.txt").write_text("to stash")
    git(work, "stash", "-q")
    (work / "l.txt").write_text("edited")
    (work / "new.txt").write_text("x")
    (work / "staged.txt").write_text("s")
    git(work, "add", "staged.txt")

    s = repos.repo_status(str(work), detailed=True)
    assert (s["ahead"], s["behind"]) == (1, 1)
    assert (s["staged"], s["modified"], s["untracked"]) == (1, 1, 1)
    assert s["stash"] == 1 and s["health"] == "dirty"
    assert {f["path"] for f in s["files"]} == {"l.txt", "new.txt", "staged.txt"}
    assert s["last_fetch"] is not None


def test_branches_merged_stale_and_safe_delete(world):
    _, work = world
    git(work, "branch", "merged-feature")
    git(work, "checkout", "-q", "-b", "old-unmerged")
    commit(work, "ancient", when="2020-01-01T10:00:00", file="old.txt")
    git(work, "checkout", "-q", "main")

    brs = {b["name"]: b for b in repos.branches(str(work))}
    assert brs["main"]["current"] and brs["main"]["default"] and not brs["main"]["merged"]
    assert brs["merged-feature"]["merged"]
    assert brs["old-unmerged"]["stale"] and not brs["old-unmerged"]["merged"]

    r = repos.delete_branches(str(work), ["merged-feature", "old-unmerged", "main", "nope"])
    assert r["deleted"] == ["merged-feature"]
    assert {e["name"] for e in r["errors"]} == {"old-unmerged", "main", "nope"}
    assert "old-unmerged" in {b["name"] for b in repos.branches(str(work))}


def test_pull_ff(world):
    origin, work = world
    git(origin, "checkout", "-q", "main")
    commit(origin, "upstream", file="u.txt")
    git(origin, "checkout", "-q", "side")
    assert repos.fetch(str(work))["behind"] == 1
    assert repos.pull_ff(str(work))["behind"] == 0
    (work / "dirty.txt").write_text("x")
    with pytest.raises(ToolError):
        repos.pull_ff(str(work))


def test_local_repo_and_detached(tmp_path):
    r = init(tmp_path / "solo")
    s = repos.repo_status(str(r))
    assert s["last_commit"] is None and s["branch"] == "main"
    commit(r, "one")
    commit(r, "two")
    git(r, "checkout", "-q", "HEAD~1")
    s = repos.repo_status(str(r))
    assert s["detached"] and s["branch"] is None and s["health"] == "local"


def test_all_status_sorts_attention_first(world, tmp_path):
    _, work = world
    clean = clone(tmp_path / "origin", tmp_path / "projects" / "aaa-clean")
    (work / "x.txt").write_text("x")
    data = repos.all_status([str(clean), str(work)])
    assert [r["name"] for r in data["repos"]] == ["work", "aaa-clean"]
    assert data["summary"] == {
        "total": 2, "dirty": 1, "unpushed": 0, "behind": 0, "clean": 1, "stale_branches": 0, "merged_branches": 0,
    }


def test_api_only_allows_known_repos(world, tmp_path):
    _, work = world
    client = TestClient(app)
    with db.session() as conn:
        settings.set(conn, "git_roots", [str(tmp_path / "projects")])

    data = client.get("/api/git/repos").json()
    assert [r["name"] for r in data["repos"]] == ["work"] and data["git"] is True

    assert client.get("/api/git/repo", params={"path": str(work)}).json()["branches"]
    assert client.get("/api/git/repo", params={"path": str(tmp_path / "origin")}).status_code == 400
    assert client.post("/api/git/fetch", json={"path": "/etc"}).status_code == 400
    assert client.post("/api/git/fetch", json={}).json()["ok"] == 1
    assert client.post("/api/git/delete-branches", json={"path": str(work), "branches": []}).status_code == 400
    r = client.post("/api/git/delete-branches", json={"path": str(work), "branches": ["main"]}).json()
    assert r["deleted"] == [] and r["errors"]
