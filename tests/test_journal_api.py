from fastapi.testclient import TestClient

from devtool.api import app

client = TestClient(app)


def test_journal_flow(tmp_path):
    r = client.post("/api/journal", json={"text": "сделал", "kind": "done", "project": "web"})
    assert r.status_code == 201
    e = r.json()
    p = client.post("/api/journal", json={"text": "план", "kind": "plan"}).json()

    days = client.get("/api/journal").json()["days"]
    assert days[0]["label"] == "Сегодня" and len(days[0]["entries"]) == 2

    assert client.patch(f"/api/journal/{p['id']}", json={"completed": True}).json()["completed"]
    assert client.delete(f"/api/journal/{e['id']}").status_code == 204
    assert client.delete(f"/api/journal/{e['id']}").status_code == 404

    meta = client.get("/api/journal/meta").json()
    assert meta["stats"]["total"] == 1 and "done" in meta["kinds"]
    assert any(pr["name"] == "web" for pr in meta["projects"]) is False  # deleted

    st = client.get("/api/journal/standup", params={"format": "slack"}).json()
    assert st["format"] == "slack" and "*Сегодня:*" in st["text"]


def test_journal_errors():
    assert client.post("/api/journal", json={"text": ""}).status_code == 400
    assert client.post("/api/journal", json={"text": "x", "kind": "nope"}).status_code == 400
    assert client.patch("/api/journal/999", json={"text": "x"}).status_code == 404
    assert client.get("/api/journal/standup", params={"format": "pdf"}).status_code == 400


def test_git_roots_setting(tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    r = client.put("/api/settings/git_roots", json={"roots": [str(tmp_path), str(tmp_path)]})
    assert r.status_code == 200
    assert r.json()["roots"] == [str(tmp_path.resolve())]
    assert r.json()["repos"] == [str((tmp_path / "repo").resolve())]
    assert client.put("/api/settings/git_roots", json={"roots": ["/definitely/missing"]}).status_code == 400
    assert client.put("/api/settings/git_roots", json={"roots": "nope"}).status_code == 400
