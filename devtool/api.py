"""FastAPI application: JSON API for the tools + the static web UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, db, gitinfo, journal, repos, settings, snippets, tools
from .i18n import reset_request_lang, set_request_lang, tr

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Dev Toolkit", version=__version__, docs_url="/api/docs", redoc_url=None)


@app.middleware("http")
async def _language(request: Request, call_next):
    """The web UI sends the chosen language in X-Lang; errors and reports follow it."""
    token = set_request_lang(request.headers.get("x-lang") or request.query_params.get("lang"))
    try:
        return await call_next(request)
    finally:
        reset_request_lang(token)


@app.exception_handler(snippets.NotFound)
@app.exception_handler(journal.NotFound)
async def _not_found_handler(_: Request, exc: tools.ToolError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": exc.to_dict()})


@app.exception_handler(tools.ToolError)
async def _tool_error_handler(_: Request, exc: tools.ToolError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": exc.to_dict()})


def _str(body: dict[str, Any], key: str, default: str = "") -> str:
    value = body.get(key, default)
    if value is None:
        return default
    if not isinstance(value, (str, int, float)):
        raise tools.ToolError(tr("Поле '{key}' должно быть строкой", key=key))
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
    return {"status": "ok", "app": "devtool", "version": __version__}


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
        raise tools.ToolError(tr("Тело запроса должно быть JSON-объектом"))
    try:
        return {"result": handler(body)}
    except (TypeError, ValueError) as exc:
        if isinstance(exc, tools.ToolError):
            raise
        raise tools.ToolError(tr("Некорректные параметры: {error}", error=exc)) from exc


# ------------------------------------------------------------------ Snippets


def get_db():
    with db.session() as conn:
        yield conn


async def _json_body(request: Request) -> Any:
    try:
        return await request.json()
    except ValueError as exc:
        raise tools.ToolError(tr("Тело запроса должно быть корректным JSON")) from exc


async def _object_body(request: Request) -> dict[str, Any]:
    body = await _json_body(request)
    if not isinstance(body, dict):
        raise tools.ToolError(tr("Тело запроса должно быть JSON-объектом"))
    return body


@app.get("/api/snippets")
def list_snippets(
    q: str = "",
    tag: list[str] = Query(default=[]),
    lang: str | None = None,
    favorite: bool = False,
    sort: str = "recent",
    conn=Depends(get_db),
) -> dict[str, Any]:
    items = snippets.search(conn, q, tags=tag, language=lang or None, favorite=favorite, sort=sort)
    return {"items": items, "count": len(items)}


@app.get("/api/snippets/meta")
def snippets_meta(conn=Depends(get_db)) -> dict[str, Any]:
    return {"tags": snippets.all_tags(conn), "languages": snippets.LANGUAGES, "stats": snippets.stats(conn)}


@app.get("/api/snippets/export")
def export_snippets(conn=Depends(get_db)) -> JSONResponse:
    return JSONResponse(
        snippets.export_all(conn),
        headers={"Content-Disposition": 'attachment; filename="devtool-snippets.json"'},
    )


@app.post("/api/snippets/import")
async def import_snippets(request: Request, conn=Depends(get_db)) -> dict[str, int]:
    return snippets.import_all(conn, await _json_body(request))


@app.post("/api/snippets/examples")
def add_examples(conn=Depends(get_db)) -> dict[str, int]:
    return snippets.add_examples(conn)


@app.post("/api/snippets", status_code=201)
async def create_snippet(request: Request, conn=Depends(get_db)) -> dict[str, Any]:
    return snippets.create(conn, await _object_body(request))


@app.get("/api/snippets/{snippet_id}")
def get_snippet(snippet_id: int, conn=Depends(get_db)) -> dict[str, Any]:
    return snippets.get(conn, snippet_id)


@app.patch("/api/snippets/{snippet_id}")
async def update_snippet(snippet_id: int, request: Request, conn=Depends(get_db)) -> dict[str, Any]:
    return snippets.update(conn, snippet_id, await _object_body(request))


@app.delete("/api/snippets/{snippet_id}", status_code=204)
def delete_snippet(snippet_id: int, conn=Depends(get_db)) -> Response:
    snippets.delete(conn, snippet_id)
    return Response(status_code=204)


@app.post("/api/snippets/{snippet_id}/use")
def use_snippet(snippet_id: int, conn=Depends(get_db)) -> dict[str, Any]:
    return snippets.mark_used(conn, snippet_id)


# ------------------------------------------------------------------- Journal


@app.get("/api/journal")
def journal_timeline(
    days: int = 14,
    before: str | None = None,
    project: str | None = None,
    q: str | None = None,
    commits: bool = True,
    conn=Depends(get_db),
) -> dict[str, Any]:
    return journal.timeline(conn, days=days, before=before, project=project or None, q=q or None, with_commits=commits)


@app.get("/api/journal/meta")
def journal_meta(conn=Depends(get_db)) -> dict[str, Any]:
    return {
        "projects": journal.projects(conn),
        "stats": journal.stats(conn),
        "kinds": journal.kind_labels(),
        "git": gitinfo.git_available(),
        "git_roots": settings.get(conn, "git_roots"),
    }


@app.get("/api/journal/standup")
def journal_standup(date: str | None = None, format: str = "md", conn=Depends(get_db)) -> dict[str, Any]:
    return journal.standup(conn, for_day=date, fmt=format)


@app.post("/api/journal", status_code=201)
async def journal_add(request: Request, conn=Depends(get_db)) -> dict[str, Any]:
    b = await _object_body(request)
    return journal.add(
        conn, b.get("text", ""), b.get("kind", "done"),
        repo_path=b.get("repo_path") or None, project=b.get("project") or None, day=b.get("day") or None,
    )


@app.patch("/api/journal/{entry_id}")
async def journal_update(entry_id: int, request: Request, conn=Depends(get_db)) -> dict[str, Any]:
    return journal.update(conn, entry_id, await _object_body(request))


@app.delete("/api/journal/{entry_id}", status_code=204)
def journal_delete(entry_id: int, conn=Depends(get_db)) -> Response:
    journal.delete(conn, entry_id)
    return Response(status_code=204)


@app.put("/api/settings/git_roots")
async def set_git_roots(request: Request, conn=Depends(get_db)) -> dict[str, Any]:
    body = await _json_body(request)
    roots = body.get("roots") if isinstance(body, dict) else body
    if not isinstance(roots, list) or not all(isinstance(r, str) for r in roots):
        raise tools.ToolError(tr("Ожидается список путей"))
    clean: list[str] = []
    for r in roots:
        p = Path(r.strip()).expanduser()
        if not r.strip():
            continue
        if not p.is_dir():
            raise tools.ToolError(tr("Папка не найдена: {path}", path=r))
        if str(p.resolve()) not in clean:
            clean.append(str(p.resolve()))
    settings.set(conn, "git_roots", clean)
    return {"roots": clean, "repos": gitinfo.find_repos(clean)}


# ---------------------------------------------------------------- Git dashboard


def _known_repo(conn, path: Any) -> str:
    """Only repositories the dashboard already knows about may be acted upon."""
    if not isinstance(path, str) or not path:
        raise tools.ToolError(tr("Не указан путь к репозиторию"))
    resolved = str(Path(path).expanduser().resolve())
    if resolved not in journal.known_repos(conn):
        raise tools.ToolError(tr("Репозиторий не найден среди папок с проектами"))
    return resolved


@app.get("/api/git/repos")
def git_repos(conn=Depends(get_db)) -> dict[str, Any]:
    data = repos.all_status(journal.known_repos(conn))
    data["roots"] = settings.get(conn, "git_roots")
    data["git"] = gitinfo.git_available()
    return data


@app.get("/api/git/repo")
def git_repo(path: str, conn=Depends(get_db)) -> dict[str, Any]:
    return repos.repo_status(_known_repo(conn, path), detailed=True)


@app.post("/api/git/fetch")
async def git_fetch(request: Request, conn=Depends(get_db)) -> dict[str, Any]:
    body = await _object_body(request)
    if body.get("path"):
        return repos.fetch(_known_repo(conn, body["path"]))
    return repos.fetch_many(journal.known_repos(conn))


@app.post("/api/git/pull")
async def git_pull(request: Request, conn=Depends(get_db)) -> dict[str, Any]:
    body = await _object_body(request)
    return repos.pull_ff(_known_repo(conn, body.get("path")))


@app.post("/api/git/delete-branches")
async def git_delete_branches(request: Request, conn=Depends(get_db)) -> dict[str, Any]:
    body = await _object_body(request)
    names = body.get("branches")
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names) or not names:
        raise tools.ToolError(tr("Ожидается непустой список веток"))
    return repos.delete_branches(_known_repo(conn, body.get("path")), names)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
