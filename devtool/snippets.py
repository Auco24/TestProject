"""Snippet storage: CRUD, search, tags, import/export."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable

from .i18n import tr
from .tools import ToolError

LANGUAGES = [
    "text", "bash", "python", "javascript", "typescript", "sql", "json", "yaml",
    "docker", "go", "rust", "java", "csharp", "cpp", "html", "css", "markdown", "powershell",
]

MAX_TITLE = 200
MAX_CONTENT = 200_000
MAX_TAGS = 20


class NotFound(ToolError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_tags(tags: Iterable[str] | str | None) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        tags = re.split(r"[,\s]+", tags)
    out: list[str] = []
    for t in tags:
        t = str(t).strip().lstrip("#").lower()
        t = re.sub(r"[^\w.+-]", "", t)[:40]
        if t and t not in out:
            out.append(t)
    if len(out) > MAX_TAGS:
        raise ToolError(tr("Не больше {n} тегов", n=MAX_TAGS))
    return out


def _validate(data: dict[str, Any], partial: bool = False) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    if "title" in data or not partial:
        title = str(data.get("title") or "").strip()
        if not title:
            raise ToolError(tr("Название не может быть пустым"))
        if len(title) > MAX_TITLE:
            raise ToolError(tr("Название длиннее {n} символов", n=MAX_TITLE))
        clean["title"] = title
    if "content" in data or not partial:
        content = str(data.get("content") or "")
        if not content.strip():
            raise ToolError(tr("Содержимое не может быть пустым"))
        if len(content) > MAX_CONTENT:
            raise ToolError(tr("Сниппет слишком большой"))
        clean["content"] = content.rstrip("\n")
    if "language" in data or not partial:
        lang = str(data.get("language") or "text").strip().lower()
        clean["language"] = lang if lang in LANGUAGES else "text"
    if "description" in data or not partial:
        clean["description"] = str(data.get("description") or "").strip()
    if "favorite" in data or not partial:
        clean["favorite"] = 1 if data.get("favorite") else 0
    if "tags" in data or not partial:
        clean["tags"] = normalize_tags(data.get("tags"))
    return clean


def _row_to_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    tags = [r[0] for r in conn.execute("SELECT tag FROM snippet_tags WHERE snippet_id = ? ORDER BY tag", (row["id"],))]
    d = dict(row)
    d["favorite"] = bool(d["favorite"])
    d["tags"] = tags
    return d


def _set_tags(conn: sqlite3.Connection, snippet_id: int, tags: list[str]) -> None:
    conn.execute("DELETE FROM snippet_tags WHERE snippet_id = ?", (snippet_id,))
    conn.executemany("INSERT INTO snippet_tags (snippet_id, tag) VALUES (?, ?)", [(snippet_id, t) for t in tags])


def get(conn: sqlite3.Connection, snippet_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM snippets WHERE id = ?", (snippet_id,)).fetchone()
    if row is None:
        raise NotFound(tr("Сниппет #{id} не найден", id=snippet_id))
    return _row_to_dict(conn, row)


def create(conn: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    clean = _validate(data)
    now = _now()
    cur = conn.execute(
        "INSERT INTO snippets (title, content, language, description, favorite, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (clean["title"], clean["content"], clean["language"], clean["description"], clean["favorite"], now, now),
    )
    _set_tags(conn, cur.lastrowid, clean["tags"])
    return get(conn, cur.lastrowid)


def update(conn: sqlite3.Connection, snippet_id: int, data: dict[str, Any]) -> dict[str, Any]:
    get(conn, snippet_id)  # raises NotFound
    clean = _validate(data, partial=True)
    tags = clean.pop("tags", None)
    if clean:
        # only the fields that changed content-wise bump updated_at; favorite toggles don't
        if set(clean) - {"favorite"}:
            clean["updated_at"] = _now()
        cols = ", ".join(f"{k} = ?" for k in clean)
        conn.execute(f"UPDATE snippets SET {cols} WHERE id = ?", (*clean.values(), snippet_id))
    if tags is not None:
        _set_tags(conn, snippet_id, tags)
        conn.execute("UPDATE snippets SET updated_at = ? WHERE id = ?", (_now(), snippet_id))
    return get(conn, snippet_id)


def delete(conn: sqlite3.Connection, snippet_id: int) -> None:
    if conn.execute("DELETE FROM snippets WHERE id = ?", (snippet_id,)).rowcount == 0:
        raise NotFound(tr("Сниппет #{id} не найден", id=snippet_id))


def mark_used(conn: sqlite3.Connection, snippet_id: int) -> dict[str, Any]:
    cur = conn.execute(
        "UPDATE snippets SET use_count = use_count + 1, last_used_at = ? WHERE id = ?", (_now(), snippet_id)
    )
    if cur.rowcount == 0:
        raise NotFound(tr("Сниппет #{id} не найден", id=snippet_id))
    return get(conn, snippet_id)


SORTS = {
    "recent": "s.updated_at DESC, s.id DESC",
    "popular": "s.use_count DESC, s.last_used_at DESC, s.id DESC",
    "title": "s.title COLLATE NOCASE ASC",
    "created": "s.created_at DESC, s.id DESC",
}


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def search(
    conn: sqlite3.Connection,
    query: str = "",
    tags: Iterable[str] | None = None,
    language: str | None = None,
    favorite: bool = False,
    sort: str = "recent",
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Every whitespace-separated term must match title, content, description or a tag.

    Terms written as ``#tag`` filter by exact tag, ``lang:python`` by language.
    """
    where: list[str] = []
    params: list[Any] = []
    tag_filter = list(normalize_tags(tags))

    for term in query.split():
        if term.startswith("#") and len(term) > 1:
            tag_filter += normalize_tags([term])
            continue
        if term.lower().startswith("lang:"):
            language = term[5:].lower()
            continue
        like = _like(term)
        where.append(
            "(s.title LIKE ? ESCAPE '\\' OR s.content LIKE ? ESCAPE '\\' OR s.description LIKE ? ESCAPE '\\'"
            " OR EXISTS (SELECT 1 FROM snippet_tags t WHERE t.snippet_id = s.id AND t.tag LIKE ? ESCAPE '\\'))"
        )
        params += [like, like, like, like]

    for tag in dict.fromkeys(tag_filter):
        where.append("EXISTS (SELECT 1 FROM snippet_tags t WHERE t.snippet_id = s.id AND t.tag = ?)")
        params.append(tag)
    if language:
        where.append("s.language = ?")
        params.append(language)
    if favorite:
        where.append("s.favorite = 1")

    sql = "SELECT s.* FROM snippets s"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY s.favorite DESC, {SORTS.get(sort, SORTS['recent'])} LIMIT ?"
    params.append(max(1, min(int(limit), 5000)))
    return [_row_to_dict(conn, r) for r in conn.execute(sql, params)]


def all_tags(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT tag, COUNT(*) AS count FROM snippet_tags GROUP BY tag ORDER BY count DESC, tag")
    return [dict(r) for r in rows]


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    total, favs = conn.execute("SELECT COUNT(*), COALESCE(SUM(favorite), 0) FROM snippets").fetchone()
    langs = conn.execute(
        "SELECT language, COUNT(*) AS count FROM snippets GROUP BY language ORDER BY count DESC"
    ).fetchall()
    return {"total": total, "favorites": favs, "languages": [dict(r) for r in langs]}


EXPORT_FIELDS = ("title", "content", "language", "description", "favorite", "tags", "use_count", "created_at")


def export_all(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute("SELECT * FROM snippets ORDER BY id")
    items = [{k: s[k] for k in EXPORT_FIELDS} for s in (_row_to_dict(conn, r) for r in rows)]
    return {"format": "devtool-snippets", "version": 1, "exported_at": _now(), "snippets": items}


def import_all(conn: sqlite3.Connection, data: Any, skip_duplicates: bool = True) -> dict[str, int]:
    items = data.get("snippets") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ToolError(tr("Ожидается список сниппетов или объект с ключом 'snippets'"))
    existing = {(r[0], r[1]) for r in conn.execute("SELECT title, content FROM snippets")}
    added = skipped = 0
    for item in items:
        if not isinstance(item, dict):
            raise ToolError(tr("Каждый сниппет должен быть объектом"))
        clean = _validate(item)
        if skip_duplicates and (clean["title"], clean["content"]) in existing:
            skipped += 1
            continue
        created = create(conn, item)
        if isinstance(item.get("use_count"), int) and item["use_count"] > 0:
            conn.execute("UPDATE snippets SET use_count = ? WHERE id = ?", (item["use_count"], created["id"]))
        existing.add((clean["title"], clean["content"]))
        added += 1
    return {"added": added, "skipped": skipped}


EXAMPLES: list[dict[str, Any]] = [
    {
        "title": "Отменить последний коммит, сохранив изменения",
        "content": "git reset --soft HEAD~1",
        "language": "bash",
        "tags": ["git"],
        "description": "Коммит исчезает, а изменения остаются в staging.",
    },
    {
        "title": "Удалить локальные ветки, которых нет на remote",
        "content": "git fetch -p && git branch -vv | awk '/: gone]/{print $1}' | xargs -r git branch -D",
        "language": "bash",
        "tags": ["git", "cleanup"],
    },
    {
        "title": "Очистить всё неиспользуемое в Docker",
        "content": "docker system prune -af --volumes",
        "language": "bash",
        "tags": ["docker", "cleanup"],
        "description": "Удаляет остановленные контейнеры, неиспользуемые образы, сети и тома. Осторожно!",
    },
    {
        "title": "Кто занимает порт",
        "content": "lsof -i :8000\n# Windows:\nnetstat -ano | findstr :8000",
        "language": "bash",
        "tags": ["network", "debug"],
    },
    {
        "title": "Самые большие файлы и папки",
        "content": "du -ah . 2>/dev/null | sort -rh | head -20",
        "language": "bash",
        "tags": ["disk", "cleanup"],
    },
    {
        "title": "Простой HTTP-сервер в текущей папке",
        "content": "python -m http.server 8080",
        "language": "bash",
        "tags": ["python", "network"],
        "favorite": True,
    },
    {
        "title": "Retry-декоратор с экспоненциальной задержкой",
        "content": (
            "import functools, time\n\n"
            "def retry(times=3, delay=1.0, exceptions=(Exception,)):\n"
            "    def decorator(fn):\n"
            "        @functools.wraps(fn)\n"
            "        def wrapper(*args, **kwargs):\n"
            "            for attempt in range(times):\n"
            "                try:\n"
            "                    return fn(*args, **kwargs)\n"
            "                except exceptions:\n"
            "                    if attempt == times - 1:\n"
            "                        raise\n"
            "                    time.sleep(delay * 2 ** attempt)\n"
            "        return wrapper\n"
            "    return decorator"
        ),
        "language": "python",
        "tags": ["python", "pattern"],
    },
    {
        "title": "Debounce",
        "content": (
            "function debounce(fn, ms = 300) {\n"
            "  let timer;\n"
            "  return (...args) => {\n"
            "    clearTimeout(timer);\n"
            "    timer = setTimeout(() => fn(...args), ms);\n"
            "  };\n"
            "}"
        ),
        "language": "javascript",
        "tags": ["js", "pattern"],
    },
    {
        "title": "Найти дубликаты в таблице",
        "content": (
            "SELECT email, COUNT(*) AS cnt\n"
            "FROM users\n"
            "GROUP BY email\n"
            "HAVING COUNT(*) > 1\n"
            "ORDER BY cnt DESC;"
        ),
        "language": "sql",
        "tags": ["sql"],
    },
]


def localized_examples() -> list[dict[str, Any]]:
    """Starter snippets with titles and descriptions in the current language."""
    return [{**e, "title": tr(e["title"]), "description": tr(e["description"]) if e.get("description") else ""} for e in EXAMPLES]


def add_examples(conn: sqlite3.Connection) -> dict[str, int]:
    return import_all(conn, localized_examples())
