"""Developer journal: quick entries, timeline, stand-up report, activity stats."""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import gitinfo, settings
from .i18n import SINCE_WEEKDAY, day_label, get_lang, plural, tr
from .tools import ToolError

KINDS = ("done", "plan", "blocker", "note")
KIND_LABELS = {"done": "Сделал", "plan": "План", "blocker": "Блокер", "note": "Заметка"}


def kind_labels() -> dict[str, str]:
    return {"done": tr("Сделал"), "plan": tr("План"), "blocker": tr("Блокер"), "note": tr("Заметка")}

MAX_TEXT = 2000
OPEN_ITEMS_WINDOW = 14  # days an unfinished plan / blocker keeps showing up in the stand-up



class NotFound(ToolError):
    pass


def today() -> date:
    return datetime.now().astimezone().date()


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _parse_day(value: Any, name: str = "date") -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ToolError(tr("Некорректная дата в поле '{name}': {value}", name=name, value=value)) from exc


def human_day(d: date, ref: date | None = None) -> str:
    ref = ref or today()
    if d == ref:
        return tr("Сегодня")
    if d == ref - timedelta(days=1):
        return tr("Вчера")
    return day_label(d.weekday(), d.day, d.month, d.year if d.year != ref.year else None)


def previous_workday(d: date) -> date:
    """Monday → Friday, weekend → Friday, otherwise the day before."""
    wd = d.weekday()
    if wd == 0:
        return d - timedelta(days=3)
    if wd == 6:
        return d - timedelta(days=2)
    if wd == 5:
        return d - timedelta(days=1)
    return d - timedelta(days=1)


# ------------------------------------------------------------------------- CRUD


def _row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["completed"] = d["completed_at"] is not None
    d["tags"] = re.findall(r"(?<!\w)#([\w.+-]+)", d["text"])
    return d


def get(conn: sqlite3.Connection, entry_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM journal WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise NotFound(tr("Запись #{id} не найдена", id=entry_id))
    return _row(row)


def _clean_text(text: Any) -> str:
    text = str(text or "").strip()
    if not text:
        raise ToolError(tr("Текст записи не может быть пустым"))
    if len(text) > MAX_TEXT:
        raise ToolError(tr("Запись длиннее {n} символов", n=MAX_TEXT))
    return text


def _clean_kind(kind: Any) -> str:
    kind = str(kind or "done").lower()
    if kind not in KINDS:
        raise ToolError(tr("Неизвестный тип записи: {kind}. Допустимо: {allowed}", kind=kind, allowed=", ".join(KINDS)))
    return kind


def add(
    conn: sqlite3.Connection,
    text: str,
    kind: str = "done",
    *,
    cwd: str | None = None,
    repo_path: str | None = None,
    project: str | None = None,
    day: Any = None,
) -> dict[str, Any]:
    """Add an entry. Project/branch are detected from *cwd* or *repo_path* when possible."""
    text = _clean_text(text)
    kind = _clean_kind(kind)
    branch = None
    info = None
    if repo_path:
        info = gitinfo.repo_info(repo_path)
    elif cwd:
        info = gitinfo.repo_info(cwd)
    if info:
        repo_path, project, branch = info.path, info.name, info.branch
    elif repo_path:
        project = project or Path(repo_path).name
    project = (str(project).strip() or None) if project else None
    d = _parse_day(day) if day else today()
    cur = conn.execute(
        "INSERT INTO journal (text, kind, day, created_at, project, repo_path, branch) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (text, kind, d.isoformat(), _now_iso(), project, repo_path, branch),
    )
    return get(conn, cur.lastrowid)


def update(conn: sqlite3.Connection, entry_id: int, data: dict[str, Any]) -> dict[str, Any]:
    get(conn, entry_id)
    fields: dict[str, Any] = {}
    if "text" in data:
        fields["text"] = _clean_text(data["text"])
    if "kind" in data:
        fields["kind"] = _clean_kind(data["kind"])
    if "day" in data:
        fields["day"] = _parse_day(data["day"], "day").isoformat()
    if "project" in data:
        fields["project"] = (str(data["project"]).strip() or None) if data["project"] else None
    if "completed" in data:
        fields["completed_at"] = _now_iso() if data["completed"] else None
    if fields:
        cols = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE journal SET {cols} WHERE id = ?", (*fields.values(), entry_id))
    return get(conn, entry_id)


def delete(conn: sqlite3.Connection, entry_id: int) -> None:
    if conn.execute("DELETE FROM journal WHERE id = ?", (entry_id,)).rowcount == 0:
        raise NotFound(tr("Запись #{id} не найдена", id=entry_id))


# ---------------------------------------------------------------------- Projects


def known_repos(conn: sqlite3.Connection) -> list[str]:
    """Repositories from the journal plus everything found under the configured git roots."""
    paths = [r[0] for r in conn.execute("SELECT DISTINCT repo_path FROM journal WHERE repo_path IS NOT NULL")]
    paths += gitinfo.find_repos(settings.get(conn, "git_roots"))
    seen: dict[str, None] = {}
    for p in paths:
        if p and Path(p).is_dir():
            seen.setdefault(p, None)
    return list(seen)


def projects(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for p in known_repos(conn):
        out[p] = {"name": Path(p).name, "path": p}
    for (name,) in conn.execute("SELECT DISTINCT project FROM journal WHERE project IS NOT NULL AND repo_path IS NULL"):
        out.setdefault("name:" + name, {"name": name, "path": None})
    return sorted(out.values(), key=lambda x: x["name"].lower())


# ---------------------------------------------------------------------- Timeline


def _entries_between(conn, start: date, end: date, project: str | None = None, q: str | None = None) -> list[dict]:
    sql = "SELECT * FROM journal WHERE day BETWEEN ? AND ?"
    params: list[Any] = [start.isoformat(), end.isoformat()]
    if project:
        sql += " AND project = ?"
        params.append(project)
    if q:
        sql += " AND text LIKE ? ESCAPE '\\'"
        params.append("%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    sql += " ORDER BY day DESC, created_at DESC, id DESC"
    return [_row(r) for r in conn.execute(sql, params)]


def timeline(
    conn: sqlite3.Connection,
    days: int = 14,
    before: Any = None,
    project: str | None = None,
    q: str | None = None,
    with_commits: bool = True,
) -> dict[str, Any]:
    days = max(1, min(int(days), 365))
    end = _parse_day(before, "before") - timedelta(days=1) if before else today()
    start = end - timedelta(days=days - 1)

    entries = _entries_between(conn, start, end, project, q)
    commits: list[dict] = []
    if with_commits and not q:
        repos = known_repos(conn)
        if project:
            repos = [r for r in repos if Path(r).name == project]
        commits = [c.to_dict() for c in gitinfo.commits_for_repos(repos, start, end)]

    by_day: dict[str, dict[str, list]] = defaultdict(lambda: {"entries": [], "commits": []})
    for e in entries:
        by_day[e["day"]]["entries"].append(e)
    for c in commits:
        by_day[c["day"]]["commits"].append(c)
    if not before and not q and not project:
        by_day[today().isoformat()]  # always show today

    result = [
        {"date": d, "label": human_day(date.fromisoformat(d)), **by_day[d]}
        for d in sorted(by_day, reverse=True)
    ]
    older = conn.execute("SELECT 1 FROM journal WHERE day < ? LIMIT 1", (start.isoformat(),)).fetchone()
    return {"days": result, "next_before": start.isoformat(), "has_more": older is not None}


# ---------------------------------------------------------------------- Stand-up


def standup(conn: sqlite3.Connection, for_day: Any = None, fmt: str = "md", with_commits: bool = True) -> dict[str, Any]:
    day = _parse_day(for_day) if for_day else today()
    prev = previous_workday(day)
    window_start = day - timedelta(days=OPEN_ITEMS_WINDOW)

    rows = [_row(r) for r in conn.execute(
        "SELECT * FROM journal WHERE day BETWEEN ? AND ? ORDER BY day, created_at, id",
        (window_start.isoformat(), day.isoformat()),
    )]
    prev_s, day_s = prev.isoformat(), day.isoformat()

    def completed_in_range(e: dict) -> bool:
        return bool(e["completed_at"]) and prev_s <= e["completed_at"][:10] < day_s

    done = [e for e in rows if (e["kind"] == "done" and prev_s <= e["day"] < day_s) or (e["kind"] == "plan" and completed_in_range(e))]
    plans = [e for e in rows if e["kind"] == "plan" and not e["completed"]]
    done_today = [
        e for e in rows
        if (e["kind"] == "done" and e["day"] == day_s)
        or (e["kind"] == "plan" and e["completed_at"] and e["completed_at"][:10] == day_s)
    ]
    blockers = [e for e in rows if e["kind"] == "blocker" and not e["completed"]]

    commits: list[dict] = []
    if with_commits:
        known = {e["text"].strip().lower() for e in done}
        for c in gitinfo.commits_for_repos(known_repos(conn), prev, day - timedelta(days=1)):
            if c.subject.strip().lower() not in known:
                commits.append(c.to_dict())
        commits.reverse()  # chronological

    data = {
        "date": day_s,
        "since": prev_s,
        "since_label": tr("Вчера") if prev == day - timedelta(days=1) else SINCE_WEEKDAY[get_lang()][prev.weekday()],
        "done": done,
        "commits": commits,
        "plans": plans,
        "done_today": done_today,
        "blockers": blockers,
    }
    data["text"] = render_standup(data, fmt)
    data["format"] = fmt
    return data


def _project_suffix(e: dict) -> str:
    return f" ({e['project']})" if e.get("project") else ""


def render_standup(data: dict[str, Any], fmt: str = "md") -> str:
    if fmt not in ("md", "slack", "text"):
        raise ToolError(tr("Формат отчёта: md, slack или text"))
    bold = {"md": "**{}**", "slack": "*{}*", "text": "{}"}[fmt]
    bullet = {"md": "- ", "slack": "• ", "text": "  - "}[fmt]

    lines: list[str] = []

    def section(title: str, items: list[str], empty: str) -> None:
        lines.append(bold.format(title + ":") if fmt != "text" else title.upper() + ":")
        lines.extend(bullet + i for i in (items or [empty]))
        lines.append("")

    prev_items = [e["text"] + _project_suffix(e) for e in data["done"]]
    by_project: dict[str, list[str]] = defaultdict(list)
    for c in data["commits"]:
        by_project[c["project"]].append(c["subject"])
    for proj, subjects in by_project.items():
        if len(subjects) == 1:
            prev_items.append(f"{subjects[0]} ({proj})")
        else:
            code = "`" if fmt != "text" else ""
            n = len(subjects)
            word = plural(n, "коммит", "коммита", "коммитов")
            shown = "; ".join(f"{code}{s}{code}" for s in subjects[:5]) + ("…" if n > 5 else "")
            prev_items.append(f"{proj}: {n} {word} — {shown}")
    section(data["since_label"], prev_items, "—")

    today_items = [e["text"] + _project_suffix(e) for e in data["plans"]]
    today_items += [e["text"] + _project_suffix(e) + " ✓" for e in data["done_today"]]
    section(tr("Сегодня"), today_items, "—")

    section(tr("Блокеры"), [e["text"] + _project_suffix(e) for e in data["blockers"]], tr("нет"))
    return "\n".join(lines).rstrip() + "\n"


# ----------------------------------------------------------------------- Stats


def stats(conn: sqlite3.Connection, weeks: int = 18, with_commits: bool = True) -> dict[str, Any]:
    end = today()
    start = end - timedelta(days=end.weekday()) - timedelta(weeks=weeks - 1)  # Monday, `weeks` weeks ago
    counts: dict[str, int] = defaultdict(int)
    for d, n in conn.execute(
        "SELECT day, COUNT(*) FROM journal WHERE day BETWEEN ? AND ? GROUP BY day", (start.isoformat(), end.isoformat())
    ):
        counts[d] += n
    commit_total = 0
    if with_commits:
        for c in gitinfo.commits_for_repos(known_repos(conn), start, end):
            counts[c.when.date().isoformat()] += 1
            commit_total += 1

    # streak: consecutive days with activity ending today (or yesterday if today is still empty)
    streak = 0
    d = end if counts.get(end.isoformat()) else end - timedelta(days=1)
    while counts.get(d.isoformat()):
        streak += 1
        d -= timedelta(days=1)

    week_start = end - timedelta(days=end.weekday())
    total = conn.execute("SELECT COUNT(*) FROM journal").fetchone()[0]
    week_entries = conn.execute("SELECT COUNT(*) FROM journal WHERE day >= ?", (week_start.isoformat(),)).fetchone()[0]
    open_plans = conn.execute("SELECT COUNT(*) FROM journal WHERE kind = 'plan' AND completed_at IS NULL AND day >= ?",
                              ((end - timedelta(days=OPEN_ITEMS_WINDOW)).isoformat(),)).fetchone()[0]
    return {
        "total": total,
        "week": week_entries,
        "streak": streak,
        "open_plans": open_plans,
        "commits": commit_total,
        "heatmap": {"start": start.isoformat(), "end": end.isoformat(), "counts": dict(counts)},
    }
