"""Command-line interface: `devtool start`, `devtool json`, `devtool jwt`, ..."""

from __future__ import annotations

import json
import os
import sys
import threading
import webbrowser
from datetime import timedelta
from pathlib import Path
from typing import Optional

import typer

from . import __version__, clipboard, db, gitinfo, journal, repos, settings, snippets, tools
from .i18n import tr

app = typer.Typer(
    help=tr("Dev Toolkit — локальный набор утилит для программиста."),
    no_args_is_help=True,
    add_completion=False,
)


def _input(value: Optional[str]) -> str:
    """Use the argument, or read from stdin when it is '-' or missing and piped."""
    if value is not None and value != "-":
        return value
    if value == "-" or not sys.stdin.isatty():
        return sys.stdin.read()
    typer.echo(tr("Нет входных данных: передайте аргумент или используйте pipe."), err=True)
    raise typer.Exit(2)


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except tools.ToolError as exc:
        typer.secho(f"✗ {exc.message}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc


def _dump(data) -> None:
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False))


@app.command(help=tr("Показать версию."))
def version() -> None:
    typer.echo(f"devtool {__version__}")


@app.command(help=tr("Запустить веб-интерфейс."))
def start(
    host: str = typer.Option("127.0.0.1", help=tr("Адрес для запуска сервера.")),
    port: int = typer.Option(8000, "--port", "-p", help=tr("Порт.")),
    no_browser: bool = typer.Option(False, "--no-browser", help=tr("Не открывать браузер.")),
) -> None:
    import uvicorn

    url = f"http://{host}:{port}"
    typer.secho("⚡ " + tr("Dev Toolkit запущен: {url}", url=url), fg=typer.colors.CYAN, bold=True)
    if not no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run("devtool.api:app", host=host, port=port, log_level="warning")


@app.command("json", help=tr("Отформатировать или минифицировать JSON."))
def json_cmd(
    text: Optional[str] = typer.Argument(None, help=tr("JSON-строка или '-' для stdin.")),
    minify: bool = typer.Option(False, "--minify", "-m", help=tr("Минифицировать.")),
    sort_keys: bool = typer.Option(False, "--sort", "-s", help=tr("Сортировать ключи.")),
    indent: int = typer.Option(2, "--indent", "-i", help=tr("Размер отступа.")),
) -> None:
    data = _input(text)
    if minify:
        typer.echo(_run(tools.json_minify, data, sort_keys=sort_keys))
    else:
        typer.echo(_run(tools.json_format, data, indent=indent, sort_keys=sort_keys))


@app.command(help=tr("Раскодировать JWT (без проверки подписи)."))
def jwt(token: Optional[str] = typer.Argument(None, help=tr("JWT-токен."))) -> None:
    result = _run(tools.jwt_decode, _input(token))
    status = {
        "valid": ("✓ " + tr("действителен"), typer.colors.GREEN),
        "expired": ("✗ " + tr("истёк"), typer.colors.RED),
        "not-yet-valid": ("… " + tr("ещё не действует"), typer.colors.YELLOW),
        "no-exp": ("• " + tr("без срока действия"), typer.colors.BLUE),
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
    decode: bool = typer.Option(False, "--decode", "-d", help=tr("Декодировать.")),
    url_safe: bool = typer.Option(False, "--url", "-u", help=tr("URL-safe алфавит.")),
) -> None:
    """Base64 encode / decode."""
    data = _input(text)
    fn = tools.b64_decode if decode else tools.b64_encode
    typer.echo(_run(fn, data.strip() if decode else data, url_safe=url_safe))


@app.command()
def url(
    text: Optional[str] = typer.Argument(None),
    decode: bool = typer.Option(False, "--decode", "-d", help=tr("Декодировать.")),
) -> None:
    """URL encode / decode."""
    data = _input(text)
    typer.echo(tools.url_decode(data) if decode else tools.url_encode(data))


@app.command(help=tr("Конвертировать timestamp ↔ дата."))
def ts(
    value: Optional[str] = typer.Argument(None, help=tr("Unix timestamp или дата. Пусто = сейчас.")),
    tz: str = typer.Option("UTC", "--tz", "-z", help=tr("Часовой пояс, например Europe/Berlin.")),
) -> None:
    r = _run(tools.timestamp_convert, value, tz=tz)
    rows = [
        ("Unix (s)", r["unix"]),
        ("Unix (ms)", r["unix_ms"]),
        ("ISO UTC", r["iso_utc"]),
        (f"ISO {r['timezone']}", r["iso_local"]),
        (tr("Дата"), f"{r['human']}, {r['weekday']}"),
        (tr("Относительно"), r["relative"]),
    ]
    for label, val in rows:
        typer.echo(f"{typer.style(f'{label:>14}', fg=typer.colors.CYAN)}  {val}")


@app.command(help=tr("Проверить регулярное выражение."))
def regex(
    pattern: str = typer.Argument(..., help=tr("Регулярное выражение.")),
    text: Optional[str] = typer.Argument(None, help=tr("Текст или '-' для stdin.")),
    flags: str = typer.Option("", "--flags", "-f", help=tr("Флаги: i, m, s, x.")),
) -> None:
    r = _run(tools.regex_test, pattern, _input(text), flags=flags)
    typer.secho(tr("Совпадений: {n}", n=r["count"]), bold=True)
    for i, m in enumerate(r["matches"], 1):
        line = f"{i:>3}. [{m['start']}:{m['end']}] {m['match']!r}"
        if m["groups"]:
            line += f"  groups={m['groups']}"
        typer.echo(line)


@app.command("hash", help=tr("Посчитать хэши строки."))
def hash_cmd(
    text: Optional[str] = typer.Argument(None),
    algo: Optional[str] = typer.Option(None, "--algo", "-a", help="md5, sha1, sha256, sha512."),
) -> None:
    algos = (algo,) if algo else tools.HASH_ALGORITHMS
    for name, digest in _run(tools.hash_text, _input(text), algos).items():
        typer.echo(digest if algo else f"{typer.style(f'{name:>6}', fg=typer.colors.CYAN)}  {digest}")


@app.command("uuid", help=tr("Сгенерировать UUID v4."))
def uuid_cmd(
    count: int = typer.Option(1, "--count", "-n", help=tr("Количество.")),
    upper: bool = typer.Option(False, "--upper", "-U", help=tr("Верхний регистр.")),
    no_hyphens: bool = typer.Option(False, "--no-hyphens", help=tr("Без дефисов.")),
) -> None:
    for u in tools.generate_uuids(count, uppercase=upper, hyphens=not no_hyphens):
        typer.echo(u)


@app.command("pass", help=tr("Сгенерировать надёжный пароль."))
def password_cmd(
    length: int = typer.Option(20, "--length", "-l", help=tr("Длина.")),
    no_symbols: bool = typer.Option(False, "--no-symbols", help=tr("Без спецсимволов.")),
    no_ambiguous: bool = typer.Option(False, "--no-ambiguous", help=tr("Без похожих символов (l, 1, O, 0).")),
) -> None:
    r = _run(tools.generate_password, length, symbols=not no_symbols, exclude_ambiguous=no_ambiguous)
    typer.echo(r["password"])
    typer.secho(tr("энтропия {bits} бит — {strength}", bits=r["entropy"], strength=r["strength"]), fg=typer.colors.BRIGHT_BLACK, err=True)


# ---------------------------------------------------------------- Snippets

snip_app = typer.Typer(help=tr("Сниппеты: сохраняйте и находите команды и куски кода."), no_args_is_help=True)
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


@snip_app.command("add", help=tr("Добавить сниппет."))
def snip_add(
    content: Optional[str] = typer.Argument(None, help=tr("Текст сниппета или '-' для stdin. Пусто — откроется $EDITOR.")),
    title: Optional[str] = typer.Option(None, "--title", "-t", help=tr("Название.")),
    tag: list[str] = typer.Option([], "--tag", "-g", help=tr("Тег (можно несколько раз или через запятую).")),
    lang: str = typer.Option("bash", "--lang", "-l", help=tr("Язык: ") + ", ".join(snippets.LANGUAGES)),
    desc: str = typer.Option("", "--desc", "-d", help=tr("Описание.")),
    fav: bool = typer.Option(False, "--fav", "-f", help=tr("Добавить в избранное.")),
) -> None:
    if content is None and sys.stdin.isatty():
        content = typer.edit("") or ""
    else:
        content = _input(content)
    if not title:
        first = content.strip().splitlines()[0] if content.strip() else ""
        title = typer.prompt(tr("Название"), default=first[:60] or None) if sys.stdin.isatty() else first[:60]
    s = _db_call(
        snippets.create,
        {"title": title, "content": content, "language": lang, "tags": ",".join(tag), "description": desc, "favorite": fav},
    )
    typer.secho("✓ " + tr("Сохранено как #{id}", id=s["id"]), fg=typer.colors.GREEN)


@snip_app.command("find", help=tr("Найти сниппеты (без аргументов — показать все)."))
@snip_app.command("ls", hidden=True, help=tr("Найти сниппеты (без аргументов — показать все)."))
def snip_find(
    query: list[str] = typer.Argument(None, help=tr("Слова для поиска. #tag — фильтр по тегу, lang:python — по языку.")),
    fav: bool = typer.Option(False, "--fav", "-f", help=tr("Только избранное.")),
    sort: str = typer.Option("recent", "--sort", "-s", help="recent | popular | title | created"),
    limit: int = typer.Option(30, "--limit", "-n"),
) -> None:
    items = _db_call(snippets.search, " ".join(query or []), favorite=fav, sort=sort, limit=limit)
    if not items:
        typer.secho(tr("Ничего не найдено."), fg=typer.colors.YELLOW)
        raise typer.Exit(0)
    for s in items:
        typer.echo(_snip_line(s))


@snip_app.command("show", help=tr("Показать сниппет."))
def snip_show(
    snippet_id: int = typer.Argument(...),
    raw: bool = typer.Option(False, "--raw", "-r", help=tr("Только содержимое, без оформления.")),
) -> None:
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
    typer.secho(tr("использован {n} раз · изменён {updated}", n=s["use_count"], updated=s["updated_at"]), fg="bright_black")


@snip_app.command("copy", help=tr("Скопировать сниппет в буфер обмена."))
@snip_app.command("cp", hidden=True, help=tr("Скопировать сниппет в буфер обмена."))
def snip_copy(snippet_id: int = typer.Argument(...)) -> None:
    s = _db_call(snippets.mark_used, snippet_id)
    if clipboard.copy(s["content"]):
        typer.secho("✓ " + tr("«{title}» скопирован в буфер обмена", title=s["title"]), fg=typer.colors.GREEN)
    else:
        typer.secho(tr("Буфер обмена недоступен, вывожу в консоль:"), fg=typer.colors.YELLOW, err=True)
        typer.echo(s["content"])


@snip_app.command("edit", help=tr("Отредактировать содержимое в $EDITOR."))
def snip_edit(snippet_id: int = typer.Argument(...)) -> None:
    s = _db_call(snippets.get, snippet_id)
    new = typer.edit(s["content"])
    if new is None or new.rstrip("\n") == s["content"]:
        typer.echo(tr("Без изменений."))
        return
    _db_call(snippets.update, snippet_id, {"content": new})
    typer.secho("✓ " + tr("#{id} обновлён", id=snippet_id), fg=typer.colors.GREEN)


@snip_app.command("fav", help=tr("Добавить в избранное / убрать из избранного."))
def snip_fav(snippet_id: int = typer.Argument(...)) -> None:
    s = _db_call(snippets.get, snippet_id)
    s = _db_call(snippets.update, snippet_id, {"favorite": not s["favorite"]})
    typer.echo(("★ " + tr("В избранном: ") if s["favorite"] else "☆ " + tr("Убран из избранного: ")) + s["title"])


@snip_app.command("rm", help=tr("Удалить сниппет."))
def snip_rm(
    snippet_id: int = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y", help=tr("Не спрашивать подтверждение.")),
) -> None:
    s = _db_call(snippets.get, snippet_id)
    if not yes and not typer.confirm(tr("Удалить «{title}»?", title=s["title"])):
        raise typer.Abort()
    _db_call(snippets.delete, snippet_id)
    typer.secho("✓ " + tr("#{id} удалён", id=snippet_id), fg=typer.colors.GREEN)


@snip_app.command("tags", help=tr("Показать все теги."))
def snip_tags() -> None:
    for t in _db_call(snippets.all_tags):
        typer.echo(f"{typer.style('#' + t['tag'], fg='cyan')} {typer.style(str(t['count']), fg='bright_black')}")


@snip_app.command("export", help=tr("Экспортировать все сниппеты в JSON."))
def snip_export(
    file: Optional[str] = typer.Argument(None, help=tr("Файл. Без аргумента — в stdout.")),
) -> None:
    data = json.dumps(_db_call(snippets.export_all), indent=2, ensure_ascii=False)
    if file:
        with open(file, "w", encoding="utf-8") as fh:
            fh.write(data)
        typer.secho("✓ " + tr("Сохранено в {file}", file=file), fg=typer.colors.GREEN)
    else:
        typer.echo(data)


@snip_app.command("import", help=tr("Импортировать сниппеты из JSON (дубликаты пропускаются)."))
def snip_import(file: str = typer.Argument(..., help=tr("JSON-файл или '-' для stdin."))) -> None:
    raw = sys.stdin.read() if file == "-" else open(file, encoding="utf-8").read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        typer.secho("✗ " + tr("Некорректный JSON: {error}", error=exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    r = _db_call(snippets.import_all, data)
    typer.secho("✓ " + tr("Добавлено: {added}, пропущено дубликатов: {skipped}", added=r["added"], skipped=r["skipped"]), fg=typer.colors.GREEN)


@snip_app.command("path", help=tr("Показать путь к базе данных."))
def snip_path() -> None:
    typer.echo(db.db_path())


# ----------------------------------------------------------------- Journal

KIND_STYLE = {
    "done": ("✓", typer.colors.GREEN),
    "plan": ("○", typer.colors.BLUE),
    "blocker": ("!", typer.colors.RED),
    "note": ("•", typer.colors.BRIGHT_BLACK),
}


def _entry_line(e: dict) -> str:
    icon, color = KIND_STYLE[e["kind"]]
    if e["kind"] == "plan" and e["completed"]:
        icon, color = "✓", typer.colors.GREEN
    t = e["created_at"][11:16]
    meta = ""
    if e["project"]:
        meta = f"{e['project']}" + (f"@{e['branch']}" if e["branch"] else "")
        meta = " " + typer.style(meta, fg=typer.colors.CYAN)
    sid = typer.style(f"#{e['id']}", fg=typer.colors.BRIGHT_BLACK)
    text = typer.style(e["text"], dim=True) if e["completed"] and e["kind"] == "plan" else e["text"]
    return f"  {typer.style(icon, fg=color, bold=True)} {typer.style(t, fg=typer.colors.BRIGHT_BLACK)} {text}{meta} {sid}"


@app.command("log", help=tr("Быстрая запись в дневник: devtool log починил баг с логином."))
def log_cmd(
    text: list[str] = typer.Argument(..., help=tr("Что сделано. Можно без кавычек.")),
    plan: bool = typer.Option(False, "--plan", "-p", help=tr("Это план на сегодня.")),
    blocker: bool = typer.Option(False, "--blocker", "-b", help=tr("Это блокер / проблема.")),
    note: bool = typer.Option(False, "--note", "-n", help=tr("Просто заметка.")),
    yesterday: bool = typer.Option(False, "--yesterday", "-y", help=tr("Записать на вчера.")),
) -> None:
    kind = "plan" if plan else "blocker" if blocker else "note" if note else "done"
    day = journal.today() - timedelta(days=1) if yesterday else None
    e = _db_call(journal.add, " ".join(text), kind, cwd=os.getcwd(), day=day)
    where = f" → {e['project']}" + (f"@{e['branch']}" if e["branch"] else "") if e["project"] else ""
    typer.secho("✓ " + tr("{kind} записано (#{id})", kind=journal.kind_labels()[kind], id=e["id"]) + where, fg=typer.colors.GREEN)


@app.command("standup", help=tr("Отчёт к стендапу: вчера / сегодня / блокеры (+ ваши коммиты)."))
def standup_cmd(
    fmt: str = typer.Option("text", "--format", "-f", help="text | md | slack"),
    copy: bool = typer.Option(False, "--copy", "-c", help=tr("Скопировать в буфер обмена.")),
    date_: Optional[str] = typer.Option(None, "--date", "-d", help=tr("Дата стендапа (YYYY-MM-DD), по умолчанию сегодня.")),
) -> None:
    r = _db_call(journal.standup, for_day=date_, fmt=fmt)
    typer.echo(r["text"], nl=False)
    if copy:
        if clipboard.copy(r["text"]):
            typer.secho("✓ " + tr("Скопировано в буфер обмена"), fg=typer.colors.GREEN, err=True)
        else:
            typer.secho(tr("Буфер обмена недоступен"), fg=typer.colors.YELLOW, err=True)


journal_app = typer.Typer(help=tr("Дневник разработчика."), no_args_is_help=True)
app.add_typer(journal_app, name="journal")


@journal_app.command("show", help=tr("Показать записи за последние дни."))
def journal_show(
    days: int = typer.Option(7, "--days", "-d", help=tr("За сколько дней.")),
    project: Optional[str] = typer.Option(None, "--project", "-p", help=tr("Фильтр по проекту.")),
    commits: bool = typer.Option(True, "--commits/--no-commits", help=tr("Показывать коммиты.")),
) -> None:
    r = _db_call(journal.timeline, days=days, project=project, with_commits=commits)
    shown = False
    for d in r["days"]:
        if not d["entries"] and not d["commits"]:
            continue
        shown = True
        typer.secho(f"\n{d['label']}  {typer.style(d['date'], fg=typer.colors.BRIGHT_BLACK)}", bold=True)
        for e in d["entries"]:
            typer.echo(_entry_line(e))
        for c in d["commits"]:
            typer.echo(f"  {typer.style('⎇', fg=typer.colors.MAGENTA)} {c['time'][11:16]} "
                       f"{typer.style(c['subject'], fg=typer.colors.BRIGHT_BLACK)} {typer.style(c['project'], fg=typer.colors.CYAN)}")
    if not shown:
        typer.secho(tr("Записей пока нет. Начните с: devtool log \"что сделали\""), fg=typer.colors.YELLOW)


@journal_app.command("done", help=tr("Отметить план или блокер выполненным / решённым."))
def journal_done(entry_id: int = typer.Argument(...)) -> None:
    e = _db_call(journal.update, entry_id, {"completed": True})
    typer.secho("✓ " + tr("Готово: {text}", text=e["text"]), fg=typer.colors.GREEN)


@journal_app.command("rm", help=tr("Удалить запись."))
def journal_rm(entry_id: int = typer.Argument(...)) -> None:
    _db_call(journal.delete, entry_id)
    typer.secho("✓ " + tr("#{id} удалена", id=entry_id), fg=typer.colors.GREEN)


@journal_app.command("roots", help=tr("Папки, в которых искать git-репозитории для коммитов в отчёте."))
def journal_roots(
    add: list[str] = typer.Option([], "--add", "-a", help=tr("Добавить папку с проектами.")),
    remove: list[str] = typer.Option([], "--remove", "-r", help=tr("Убрать папку.")),
) -> None:
    with db.session() as conn:
        roots = settings.get(conn, "git_roots")
        for a in add:
            p = Path(a).expanduser().resolve()
            if not p.is_dir():
                typer.secho("✗ " + tr("Папка не найдена: {path}", path=a), fg=typer.colors.RED, err=True)
                raise typer.Exit(1)
            if str(p) not in roots:
                roots.append(str(p))
        for r in remove:
            rp = str(Path(r).expanduser().resolve())
            roots = [x for x in roots if x != rp and x != r]
        settings.set(conn, "git_roots", roots)
    if not roots:
        typer.echo(tr("Папки не заданы. Пример: devtool journal roots --add ~/projects"))
        return
    for r in roots:
        typer.echo(typer.style(r, bold=True))
        for repo in gitinfo.find_repos([r]):
            typer.echo("  " + typer.style("⎇ ", fg=typer.colors.MAGENTA) + repo)


# --------------------------------------------------------------- Git dashboard

repos_app = typer.Typer(help=tr("Git-дашборд: состояние всех репозиториев."), invoke_without_command=True)
app.add_typer(repos_app, name="repos")

HEALTH_STYLE = {
    "conflict": ("✗", "конфликт", typer.colors.RED),
    "dirty": ("●", "изменения", typer.colors.YELLOW),
    "unpushed": ("↑", "не отправлено", typer.colors.MAGENTA),
    "behind": ("↓", "отстаёт", typer.colors.BLUE),
    "local": ("○", "без remote", typer.colors.BRIGHT_BLACK),
    "clean": ("✓", "чисто", typer.colors.GREEN),
    "error": ("?", "ошибка", typer.colors.RED),
}


def _health_label(health: str) -> tuple[str, str]:
    icon, label, color = HEALTH_STYLE[health]
    translated = {
        "конфликт": tr("конфликт"), "изменения": tr("изменения"), "не отправлено": tr("не отправлено"),
        "отстаёт": tr("отстаёт"), "без remote": tr("без remote"), "чисто": tr("чисто"), "ошибка": tr("ошибка"),
    }[label]
    return f"{icon} {translated}", color


def _known_repos() -> list[str]:
    with db.session() as conn:
        return journal.known_repos(conn)


def _resolve_repo(name_or_path: str) -> str:
    known = _known_repos()
    p = str(Path(name_or_path).expanduser().resolve())
    if p in known:
        return p
    matches = [k for k in known if Path(k).name == name_or_path]
    if len(matches) == 1:
        return matches[0]
    typer.secho("✗ " + tr("Репозиторий не найден: {name}", name=name_or_path) + (" " + tr("(неоднозначно)") if matches else ""), fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


@repos_app.callback(help=tr("Показать состояние всех репозиториев (devtool repos)."))
def repos_status(
    ctx: typer.Context,
    attention: bool = typer.Option(False, "--attention", "-a", help=tr("Только требующие внимания.")),
) -> None:
    if ctx.invoked_subcommand:
        return
    paths = _known_repos()
    if not paths:
        typer.secho(tr("Репозитории не найдены. Добавьте папку: devtool journal roots --add ~/projects"), fg=typer.colors.YELLOW)
        raise typer.Exit(0)
    data = repos.all_status(paths)
    width = max(len(r["name"]) for r in data["repos"])
    for r in data["repos"]:
        if attention and r["health"] in ("clean", "local"):
            continue
        label, color = _health_label(r["health"])
        branch = r.get("branch") or "(detached)"
        sync = ""
        if r.get("ahead"):
            sync += typer.style(f" ↑{r['ahead']}", fg=typer.colors.MAGENTA)
        if r.get("behind"):
            sync += typer.style(f" ↓{r['behind']}", fg=typer.colors.BLUE)
        changes = ""
        if r.get("changes"):
            bits = [f"✗{r['conflicts']}" if r["conflicts"] else "", f"+{r['staged']}" if r["staged"] else "", f"~{r['modified']}" if r["modified"] else "",
                    f"?{r['untracked']}" if r["untracked"] else ""]
            changes = " " + typer.style(" ".join(b for b in bits if b), fg=typer.colors.YELLOW)
        extra = []
        if r.get("stash"):
            extra.append(f"stash {r['stash']}")
        if r.get("merged_branches"):
            extra.append(tr("слитых веток {n}", n=r["merged_branches"]))
        typer.echo(
            f"{typer.style(r['name'].ljust(width), bold=True)}  {typer.style(label.ljust(15), fg=color)}"
            f" {typer.style(branch, fg=typer.colors.CYAN)}{sync}{changes}"
            + (typer.style("  · " + ", ".join(extra), fg=typer.colors.BRIGHT_BLACK) if extra else "")
        )
    sm = data["summary"]
    typer.secho(
        "\n" + tr("{total} репоз. · изменений {dirty} · не отправлено {unpushed} · отстают {behind}", **{k: sm[k] for k in ("total", "dirty", "unpushed", "behind")}),
        fg=typer.colors.BRIGHT_BLACK,
    )


@repos_app.command("fetch", help=tr("git fetch --all --prune во всех репозиториях."))
def repos_fetch() -> None:
    paths = _known_repos()
    with typer.progressbar(length=1, label="fetch " + tr("{n} репоз.", n=len(paths))) as bar:
        r = repos.fetch_many(paths)
        bar.update(1)
    for item in r["results"]:
        if not item["ok"]:
            typer.secho(f"✗ {item['path']}: {item['error']}", fg=typer.colors.RED)
    typer.secho("✓ " + tr("Успешно: {ok}, с ошибками: {failed}", ok=r["ok"], failed=r["failed"]), fg=typer.colors.GREEN if not r["failed"] else typer.colors.YELLOW)


@repos_app.command("branches", help=tr("Ветки репозитория: слитые, устаревшие, отслеживание."))
def repos_branches(repo: str = typer.Argument(..., help=tr("Имя или путь репозитория."))) -> None:
    path = _resolve_repo(repo)
    for b in repos.branches(path):
        marks = []
        if b["current"]:
            marks.append(typer.style(tr("текущая"), fg=typer.colors.GREEN))
        if b["default"]:
            marks.append(typer.style(tr("основная"), fg=typer.colors.CYAN))
        if b["merged"]:
            marks.append(typer.style(tr("слита"), fg=typer.colors.MAGENTA))
        if b["stale"]:
            marks.append(typer.style(tr("{n} дн. без коммитов", n=b["age_days"]), fg=typer.colors.YELLOW))
        if b["gone"]:
            marks.append(typer.style(tr("upstream удалён"), fg=typer.colors.RED))
        prefix = "*" if b["current"] else " "
        typer.echo(f"{prefix} {typer.style(b['name'], bold=True)}  " + "  ".join(marks))


@repos_app.command("prune", help=tr("Удалить локальные ветки, уже слитые в основную (git branch -d)."))
def repos_prune(
    repo: str = typer.Argument(..., help=tr("Имя или путь репозитория.")),
    yes: bool = typer.Option(False, "--yes", "-y", help=tr("Не спрашивать подтверждение.")),
) -> None:
    path = _resolve_repo(repo)
    names = [b["name"] for b in repos.branches(path) if b["merged"] and not b["current"] and not b["default"]]
    if not names:
        typer.echo(tr("Слитых веток нет."))
        return
    typer.echo(tr("Будут удалены: ") + ", ".join(names))
    if not yes and not typer.confirm(tr("Удалить?")):
        raise typer.Abort()
    r = repos.delete_branches(path, names)
    for e in r["errors"]:
        typer.secho(f"✗ {e['name']}: {e['error']}", fg=typer.colors.RED)
    typer.secho("✓ " + tr("Удалено веток: {n}", n=len(r["deleted"])), fg=typer.colors.GREEN)


if __name__ == "__main__":  # pragma: no cover
    app()
