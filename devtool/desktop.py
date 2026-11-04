"""Desktop app: runs the local server in a background thread and shows the UI in a native window.

Used by the installers (PyInstaller bundle) and by ``devtool app``.

* The window is provided by pywebview (Edge WebView2 on Windows, WebKit on macOS).
  If pywebview is not available, the UI opens in the default browser instead.
* The server listens on 127.0.0.1 only, on a fixed port when possible so that
  browser storage (theme, language, remembered filters) survives restarts.
* A second launch while the app is running simply opens another window to the
  running instance instead of starting a new server.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from . import __version__

APP_NAME = "Dev Toolkit"
HOST = "127.0.0.1"
PREFERRED_PORT = 47821

log = logging.getLogger("devtool.desktop")


def data_dir() -> Path:
    path = Path(os.environ.get("DEVTOOL_HOME", Path.home() / ".devtool")).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ensure_streams() -> None:
    """A windowed executable on Windows has no console: sys.stdout / sys.stderr are None and
    anything that writes to them would crash. Send such output to desktop.log instead."""
    if sys.stdout is None or sys.stderr is None:
        stream = open(data_dir() / "desktop.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives for the process
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream


def _setup_logging() -> None:
    log_file = data_dir() / "desktop.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8")],
        force=True,
    )


def port_is_free(port: int, host: str = HOST) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def free_port(host: str = HOST) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def is_devtool(port: int, host: str = HOST, timeout: float = 1.5) -> bool:
    """True when a Dev Toolkit server already answers on this port."""
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=timeout) as r:  # noqa: S310 - localhost only
            data = json.loads(r.read().decode("utf-8"))
        return data.get("app") == "devtool" and data.get("status") == "ok"
    except (OSError, ValueError):
        return False


def choose_port(preferred: int = PREFERRED_PORT) -> tuple[int, bool]:
    """Return (port, already_running)."""
    if port_is_free(preferred):
        return preferred, False
    if is_devtool(preferred):
        return preferred, True
    return free_port(), False


class ServerThread:
    """uvicorn in a daemon thread, stoppable from the main thread."""

    def __init__(self, port: int, host: str = HOST) -> None:
        import uvicorn

        from .api import app

        self.url = f"http://{host}:{port}"
        config = uvicorn.Config(app, host=host, port=port, log_level="warning", log_config=None, access_log=False)
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, name="devtool-server", daemon=True)

    def start(self, timeout: float = 20.0) -> None:
        self.thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.server.started:
                return
            if not self.thread.is_alive():
                raise RuntimeError("Dev Toolkit server failed to start (see desktop.log)")
            time.sleep(0.05)
        raise RuntimeError("Dev Toolkit server did not start in time")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


def open_window(url: str) -> bool:
    """Show the UI in a native window. Returns False when pywebview is unavailable."""
    try:
        import webview
    except ImportError:
        log.warning("pywebview is not installed; falling back to the browser")
        return False

    try:
        webview.settings["ALLOW_DOWNLOADS"] = True  # snippet export
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True  # GitHub links etc.
    except (AttributeError, TypeError):  # older pywebview
        pass
    webview.create_window(APP_NAME, url, width=1360, height=900, min_size=(900, 620), text_select=True)
    storage = data_dir() / "webview"
    storage.mkdir(exist_ok=True)
    try:
        # private_mode=False + storage_path keeps localStorage (theme, language) between launches
        webview.start(private_mode=False, storage_path=str(storage))
    except TypeError:  # pywebview < 4
        webview.start()
    return True


def smoke_test() -> int:
    """Start the bundled server, request a few pages, exit. Used by CI on the built app."""
    server = ServerThread(free_port())
    server.start()
    try:
        for path in ("/api/health", "/", "/static/app.js", "/static/style.css"):
            with urllib.request.urlopen(server.url + path, timeout=10) as r:  # noqa: S310 - localhost only
                if r.status != 200:
                    print(f"FAIL {path}: HTTP {r.status}")
                    return 1
        with urllib.request.urlopen(server.url + "/api/health", timeout=10) as r:  # noqa: S310
            print("OK", r.read().decode("utf-8"))
        try:
            import webview  # noqa: F401

            print("pywebview: available")
        except ImportError:
            print("pywebview: not bundled")
        return 0
    finally:
        server.stop()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    _ensure_streams()
    if "--version" in argv:
        print(f"{APP_NAME} {__version__}")
        return 0
    if "--smoke-test" in argv:
        return smoke_test()

    _setup_logging()
    port, running = choose_port()
    url = f"http://{HOST}:{port}"
    if running:
        log.info("Dev Toolkit already running on %s, opening another window", url)
        if not open_window(url):
            webbrowser.open(url)
        return 0

    server = ServerThread(port)
    server.start()
    log.info("Dev Toolkit %s started on %s", __version__, url)
    try:
        if not open_window(url):
            webbrowser.open(url)
            print(f"{APP_NAME}: {url}  (Ctrl+C to stop)")
            while server.thread.is_alive():
                server.thread.join(timeout=1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        log.info("Dev Toolkit stopped")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
