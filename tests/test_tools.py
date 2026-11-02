import base64
import json
from datetime import datetime, timedelta, timezone

import pytest

from devtool import tools
from devtool.tools import ToolError


def make_jwt(payload, header=None):
    enc = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b"=").decode()
    return f"{enc(header or {'alg': 'HS256', 'typ': 'JWT'})}.{enc(payload)}.sig"


# JSON
def test_json_format_and_minify():
    assert tools.json_format('{"b":1,"a":[1,2]}', indent=2, sort_keys=True) == '{\n  "a": [\n    1,\n    2\n  ],\n  "b": 1\n}'
    assert tools.json_minify('{ "a" : [1, 2] }') == '{"a":[1,2]}'
    assert tools.json_format('{"name":"Иван"}') == '{\n  "name": "Иван"\n}'


def test_json_error_has_position():
    with pytest.raises(ToolError) as exc:
        tools.json_format('{\n  "a": 1\n  "b": 2\n}')
    assert exc.value.details["line"] == 3


def test_json_empty():
    with pytest.raises(ToolError):
        tools.json_format("   ")


# Base64 / URL
@pytest.mark.parametrize("url_safe", [False, True])
def test_b64_roundtrip(url_safe):
    text = "Привет, мир! ??>>"
    assert tools.b64_decode(tools.b64_encode(text, url_safe), url_safe) == text


def test_b64_decode_without_padding():
    assert tools.b64_decode("aGVsbG8") == "hello"


def test_b64_invalid():
    with pytest.raises(ToolError):
        tools.b64_decode("@@@not base64@@@")


def test_url_roundtrip():
    assert tools.url_encode("a b&c=д") == "a%20b%26c%3D%D0%B4"
    assert tools.url_decode("a%20b%26c%3D%D0%B4") == "a b&c=д"


# JWT
def test_jwt_valid_and_times():
    now = int(datetime.now(timezone.utc).timestamp())
    r = tools.jwt_decode("Bearer " + make_jwt({"sub": "1", "iat": now, "exp": now + 3600}))
    assert r["header"]["alg"] == "HS256"
    assert r["payload"]["sub"] == "1"
    assert r["status"] == "valid"
    assert set(r["times"]) == {"iat", "exp"}


def test_jwt_expired_and_no_exp():
    assert tools.jwt_decode(make_jwt({"exp": 1}))["status"] == "expired"
    assert tools.jwt_decode(make_jwt({"sub": "x"}))["status"] == "no-exp"


def test_jwt_invalid():
    with pytest.raises(ToolError):
        tools.jwt_decode("not.a.jwt!!")
    with pytest.raises(ToolError):
        tools.jwt_decode("onlyonepart")


# Timestamps
def test_timestamp_seconds_and_ms():
    r = tools.timestamp_convert("1730505600")
    assert r["iso_utc"] == "2024-11-02T00:00:00Z"
    assert r["source"] == "unix-s"
    r_ms = tools.timestamp_convert("1730505600000")
    assert r_ms["unix"] == 1730505600 and r_ms["source"] == "unix-ms"


def test_timestamp_iso_with_tz():
    r = tools.timestamp_convert("2024-11-02 01:00", tz="Europe/Berlin")
    assert r["unix"] == 1730505600
    assert r["iso_local"].endswith("+01:00")


def test_timestamp_now_and_errors():
    assert tools.timestamp_convert("")["source"] == "now"
    with pytest.raises(ToolError):
        tools.timestamp_convert("вчера")
    with pytest.raises(ToolError):
        tools.timestamp_convert("0", tz="Mars/Olympus")


def test_humanize():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert tools.humanize_delta(now - timedelta(minutes=1), now) == "1 минуту назад"
    assert tools.humanize_delta(now - timedelta(hours=3), now) == "3 часа назад"
    assert tools.humanize_delta(now + timedelta(days=5), now) == "через 5 дней"
    assert tools.humanize_delta(now, now) == "только что"


# Regex
def test_regex_groups_and_flags():
    r = tools.regex_test(r"(?P<user>\w+)@(\w+)", "A@b c@d", flags="i")
    assert r["count"] == 2
    assert r["group_names"] == ["user", None]
    assert r["matches"][1] == {"match": "c@d", "start": 4, "end": 7, "groups": ["c", "d"], "named": {"user": "c"}}


def test_regex_errors():
    with pytest.raises(ToolError):
        tools.regex_test("(", "x")
    with pytest.raises(ToolError):
        tools.regex_test("a", "a", flags="q")


# Generators
def test_hash():
    assert tools.hash_text("abc")["sha256"] == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert tools.hash_text("abc", ("md5",)) == {"md5": "900150983cd24fb0d6963f7d28e17f72"}


def test_uuids():
    out = tools.generate_uuids(3, uppercase=True, hyphens=False)
    assert len(out) == 3 and all(len(u) == 32 and u.isupper() for u in out)
    assert len(tools.generate_uuids(1000)) == 100


def test_password():
    r = tools.generate_password(32, symbols=False, exclude_ambiguous=True)
    pw = r["password"]
    assert len(pw) == 32
    assert any(c.isupper() for c in pw) and any(c.islower() for c in pw) and any(c.isdigit() for c in pw)
    assert not set(pw) & tools.AMBIGUOUS and pw.isalnum()
    assert r["strength"] in ("сильный", "очень сильный")
    with pytest.raises(ToolError):
        tools.generate_password(10, upper=False, lower=False, digits=False, symbols=False)
    with pytest.raises(ToolError):
        tools.generate_password(2)
