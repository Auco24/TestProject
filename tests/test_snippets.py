import pytest

from devtool import db, snippets
from devtool.tools import ToolError


@pytest.fixture
def conn(isolated_db):
    c = db.connect()
    yield c
    c.close()


def add(conn, **kw):
    data = {"title": "t", "content": "echo hi", "language": "bash"} | kw
    return snippets.create(conn, data)


def test_migrations_are_idempotent(isolated_db):
    db.connect().close()
    c = db.connect()
    assert c.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)


def test_create_and_get(conn):
    s = add(conn, title="  Docker cleanup ", tags="Docker, #cleanup docker", content="docker system prune\n\n")
    assert s["title"] == "Docker cleanup"
    assert s["tags"] == ["cleanup", "docker"]
    assert s["content"] == "docker system prune"
    assert s["favorite"] is False and s["use_count"] == 0
    assert snippets.get(conn, s["id"]) == s


def test_validation(conn):
    with pytest.raises(ToolError):
        add(conn, title="")
    with pytest.raises(ToolError):
        add(conn, content="   ")
    assert add(conn, language="klingon")["language"] == "text"
    with pytest.raises(ToolError):
        add(conn, tags=[f"t{i}" for i in range(30)])


def test_update_partial_and_tags(conn):
    s = add(conn, tags=["a", "b"])
    u = snippets.update(conn, s["id"], {"favorite": True})
    assert u["favorite"] and u["title"] == "t" and u["tags"] == ["a", "b"]
    u = snippets.update(conn, s["id"], {"tags": "c", "title": "new"})
    assert u["tags"] == ["c"] and u["title"] == "new"
    with pytest.raises(snippets.NotFound):
        snippets.update(conn, 999, {"title": "x"})


def test_delete_cascades_tags(conn):
    s = add(conn, tags=["x"])
    snippets.delete(conn, s["id"])
    assert conn.execute("SELECT COUNT(*) FROM snippet_tags").fetchone()[0] == 0
    with pytest.raises(snippets.NotFound):
        snippets.delete(conn, s["id"])


def test_search(conn):
    a = add(conn, title="Git undo", content="git reset --soft HEAD~1", tags=["git"])
    b = add(conn, title="Docker prune", content="docker system prune", tags=["docker", "cleanup"])
    c = add(conn, title="Retry", content="def retry(): pass", language="python", tags=["cleanup"], favorite=True)

    ids = lambda r: [s["id"] for s in r]
    assert ids(snippets.search(conn, "git")) == [a["id"]]
    assert ids(snippets.search(conn, "PRUNE docker")) == [b["id"]]       # all terms, case-insensitive
    assert set(ids(snippets.search(conn, "#cleanup"))) == {b["id"], c["id"]}
    assert ids(snippets.search(conn, "lang:python")) == [c["id"]]
    assert ids(snippets.search(conn, "", tags=["cleanup", "docker"])) == [b["id"]]
    assert ids(snippets.search(conn, "", favorite=True)) == [c["id"]]
    assert snippets.search(conn, "nothing-matches") == []
    # favorites first
    assert ids(snippets.search(conn))[0] == c["id"]


def test_search_escapes_like_wildcards(conn):
    add(conn, title="percent", content="100% done")
    add(conn, title="other", content="nothing")
    assert len(snippets.search(conn, "%")) == 1
    assert len(snippets.search(conn, "_")) == 0


def test_popular_sort_and_mark_used(conn):
    a = add(conn, title="a")
    b = add(conn, title="b")
    snippets.mark_used(conn, b["id"])
    snippets.mark_used(conn, b["id"])
    r = snippets.search(conn, sort="popular")
    assert [s["title"] for s in r] == ["b", "a"]
    assert r[0]["use_count"] == 2 and r[0]["last_used_at"]
    with pytest.raises(snippets.NotFound):
        snippets.mark_used(conn, 999)


def test_tags_and_stats(conn):
    add(conn, tags=["git", "x"])
    add(conn, tags=["git"], language="python", favorite=True)
    assert snippets.all_tags(conn) == [{"tag": "git", "count": 2}, {"tag": "x", "count": 1}]
    st = snippets.stats(conn)
    assert st["total"] == 2 and st["favorites"] == 1
    assert {l["language"] for l in st["languages"]} == {"bash", "python"}


def test_export_import_roundtrip(conn, tmp_path):
    add(conn, title="one", tags=["a"], favorite=True)
    add(conn, title="two", description="d")
    data = snippets.export_all(conn)
    assert data["format"] == "devtool-snippets"
    assert [s["title"] for s in data["snippets"]] == ["one", "two"]

    other = db.connect(tmp_path / "other.sqlite3")
    assert snippets.import_all(other, data) == {"added": 2, "skipped": 0}
    assert snippets.import_all(other, data) == {"added": 0, "skipped": 2}
    imported = snippets.search(other, "one")[0]
    assert imported["favorite"] and imported["tags"] == ["a"]
    with pytest.raises(ToolError):
        snippets.import_all(other, {"nope": 1})


def test_examples(conn):
    r = snippets.add_examples(conn)
    assert r["added"] == len(snippets.EXAMPLES)
    assert snippets.add_examples(conn)["added"] == 0
