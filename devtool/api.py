"""FastAPI application: JSON API for the tools + the static web UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, tools

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Dev Toolkit", version=__version__, docs_url="/api/docs", redoc_url=None)


@app.exception_handler(tools.ToolError)
async def _tool_error_handler(_: Request, exc: tools.ToolError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": exc.to_dict()})


def _str(body: dict[str, Any], key: str, default: str = "") -> str:
    value = body.get(key, default)
    if value is None:
        return default
    if not isinstance(value, (str, int, float)):
        raise tools.ToolError(f"Поле '{key}' должно быть строкой")
    return str(value)


# Each handler takes the request body (dict) and returns {"result": ...}.
HANDLERS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "json/format": lambda b: tools.json_format(
        _str(b, "text"), indent=b.get("indent", 2), sort_keys=bool(b.get("sort_keys"))
    ),
    "json/minify": lambda b: tools.json_minify(_str(b, "text"), sort_keys=bool(b.get("sort_keys"))),
    "jwt/decode": lambda b: tools.jwt_decode(_str(b, "token")),
    "base64/encode": lambda b: tools.b64_encode(_str(b, "text"), url_safe=bool(b.get("url_safe"))),
    "base64/decode": lambda b: tools.b64_decode(_str(b, "text"), url_safe=bool(b.get("url_safe"))),
    "url/encode": lambda b: tools.url_encode(_str(b, "text")),
    "url/decode": lambda b: tools.url_decode(_str(b, "text")),
    "timestamp": lambda b: tools.timestamp_convert(_str(b, "value"), tz=_str(b, "tz", "UTC")),
    "regex": lambda b: tools.regex_test(_str(b, "pattern"), _str(b, "text"), flags=_str(b, "flags")),
    "hash": lambda b: tools.hash_text(_str(b, "text")),
    "uuid": lambda b: tools.generate_uuids(
        count=b.get("count", 1), uppercase=bool(b.get("uppercase")), hyphens=b.get("hyphens", True)
    ),
    "password": lambda b: tools.generate_password(
        length=b.get("length", 20),
        upper=b.get("upper", True),
        lower=b.get("lower", True),
        digits=b.get("digits", True),
        symbols=b.get("symbols", True),
        exclude_ambiguous=bool(b.get("exclude_ambiguous")),
    ),
}


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.post("/api/tools/{name:path}")
async def run_tool(name: str, request: Request) -> dict[str, Any]:
    handler = HANDLERS.get(name)
    if handler is None:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {name}")
    try:
        body = await request.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        raise tools.ToolError("Тело запроса должно быть JSON-объектом")
    try:
        return {"result": handler(body)}
    except (TypeError, ValueError) as exc:
        if isinstance(exc, tools.ToolError):
            raise
        raise tools.ToolError(f"Некорректные параметры: {exc}") from exc


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
