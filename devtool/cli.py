"""Command-line interface: `devtool start`, `devtool json`, `devtool jwt`, ..."""

from __future__ import annotations

import json
import sys
import threading
import webbrowser
from typing import Optional

import typer

from . import __version__, clipboard, db, snippets, tools

app = typer.Typer(
    help="Dev Toolkit — локальный набор утилит для программиста.",
    no_args_is_help=True,
    add_completion=False,
)


def _input(value: Optional[str]) -> str:
    """Use the argument, or read from stdin when it is '-' or missing and piped."""
    if value is not None and value != "-":
        return value
    if value == "-" or not sys.stdin.isatty():
        return sys.stdin.read()
    typer.echo("Нет входных данных: передайте аргумент или используйте pipe.", err=True)
    raise typer.Exit(2)


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except tools.ToolError as exc:
        typer.secho(f"✗ {exc.message}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc


def _dump(data) -> None:
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False))


@app.command()
def version() -> None:
    """Показать версию."""
    typer.echo(f"devtool {__version__}")


@app.command()
def start(
    host: str = typer.Option("127.0.0.1", help="Адрес для запуска сервера."),
    port: int = typer.Option(8000, "--port", "-p", help="Порт."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Не открывать браузер."),
) -> None:
    """Запустить веб-интерфейс."""
    import uvicorn

    url = f"http://{host}:{port}"
    typer.secho(f"⚡ Dev Toolkit запущен: {url}", fg=typer.colors.CYAN, bold=True)
    if not no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run("devtool.api:app", host=host, port=port, log_level="warning")


@app.command("json")
def json_cmd(
    text: Optional[str] = typer.Argument(None, help="JSON-строка или '-' для stdin."),
    minify: bool = typer.Option(False, "--minify", "-m", help="Минифицировать."),
    sort_keys: bool = typer.Option(False, "--sort", "-s", help="Сортировать ключи."),
    indent: int = typer.Option(2, "--indent", "-i", help="Размер отступа."),
) -> None:
    """Отформатировать или минифицировать JSON."""
    data = _input(text)
    if minify:
        typer.echo(_run(tools.json_minify, data, sort_keys=sort_keys))
    else:
        typer.echo(_run(tools.json_format, data, indent=indent, sort_keys=sort_keys))


@app.command()
def jwt(token: Optional[str] = typer.Argument(None, help="JWT-токен.")) -> None:
    """Раскодировать JWT (без проверки подписи)."""
    result = _run(tools.jwt_decode, _input(token))
    status = {
        "valid": ("✓ действителен", typer.colors.GREEN),
        "expired": ("✗ истёк", typer.colors.RED),
        "not-yet-valid": ("… ещё не действует", typer.colors.YELLOW),
        "no-exp": ("• без срока действия", typer.colors.BLUE),
    }[result["status"]]
    typer.secho("Header:", bold=True)
    _dump(result["header"])
    typer.secho("Payload:", bold=True)
    _dump(result["payload"])
    for key, info in result["times"].items():
        typer.echo(f"{key}: {info['iso']} ({info['relative']})")
    typer.secho(status[0], fg=status[1], bold=True)


@app.command()
def b64(
    text: Optional[str] = typer.Argument(None),
    decode: bool = typer.Option(False, "--decode", "-d", help="Декодировать."),
    url_safe: bool = typer.Option(False, "--url", "-u", help="URL-safe алфавит."),
) -> None:
    """Base64 encode / decode."""
    data = _input(text)
    fn = tools.b64_decode if decode else tools.b64_encode
    typer.echo(_run(fn, data.strip() if decode else data, url_safe=url_safe))


@app.command()
def url(
    text: Optional[str] = typer.Argument(None),
    decode: bool = typer.Option(False, "--decode", "-d", help="Декодировать."),
) -> None:
    """URL encode / decode."""
    data = _input(text)
    typer.echo(tools.url_decode(data) if decode else tools.url_encode(data))


@app.command()
def ts(
    value: Optional[str] = typer.Argument(None, help="Unix timestamp или дата. Пусто = сейчас."),
    tz: str = typer.Option("UTC", "--tz", "-z", help="Часовой пояс, например Europe/Berlin."),
) -> None:
    """Конвертировать timestamp ↔ дата."""
    r = _run(tools.timestamp_convert, value, tz=tz)
    rows = [
        ("Unix (s)", r["unix"]),
        ("Unix (ms)", r["unix_ms"]),
        ("ISO UTC", r["iso_utc"]),
        (f"ISO {r['timezone']}", r["iso_local"]),
        ("Дата", f"{r['human']}, {r['weekday']}"),
        ("Относительно", r["relative"]),
    ]
    for label, val in rows:
        typer.echo(f"{typer.style(f'{label:>14}', fg=typer.colors.CYAN)}  {val}")


@app.command()
def regex(
    pattern: str = typer.Argument(..., help="Регулярное выражение."),
    text: Optional[str] = typer.Argument(None, help="Текст или '-' для stdin."),
    flags: str = typer.Option("", "--flags", "-f", help="Флаги: i, m, s, x."),
) -> None:
    """Проверить регулярное выражение."""
    r = _run(tools.regex_test, pattern, _input(text), flags=flags)
    typer.secho(f"Совпадений: {r['count']}", bold=True)
    for i, m in enumerate(r["matches"], 1):
        line = f"{i:>3}. [{m['start']}:{m['end']}] {m['match']!r}"
        if m["groups"]:
            line += f"  groups={m['groups']}"
        typer.echo(line)


@app.command("hash")
def hash_cmd(
    text: Optional[str] = typer.Argument(None),
    algo: Optional[str] = typer.Option(None, "--algo", "-a", help="md5, sha1, sha256, sha512."),
) -> None:
    """Посчитать хэши строки."""
    algos = (algo,) if algo else tools.HASH_ALGORITHMS
    for name, digest in _run(tools.hash_text, _input(text), algos).items():
        typer.echo(digest if algo else f"{typer.style(f'{name:>6}', fg=typer.colors.CYAN)}  {digest}")


@app.command("uuid")
def uuid_cmd(
    count: int = typer.Option(1, "--count", "-n", help="Количество."),
    upper: bool = typer.Option(False, "--upper", "-U", help="Верхний регистр."),
    no_hyphens: bool = typer.Option(False, "--no-hyphens", help="Без дефисов."),
) -> None:
    """Сгенерировать UUID v4."""
    for u in tools.generate_uuids(count, uppercase=upper, hyphens=not no_hyphens):
        typer.echo(u)


@app.command("pass")
def password_cmd(
    length: int = typer.Option(20, "--length", "-l", help="Длина."),
    no_symbols: bool = typer.Option(False, "--no-symbols", help="Без спецсимволов."),
    no_ambiguous: bool = typer.Option(False, "--no-ambiguous", help="Без похожих символов (l, 1, O, 0)."),
) -> None:
    """Сгенерировать надёжный пароль."""
    r = _run(tools.generate_password, length, symbols=not no_symbols, exclude_ambiguous=no_ambiguous)
    typer.echo(r["password"])
    typer.secho(f"энтропия {r['entropy']} бит — {r['strength']}", fg=typer.colors.BRIGHT_BLACK, err=True)


# ---------------------------------------------------------------- Snippets

snip_app = typer.Typer(help="Сниппеты: сохраняйте и находите команды и куски кода.", no_args_is_help=True)
app.add_typer(snip_app, name="snip")

LANG_COLORS = {"bash": "green", "python": "yellow", "javascript": "bright_yellow", "sql": "cyan", "docker": "blue"}


def _snip_line(s: dict) -> str:
    star = typer.style("★ ", fg="yellow") if s["favorite"] else "  "
    sid = typer.style(f"#{s['id']:<4}", fg="bright_black")
    lang = typer.style(f"[{s['language']}]", fg=LANG_COLORS.get(s["language"], "magenta"))
    tags = typer.style(" ".join("#" + t for t in s["tags"]), fg="cyan")
    first = s["content"].splitlines()[0] if s["content"] else ""
    if len(first) > 70:
        first = first[:67] + "..."
    preview = typer.style(f"\n        {first}", fg="bright_black")
    return f"{star}{sid} {typer.style(s['title'], bold=True)} {lang} {tags}{preview}"


def _db_call(fn, *args, **kwargs):
    with db.session() as conn:
        return _run(fn, conn, *args, **kwargs)


@snip_app.command("add")
def snip_add(
    content: Optional[str] = typer.Argument(None, help="Текст сниппета или '-' для stdin. Пусто — откроется $EDITOR."),
    title: Optional[str] = typer.Option(None, "--title", "-t", help="Название."),
    tag: list[str] = typer.Option([], "--tag", "-g", help="Тег (можно несколько раз или через запятую)."),
    lang: str = typer.Option("bash", "--lang", "-l", help="Язык: " + ", ".join(snippets.LANGUAGES)),
    desc: str = typer.Option("", "--desc", "-d", help="Описание."),
    fav: bool = typer.Option(False, "--fav", "-f", help="Добавить в избранное."),
) -> None:
    """Добавить сниппет."""
    if content is None and sys.stdin.isatty():
        content = typer.edit("") or ""
    else:
        content = _input(content)
    if not title:
        first = content.strip().splitlines()[0] if content.strip() else ""
        title = typer.prompt("Название", default=first[:60] or None) if sys.stdin.isatty() else first[:60]
    s = _db_call(
        snippets.create,
        {"title": title, "content": content, "language": lang, "tags": ",".join(tag), "description": desc, "favorite": fav},
    )
    typer.secho(f"✓ Сохранено как #{s['id']}", fg=typer.colors.GREEN)


@snip_app.command("find")
@snip_app.command("ls", hidden=True)
def snip_find(
    query: list[str] = typer.Argument(None, help="Слова для поиска. #tag — фильтр по тегу, lang:python — по языку."),
    fav: bool = typer.Option(False, "--fav", "-f", help="Только избранное."),
    sort: str = typer.Option("recent", "--sort", "-s", help="recent | popular | title | created"),
    limit: int = typer.Option(30, "--limit", "-n"),
) -> None:
    """Найти сниппеты (без аргументов — показать все)."""
    items = _db_call(snippets.search, " ".join(query or []), favorite=fav, sort=sort, limit=limit)
    if not items:
        typer.secho("Ничего не найдено.", fg=typer.colors.YELLOW)
        raise typer.Exit(0)
    for s in items:
        typer.echo(_snip_line(s))


@snip_app.command("show")
def snip_show(
    snippet_id: int = typer.Argument(...),
    raw: bool = typer.Option(False, "--raw", "-r", help="Только содержимое, без оформления."),
) -> None:
    """Показать сниппет."""
    s = _db_call(snippets.get, snippet_id)
    if raw:
        typer.echo(s["content"])
        return
    typer.echo(_snip_line(s).split("\n")[0])
    if s["description"]:
        typer.secho(s["description"], fg="bright_black")
    typer.echo(typer.style("─" * 60, fg="bright_black"))
    typer.echo(s["content"])
    typer.echo(typer.style("─" * 60, fg="bright_black"))
    typer.secho(f"использован {s['use_count']} раз · изменён {s['updated_at']}", fg="bright_black")


@snip_app.command("copy")
@snip_app.command("cp", hidden=True)
def snip_copy(snippet_id: int = typer.Argument(...)) -> None:
    """Скопировать сниппет в буфер обмена."""
    s = _db_call(snippets.mark_used, snippet_id)
    if clipboard.copy(s["content"]):
        typer.secho(f"✓ «{s['title']}» скопирован в буфер обмена", fg=typer.colors.GREEN)
    else:
        typer.secho("Буфер обмена недоступен, вывожу в консоль:", fg=typer.colors.YELLOW, err=True)
        typer.echo(s["content"])


@snip_app.command("edit")
def snip_edit(snippet_id: int = typer.Argument(...)) -> None:
    """Отредактировать содержимое в $EDITOR."""
    s = _db_call(snippets.get, snippet_id)
    new = typer.edit(s["content"])
    if new is None or new.rstrip("\n") == s["content"]:
        typer.echo("Без изменений.")
        return
    _db_call(snippets.update, snippet_id, {"content": new})
    typer.secho(f"✓ #{snippet_id} обновлён", fg=typer.colors.GREEN)


@snip_app.command("fav")
def snip_fav(snippet_id: int = typer.Argument(...)) -> None:
    """Добавить в избранное / убрать из избранного."""
    s = _db_call(snippets.get, snippet_id)
    s = _db_call(snippets.update, snippet_id, {"favorite": not s["favorite"]})
    typer.echo(("★ В избранном: " if s["favorite"] else "☆ Убран из избранного: ") + s["title"])


@snip_app.command("rm")
def snip_rm(
    snippet_id: int = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y", help="Не спрашивать подтверждение."),
) -> None:
    """Удалить сниппет."""
    s = _db_call(snippets.get, snippet_id)
    if not yes and not typer.confirm(f"Удалить «{s['title']}»?"):
        raise typer.Abort()
    _db_call(snippets.delete, snippet_id)
    typer.secho(f"✓ #{snippet_id} удалён", fg=typer.colors.GREEN)


@snip_app.command("tags")
def snip_tags() -> None:
    """Показать все теги."""
    for t in _db_call(snippets.all_tags):
        typer.echo(f"{typer.style('#' + t['tag'], fg='cyan')} {typer.style(str(t['count']), fg='bright_black')}")


@snip_app.command("export")
def snip_export(
    file: Optional[str] = typer.Argument(None, help="Файл. Без аргумента — в stdout."),
) -> None:
    """Экспортировать все сниппеты в JSON."""
    data = json.dumps(_db_call(snippets.export_all), indent=2, ensure_ascii=False)
    if file:
        with open(file, "w", encoding="utf-8") as fh:
            fh.write(data)
        typer.secho(f"✓ Сохранено в {file}", fg=typer.colors.GREEN)
    else:
        typer.echo(data)


@snip_app.command("import")
def snip_import(file: str = typer.Argument(..., help="JSON-файл или '-' для stdin.")) -> None:
    """Импортировать сниппеты из JSON (дубликаты пропускаются)."""
    raw = sys.stdin.read() if file == "-" else open(file, encoding="utf-8").read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        typer.secho(f"✗ Некорректный JSON: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    r = _db_call(snippets.import_all, data)
    typer.secho(f"✓ Добавлено: {r['added']}, пропущено дубликатов: {r['skipped']}", fg=typer.colors.GREEN)


@snip_app.command("path")
def snip_path() -> None:
    """Показать путь к базе данных."""
    typer.echo(db.db_path())


if __name__ == "__main__":  # pragma: no cover
    app()
