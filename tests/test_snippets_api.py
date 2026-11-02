from fastapi.testclient import TestClient

from devtool.api import app

client = TestClient(app)


def create(**kw):
    body = {"title": "Docker", "content": "docker ps", "language": "bash", "tags": ["docker"]} | kw
    r = client.post("/api/snippets", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_crud_flow():
    s = create()
    assert client.get(f"/api/snippets/{s['id']}").json()["title"] == "Docker"

    r = client.patch(f"/api/snippets/{s['id']}", json={"favorite": True, "tags": "a, b"})
    assert r.status_code == 200 and r.json()["favorite"] and r.json()["tags"] == ["a", "b"]

    assert client.post(f"/api/snippets/{s['id']}/use").json()["use_count"] == 1

    assert client.delete(f"/api/snippets/{s['id']}").status_code == 204
    assert client.get(f"/api/snippets/{s['id']}").status_code == 404
    assert client.delete(f"/api/snippets/{s['id']}").status_code == 404


def test_list_filters():
    create(title="git undo", content="git reset", tags=["git"])
    create(title="py", content="print()", language="python", tags=["py"], favorite=True)
    assert client.get("/api/snippets").json()["count"] == 2
    assert client.get("/api/snippets", params={"q": "reset"}).json()["items"][0]["title"] == "git undo"
    assert client.get("/api/snippets", params={"tag": "py"}).json()["count"] == 1
    assert client.get("/api/snippets", params={"lang": "python"}).json()["count"] == 1
    assert client.get("/api/snippets", params={"favorite": "true"}).json()["count"] == 1


def test_validation_errors():
    assert client.post("/api/snippets", json={"title": "", "content": "x"}).status_code == 400
    assert client.post("/api/snippets", json=[1]).status_code == 400
    assert client.post("/api/snippets", content=b"not json", headers={"content-type": "application/json"}).status_code == 400
    assert client.patch("/api/snippets/999", json={"title": "x"}).status_code == 404


def test_meta_export_import_examples():
    assert client.post("/api/snippets/examples").json()["added"] > 0
    meta = client.get("/api/snippets/meta").json()
    assert meta["stats"]["total"] > 0 and "bash" in meta["languages"] and meta["tags"]

    exp = client.get("/api/snippets/export")
    assert "attachment" in exp.headers["content-disposition"]
    data = exp.json()
    assert client.post("/api/snippets/import", json=data).json() == {"added": 0, "skipped": len(data["snippets"])}
    assert client.post("/api/snippets/import", json={"x": 1}).status_code == 400
