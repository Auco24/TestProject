from fastapi.testclient import TestClient

from devtool.api import app

client = TestClient(app)


def test_index_and_static():
    assert "Dev Toolkit" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_health():
    assert client.get("/api/health").json()["status"] == "ok"


def test_tool_ok():
    r = client.post("/api/tools/json/minify", json={"text": '{ "a": 1 }'})
    assert r.status_code == 200 and r.json() == {"result": '{"a":1}'}


def test_tool_error_is_400():
    r = client.post("/api/tools/json/format", json={"text": "{bad"})
    assert r.status_code == 400
    assert "line" in r.json()["error"]


def test_bad_params_are_400():
    assert client.post("/api/tools/password", json={"length": "abc"}).status_code == 400
    assert client.post("/api/tools/json/format", json={"text": {"x": 1}}).status_code == 400
    assert client.post("/api/tools/json/format", json=[1, 2]).status_code == 400


def test_unknown_tool():
    assert client.post("/api/tools/nope", json={}).status_code == 404


def test_all_tools_respond():
    payloads = {
        "jwt/decode": {"token": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.x"},
        "base64/encode": {"text": "hi"},
        "base64/decode": {"text": "aGk="},
        "url/encode": {"text": "a b"},
        "url/decode": {"text": "a%20b"},
        "timestamp": {"value": "0", "tz": "UTC"},
        "regex": {"pattern": "a", "text": "aa"},
        "hash": {"text": "x"},
        "uuid": {"count": 2},
        "password": {"length": 16},
    }
    for name, body in payloads.items():
        r = client.post(f"/api/tools/{name}", json=body)
        assert r.status_code == 200, (name, r.text)
