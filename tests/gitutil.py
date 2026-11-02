"""Helpers for building throw-away git repositories in tests."""

import os
import subprocess
from pathlib import Path

ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def git(repo, *args, when=None):
    env = dict(ENV)
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=env).stdout


def init(path: Path, email="me@example.com"):
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", email)
    git(path, "config", "user.name", "Me")
    git(path, "config", "commit.gpgsign", "false")
    return path


def commit(repo: Path, msg: str, when=None, file="f.txt"):
    (repo / file).write_text(msg)
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", msg, when=when)


def clone(src: Path, dst: Path):
    subprocess.run(["git", "clone", "-q", str(src), str(dst)], check=True, capture_output=True, env=ENV)
    git(dst, "config", "user.email", "me@example.com")
    git(dst, "config", "user.name", "Me")
    git(dst, "config", "commit.gpgsign", "false")
    return dst
