"""Git dashboard: status of many repositories at once, branches, safe maintenance actions."""

from __future__ import annotations

import os
import re
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .gitinfo import _git
from .tools import ToolError

STALE_DAYS = 30
ACTIVITY_DAYS = 14
MAX_FILES = 200


# ----------------------------------------------------------------------- helpers


def web_url(remote: str | None) -> str | None:
    """Turn a git remote into a browsable https URL (credentials stripped)."""
    if not remote:
        return None
    r = remote.strip()
    m = re.match(r"^(?:ssh://)?[\w.-]+@([\w.-]+)[:/](?:\d+/)?(.+?)(?:\.git)?/?$", r)
    if m and not r.startswith(("http://", "https://")):
        return f"https://{m.group(1)}/{m.group(2)}"
    m = re.match(r"^https?://(?:[^@/]+@)?([^/]+)/(.+?)(?:\.git)?/?$", r)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}"
    return None


def safe_remote(remote: str | None) -> str | None:
    """Hide credentials embedded in https remotes (https://user:token@host/...)."""
    if not remote:
        return None
    return re.sub(r"^(https?://)[^@/]+@", r"\1", remote.strip())


def _parse_status(out: str) -> dict[str, Any]:
    info: dict[str, Any] = {
        "branch": None, "detached": False, "upstream": None, "ahead": 0, "behind": 0, "initial": False,
        "staged": 0, "modified": 0, "untracked": 0, "conflicts": 0, "files": [],
    }
    for line in out.splitlines():
        if line.startswith("# branch.head "):
            head = line[14:]
            info["detached"] = head == "(detached)"
            info["branch"] = None if info["detached"] else head
        elif line.startswith("# branch.oid "):
            info["initial"] = line[13:] == "(initial)"
        elif line.startswith("# branch.upstream "):
            info["upstream"] = line[18:]
        elif line.startswith("# branch.ab "):
            m = re.match(r"# branch\.ab \+(\d+) -(\d+)", line)
            if m:
                info["ahead"], info["behind"] = int(m.group(1)), int(m.group(2))
        elif line[:2] in ("1 ", "2 "):
            parts = line.split(" ", 8)
            xy = parts[1]
            path = parts[8].split("\t")[0] if len(parts) > 8 else ""
            if xy[0] != ".":
                info["staged"] += 1
            if xy[1] != ".":
                info["modified"] += 1
            if len(info["files"]) < MAX_FILES:
                info["files"].append({"path": path, "x": xy[0], "y": xy[1], "renamed": line[0] == "2"})
        elif line.startswith("u "):
            info["conflicts"] += 1
            path = line.split(" ", 10)[-1]
            if len(info["files"]) < MAX_FILES:
                info["files"].append({"path": path, "x": "U", "y": "U", "renamed": False})
        elif line.startswith("? "):
            info["untracked"] += 1
            if len(info["files"]) < MAX_FILES:
                info["files"].append({"path": line[2:], "x": "?", "y": "?", "renamed": False})
    return info


def default_branch(path: str) -> str | None:
    ref = _git(path, "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD")
    if ref and "/" in ref:
        return ref.split("/", 1)[1]
    for name in ("main", "master", "develop", "trunk"):
        if _git(path, "rev-parse", "--verify", "-q", f"refs/heads/{name}") is not None:
            return name
    return _git(path, "symbolic-ref", "--short", "-q", "HEAD")


def _age_days(iso: str | None, now: datetime) -> int | None:
    if not iso:
        return None
    try:
        return max(0, (now - datetime.fromisoformat(iso)).days)
    except ValueError:
        return None


def branches(path: str, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    out = _git(
        path, "for-each-ref", "--sort=-committerdate",
        "--format=%(refname:short)%1f%(committerdate:iso-strict)%1f%(upstream:short)%1f%(upstream:track)%1f%(subject)%1f%(HEAD)",
        "refs/heads",
    )
    if not out:
        return []
    base = default_branch(path)
    merged = set()
    if base:
        m = _git(path, "branch", "--merged", base, "--format=%(refname:short)")
        merged = set((m or "").splitlines())
    result = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 6:
            continue
        name, iso, upstream, track, subject, head = parts
        ahead = behind = 0
        if m := re.search(r"ahead (\d+)", track):
            ahead = int(m.group(1))
        if m := re.search(r"behind (\d+)", track):
            behind = int(m.group(1))
        age = _age_days(iso, now)
        is_current = head == "*"
        result.append({
            "name": name,
            "current": is_current,
            "default": name == base,
            "last_commit": iso,
            "age_days": age,
            "subject": subject,
            "upstream": upstream or None,
            "gone": "gone" in track,
            "ahead": ahead,
            "behind": behind,
            "merged": name in merged and name != base,
            "stale": age is not None and age > STALE_DAYS and name != base,
        })
    return result


def activity(path: str, days: int = ACTIVITY_DAYS, today: date | None = None) -> list[int]:
    today = today or datetime.now().astimezone().date()
    start = today - timedelta(days=days - 1)
    out = _git(path, "log", "--all", f"--since={start.isoformat()} 00:00", "--format=%ad", "--date=short")
    counts = Counter((out or "").splitlines())
    return [counts.get((start + timedelta(days=i)).isoformat(), 0) for i in range(days)]


def _last_fetch(path: str) -> str | None:
    git_dir = _git(path, "rev-parse", "--absolute-git-dir")
    if not git_dir:
        return None
    fh = Path(git_dir) / "FETCH_HEAD"
    if not fh.exists():
        return None
    return datetime.fromtimestamp(fh.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")


def _health(s: dict[str, Any]) -> str:
    if s["conflicts"]:
        return "conflict"
    if s["staged"] or s["modified"] or s["untracked"]:
        return "dirty"
    if s["ahead"]:
        return "unpushed"
    if s["behind"]:
        return "behind"
    if not s["remote"]:
        return "local"
    return "clean"


# ------------------------------------------------------------------------ status


def repo_status(path: str, detailed: bool = False) -> dict[str, Any]:
    """Summary (and optionally full details) for one repository."""
    started = time.perf_counter()
    path = str(Path(path).resolve())
    raw = _git(path, "status", "--porcelain=v2", "--branch")
    if raw is None:
        return {"path": path, "name": Path(path).name, "error": "Не удалось прочитать репозиторий", "health": "error"}
    s = _parse_status(raw)
    files = s.pop("files")

    last = _git(path, "log", "-1", "--format=%h%x1f%s%x1f%an%x1f%aI") if not s["initial"] else None
    last_commit = None
    if last and len(p := last.split("\x1f")) == 4:
        last_commit = {"sha": p[0], "subject": p[1], "author": p[2], "time": p[3]}

    remote = _git(path, "remote", "get-url", "origin")
    if remote is None:
        remotes = (_git(path, "remote") or "").split()
        remote = _git(path, "remote", "get-url", remotes[0]) if remotes else None
    stash_out = _git(path, "stash", "list", "--format=%gd")
    brs = branches(path)

    s.update({
        "path": path,
        "name": Path(path).name,
        "remote": safe_remote(remote),
        "web_url": web_url(remote),
        "stash": len(stash_out.splitlines()) if stash_out else 0,
        "last_commit": last_commit,
        "last_fetch": _last_fetch(path),
        "branch_count": len(brs),
        "merged_branches": sum(b["merged"] for b in brs if not b["current"]),
        "stale_branches": sum(b["stale"] for b in brs if not b["current"]),
        "activity": activity(path),
    })
    s["changes"] = s["staged"] + s["modified"] + s["untracked"] + s["conflicts"]
    s["health"] = _health(s)
    if detailed:
        s["files"] = files
        s["branches"] = brs
        s["default_branch"] = default_branch(path)
        log = _git(path, "log", "-15", "--format=%h%x1f%s%x1f%an%x1f%aI%x1f%D") if not s["initial"] else None
        s["commits"] = [
            dict(zip(("sha", "subject", "author", "time", "refs"), line.split("\x1f")))
            for line in (log or "").splitlines() if line.count("\x1f") == 4
        ]
    s["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    return s


HEALTH_ORDER = {"conflict": 0, "dirty": 1, "unpushed": 2, "behind": 3, "error": 4, "local": 5, "clean": 6}


def all_status(paths: list[str], workers: int = 8) -> dict[str, Any]:
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(paths) or 1))) as ex:
        items = list(ex.map(repo_status, paths))
    items.sort(key=lambda r: (HEALTH_ORDER.get(r["health"], 9), r["name"].lower()))
    ok = [r for r in items if r["health"] != "error"]
    summary = {
        "total": len(items),
        "dirty": sum(1 for r in ok if r["changes"]),
        "unpushed": sum(1 for r in ok if r["ahead"]),
        "behind": sum(1 for r in ok if r["behind"]),
        "clean": sum(1 for r in ok if r["health"] == "clean"),
        "stale_branches": sum(r["stale_branches"] for r in ok),
        "merged_branches": sum(r["merged_branches"] for r in ok),
    }
    return {"repos": items, "summary": summary}


# ----------------------------------------------------------------------- actions


ACTION_TIMEOUT = 60


def _run(path: str, *args: str, timeout_msg: str) -> str:
    """Run a git command that changes state; raise ToolError with git's message on failure."""
    try:
        r = subprocess.run(
            ["git", *args], cwd=path, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=ACTION_TIMEOUT, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError(timeout_msg) from exc
    except OSError as exc:
        raise ToolError(f"Не удалось запустить git: {exc}") from exc
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip().splitlines()
        raise ToolError(msg[-1] if msg else "git завершился с ошибкой")
    return (r.stdout + r.stderr).strip()


def fetch(path: str) -> dict[str, Any]:
    _run(path, "fetch", "--all", "--prune", "--quiet", timeout_msg="fetch не уложился в 60 секунд")
    return repo_status(path)


def fetch_many(paths: list[str]) -> dict[str, Any]:
    def one(p: str) -> dict[str, Any]:
        try:
            _run(p, "fetch", "--all", "--prune", "--quiet", timeout_msg="таймаут")
            return {"path": p, "ok": True}
        except ToolError as exc:
            return {"path": p, "ok": False, "error": exc.message}

    with ThreadPoolExecutor(max_workers=max(1, min(6, len(paths) or 1))) as ex:
        results = list(ex.map(one, paths))
    return {"results": results, "ok": sum(r["ok"] for r in results), "failed": sum(not r["ok"] for r in results)}


def pull_ff(path: str) -> dict[str, Any]:
    st = repo_status(path)
    if st["changes"]:
        raise ToolError("Есть незакоммиченные изменения: сначала закоммитьте или уберите их в stash")
    if not st["upstream"]:
        raise ToolError("У текущей ветки нет upstream")
    _run(path, "pull", "--ff-only", "--quiet", timeout_msg="pull не уложился в 60 секунд")
    return repo_status(path)


def delete_branches(path: str, names: list[str]) -> dict[str, Any]:
    """Delete *merged* local branches with the safe `git branch -d` (never -D)."""
    brs = {b["name"]: b for b in branches(path)}
    deleted, errors = [], []
    for name in names:
        b = brs.get(name)
        if b is None:
            errors.append({"name": name, "error": "ветка не найдена"})
        elif b["current"] or b["default"]:
            errors.append({"name": name, "error": "нельзя удалить текущую или основную ветку"})
        elif not b["merged"]:
            errors.append({"name": name, "error": "ветка не слита в основную"})
        else:
            try:
                _run(path, "branch", "-d", name, timeout_msg="таймаут")
                deleted.append(name)
            except ToolError as exc:
                errors.append({"name": name, "error": exc.message})
    return {"deleted": deleted, "errors": errors}
