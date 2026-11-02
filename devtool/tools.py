"""Pure utility functions shared by the web API and the CLI.

Every function either returns a plain JSON-serialisable value or raises
:class:`ToolError` with a human-readable message.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import re
import secrets
import string
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .i18n import WEEKDAYS_FULL, get_lang, relative, tr


class ToolError(ValueError):
    """Raised when user input cannot be processed."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        return {"message": self.message, **self.details}


# --------------------------------------------------------------------------- JSON


def _parse_json(text: str) -> Any:
    if not text.strip():
        raise ToolError(tr("Пустой ввод"))
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ToolError(
            tr("Ошибка JSON: {msg} (строка {line}, столбец {col})", msg=exc.msg, line=exc.lineno, col=exc.colno),
            line=exc.lineno,
            col=exc.colno,
        ) from exc


def json_format(text: str, indent: int = 2, sort_keys: bool = False) -> str:
    data = _parse_json(text)
    indent = max(0, min(int(indent), 8))
    return json.dumps(data, indent=indent or None, sort_keys=sort_keys, ensure_ascii=False)


def json_minify(text: str, sort_keys: bool = False) -> str:
    data = _parse_json(text)
    return json.dumps(data, separators=(",", ":"), sort_keys=sort_keys, ensure_ascii=False)


# ---------------------------------------------------------------------- Base64 / URL


def _pad(data: str) -> str:
    return data + "=" * (-len(data) % 4)


def b64_encode(text: str, url_safe: bool = False) -> str:
    raw = text.encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw) if url_safe else base64.b64encode(raw)
    return encoded.decode("ascii")


def b64_decode(text: str, url_safe: bool = False) -> str:
    cleaned = "".join(text.split())
    try:
        if url_safe:
            raw = base64.urlsafe_b64decode(_pad(cleaned))
        else:
            raw = base64.b64decode(_pad(cleaned), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ToolError(tr("Некорректная строка Base64")) from exc
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ToolError(tr("Декодированные данные не являются текстом UTF-8")) from exc


def url_encode(text: str) -> str:
    return urllib.parse.quote(text, safe="")


def url_decode(text: str) -> str:
    return urllib.parse.unquote(text)


# ------------------------------------------------------------------------------ JWT


def _b64url_json(part: str, name: str) -> Any:
    try:
        raw = base64.urlsafe_b64decode(_pad(part))
        return json.loads(raw)
    except (binascii.Error, ValueError) as exc:
        raise ToolError(tr("Не удалось раскодировать {name} токена", name=name)) from exc


def _ts_info(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, (int, float)):
        return None
    dt = datetime.fromtimestamp(value, tz=timezone.utc)
    return {"unix": value, "iso": dt.isoformat(), "relative": humanize_delta(dt)}


def jwt_decode(token: str) -> dict[str, Any]:
    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    parts = token.split(".")
    if len(parts) != 3:
        raise ToolError(tr("JWT должен состоять из трёх частей, разделённых точками"))
    header = _b64url_json(parts[0], tr("заголовок"))
    payload = _b64url_json(parts[1], "payload")
    if not isinstance(payload, dict):
        payload = {"value": payload}

    now = datetime.now(timezone.utc).timestamp()
    exp = payload.get("exp")
    status = "no-exp"
    if isinstance(exp, (int, float)):
        status = "expired" if exp < now else "valid"
    nbf = payload.get("nbf")
    if isinstance(nbf, (int, float)) and nbf > now:
        status = "not-yet-valid"

    return {
        "header": header,
        "payload": payload,
        "signature": parts[2],
        "parts": parts,
        "status": status,
        "times": {
            key: info
            for key in ("iat", "nbf", "exp")
            if (info := _ts_info(payload.get(key))) is not None
        },
    }


# ------------------------------------------------------------------------ Timestamps


def humanize_delta(dt: datetime, now: datetime | None = None, lang: str | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return relative(int((dt - now).total_seconds()), lang=lang)


def _get_zone(tz: str) -> ZoneInfo | timezone:
    if not tz or tz.upper() == "UTC":
        return timezone.utc
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ToolError(tr("Неизвестный часовой пояс: {tz}", tz=tz)) from exc


def timestamp_convert(value: str | int | float | None = None, tz: str = "UTC") -> dict[str, Any]:
    """Convert a unix timestamp (s/ms/µs) or an ISO-8601 date into many formats."""
    zone = _get_zone(tz)
    text = "" if value is None else str(value).strip()

    if not text or text.lower() == "now":
        dt = datetime.now(timezone.utc)
        source = "now"
    elif re.fullmatch(r"-?\d+(\.\d+)?", text):
        num = float(text)
        digits = len(text.split(".")[0].lstrip("-"))
        if digits >= 16:
            num /= 1_000_000
            source = "unix-us"
        elif digits >= 13:
            num /= 1000
            source = "unix-ms"
        else:
            source = "unix-s"
        try:
            dt = datetime.fromtimestamp(num, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise ToolError(tr("Значение timestamp вне допустимого диапазона")) from exc
    else:
        iso = text.replace(" ", "T", 1)
        if iso.endswith("Z"):
            iso = iso[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(iso)
        except ValueError as exc:
            raise ToolError(
                tr("Не удалось распознать дату. Примеры: 1730505600, 2026-11-02 12:00, 2026-11-02T12:00:00Z")
            ) from exc
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=zone)
        source = "iso"

    local = dt.astimezone(zone)
    utc = dt.astimezone(timezone.utc)
    ts = utc.timestamp()
    return {
        "source": source,
        "unix": int(ts // 1),
        "unix_ms": int(round(ts * 1000)),
        "iso_utc": utc.isoformat().replace("+00:00", "Z"),
        "iso_local": local.isoformat(),
        "human": local.strftime("%d.%m.%Y %H:%M:%S"),
        "rfc2822": utc.strftime("%a, %d %b %Y %H:%M:%S +0000"),
        "timezone": tz or "UTC",
        "weekday": WEEKDAYS_FULL[get_lang()][local.weekday()],
        "relative": humanize_delta(utc),
    }


# ----------------------------------------------------------------------------- Regex

_FLAG_MAP = {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL, "x": re.VERBOSE}
MAX_MATCHES = 1000


def regex_test(pattern: str, text: str, flags: str = "") -> dict[str, Any]:
    if pattern == "":
        raise ToolError(tr("Пустой шаблон"))
    flag_value = 0
    for ch in flags:
        if ch not in _FLAG_MAP:
            raise ToolError(tr("Неизвестный флаг: {flag}", flag=ch))
        flag_value |= _FLAG_MAP[ch]
    try:
        compiled = re.compile(pattern, flag_value)
    except re.error as exc:
        raise ToolError(tr("Ошибка в регулярном выражении: {msg}", msg=exc.msg), pos=exc.pos) from exc

    matches = []
    for m in compiled.finditer(text):
        matches.append(
            {
                "match": m.group(0),
                "start": m.start(),
                "end": m.end(),
                "groups": list(m.groups()),
                "named": m.groupdict(),
            }
        )
        if len(matches) >= MAX_MATCHES:
            break
    names: list[str | None] = [None] * compiled.groups
    for name, index in compiled.groupindex.items():
        names[index - 1] = name
    return {
        "count": len(matches),
        "truncated": len(matches) >= MAX_MATCHES,
        "group_count": compiled.groups,
        "group_names": names,
        "matches": matches,
    }


# ------------------------------------------------------------------------ Generators

HASH_ALGORITHMS = ("md5", "sha1", "sha256", "sha512")


def hash_text(text: str, algorithms: tuple[str, ...] = HASH_ALGORITHMS) -> dict[str, str]:
    result = {}
    for algo in algorithms:
        if algo not in HASH_ALGORITHMS:
            raise ToolError(tr("Неподдерживаемый алгоритм: {algo}", algo=algo))
        result[algo] = hashlib.new(algo, text.encode("utf-8")).hexdigest()
    return result


def generate_uuids(count: int = 1, uppercase: bool = False, hyphens: bool = True) -> list[str]:
    count = max(1, min(int(count), 100))
    out = []
    for _ in range(count):
        u = str(uuid.uuid4()) if hyphens else uuid.uuid4().hex
        out.append(u.upper() if uppercase else u)
    return out


AMBIGUOUS = set("Il1O0o")


def generate_password(
    length: int = 20,
    upper: bool = True,
    lower: bool = True,
    digits: bool = True,
    symbols: bool = True,
    exclude_ambiguous: bool = False,
) -> dict[str, Any]:
    length = int(length)
    if not 4 <= length <= 256:
        raise ToolError(tr("Длина пароля должна быть от 4 до 256"))
    pools = []
    if upper:
        pools.append(string.ascii_uppercase)
    if lower:
        pools.append(string.ascii_lowercase)
    if digits:
        pools.append(string.digits)
    if symbols:
        pools.append("!@#$%^&*()-_=+[]{};:,.?")
    if exclude_ambiguous:
        pools = ["".join(c for c in p if c not in AMBIGUOUS) for p in pools]
    pools = [p for p in pools if p]
    if not pools:
        raise ToolError(tr("Выберите хотя бы один набор символов"))

    alphabet = "".join(pools)
    # guarantee at least one char from each selected pool
    chars = [secrets.choice(p) for p in pools]
    chars += [secrets.choice(alphabet) for _ in range(length - len(chars))]
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]

    entropy = round(length * math.log2(len(alphabet)), 1)
    level = "weak" if entropy < 50 else "medium" if entropy < 80 else "strong" if entropy < 120 else "very_strong"
    label = {"weak": tr("слабый"), "medium": tr("средний"), "strong": tr("сильный"), "very_strong": tr("очень сильный")}[level]
    return {"password": "".join(chars), "entropy": entropy, "strength": label, "level": level}
