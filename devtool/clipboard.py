"""Minimal cross-platform clipboard support without extra dependencies."""

from __future__ import annotations

import os
import shutil
import subprocess

_CANDIDATES = [
    ["pbcopy"],                                # macOS
    ["clip.exe"],                              # Windows / WSL
    ["wl-copy"],                               # Wayland
    ["xclip", "-selection", "clipboard"],      # X11
    ["xsel", "--clipboard", "--input"],        # X11
]


def copy(text: str) -> bool:
    """Copy text to the system clipboard. Returns False when no clipboard tool is available."""
    for cmd in _CANDIDATES:
        if cmd[0] == "wl-copy" and not os.environ.get("WAYLAND_DISPLAY"):
            continue
        if cmd[0] in ("xclip", "xsel") and not os.environ.get("DISPLAY"):
            continue
        exe = shutil.which(cmd[0])
        if not exe:
            continue
        encoding = "utf-16le" if cmd[0] == "clip.exe" else "utf-8"
        try:
            subprocess.run([exe, *cmd[1:]], input=text.encode(encoding), check=True, timeout=5)
            return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False
