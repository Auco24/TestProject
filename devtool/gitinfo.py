"""Thin wrappers around the `git` command line (no extra dependencies)."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path

GIT_TIMEOUT = 8
SKIP_DIRS = {"node_modules", ".venv", "venv", "__pycache__", "target", "dist", "build", ".cache", ".idea", ".vscode"}


def git_available() -> bool:
    return shutil.which("git") is not None


def _git(cwd: str | Path, *args: str) -> str | None:
    if not git_available():
        return None
    try:
        r = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.rstrip("\n") if r.returncode == 0 else None


@dataclass(frozen=True)
class RepoInfo:
    path: str
    name: str
    branch: str | None


def repo_info(cwd: str | Path) -> RepoInfo | None:
    """Return the repository that contains *cwd*, or None."""
    top = _git(cwd, "rev-parse", "--show-toplevel")
    if not top:
        return None
    # symbolic-ref also works for a fresh repository without commits
    branch = _git(top, "symbolic-ref", "--short", "-q", "HEAD")
    if not branch:  # detached HEAD
        branch = _git(top, "rev-parse", "--short", "HEAD")
    path = str(Path(top).resolve())
    return RepoInfo(path=path, name=Path(path).name, branch=branch or None)


def find_repos(roots: list[str], max_depth: int = 2) -> list[str]:
    """Find git repositories at or below each root (not descending into repositories)."""
    found: list[str] = []
    seen: set[str] = set()

    def walk(p: Path, depth: int) -> None:
        try:
            if (p / ".git").exists():
                rp = str(p.resolve())
                if rp not in seen:
                    seen.add(rp)
                    found.append(rp)
                return
            if depth >= max_depth:
                return
            for child in sorted(p.iterdir()):
                if child.is_dir() and not child.name.startswith(".") and child.name not in SKIP_DIRS:
                    walk(child, depth + 1)
        except (PermissionError, OSError):
            return

    for root in roots:
        p = Path(root).expanduser()
        if p.is_dir():
            walk(p, 0)
    return found


@lru_cache(maxsize=256)
def _author_email(repo: str) -> str | None:
    return _git(repo, "config", "user.email") or None


@dataclass(frozen=True)
class Commit:
    repo: str
    project: str
    sha: str
    subject: str
    when: datetime

    def to_dict(self) -> dict:
        return {
            "repo": self.repo,
            "project": self.project,
            "sha": self.sha[:8],
            "subject": self.subject,
            "time": self.when.isoformat(timespec="seconds"),
            "day": self.when.date().isoformat(),
        }


def commits_between(repo: str, start: date, end: date, mine_only: bool = True) -> list[Commit]:
    """Commits authored in [start, end] (local dates, inclusive) on any branch."""
    since = datetime.combine(start, time.min).astimezone().isoformat()
    until = datetime.combine(end + timedelta(days=1), time.min).astimezone().isoformat()
    args = ["log", "--all", "--no-merges", f"--since={since}", f"--until={until}", "--pretty=format:%H%x1f%aI%x1f%s"]
    if mine_only:
        email = _author_email(repo)
        if email:
            args.append(f"--author={email}")
    out = _git(repo, *args)
    if not out:
        return []
    name = Path(repo).name
    commits = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 3:
            continue
        sha, iso, subject = parts
        try:
            when = datetime.fromisoformat(iso).astimezone()
        except ValueError:
            continue
        if start <= when.date() <= end:
            commits.append(Commit(repo=repo, project=name, sha=sha, subject=subject, when=when))
    return commits


def commits_for_repos(repos: list[str], start: date, end: date) -> list[Commit]:
    out: list[Commit] = []
    for r in repos:
        if Path(r).is_dir():
            out.extend(commits_between(r, start, end))
    out.sort(key=lambda c: c.when, reverse=True)
    return out
