import socket
import urllib.request

import pytest

from devtool import desktop


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVTOOL_HOME", str(tmp_path / "home"))


def test_free_and_busy_ports():
    port = desktop.free_port()
    assert desktop.port_is_free(port)
    with socket.socket() as s:
        s.bind((desktop.HOST, port))
        s.listen()
        assert not desktop.port_is_free(port)
        assert not desktop.is_devtool(port, timeout=0.5)  # something else listens there


def test_choose_port_prefers_fixed_port():
    port = desktop.free_port()
    assert desktop.choose_port(port) == (port, False)


def test_choose_port_falls_back_when_taken_by_another_program():
    port = desktop.free_port()
    with socket.socket() as s:
        s.bind((desktop.HOST, port))
        s.listen()
        chosen, running = desktop.choose_port(port)
    assert chosen != port and running is False


def test_server_thread_and_reuse_of_running_instance():
    port = desktop.free_port()
    server = desktop.ServerThread(port)
    server.start()
    try:
        with urllib.request.urlopen(server.url + "/api/health") as r:
            assert b'"app":"devtool"' in r.read()
        assert desktop.is_devtool(port)
        assert desktop.choose_port(port) == (port, True)  # second launch reuses the first one
    finally:
        server.stop()
    assert not server.thread.is_alive()


def test_smoke_test(capsys):
    assert desktop.smoke_test() == 0
    assert "OK" in capsys.readouterr().out


def test_main_opens_window_then_stops_server(monkeypatch):
    seen = {}

    def fake_window(url):
        with urllib.request.urlopen(url + "/api/health") as r:
            seen["status"] = r.status
        seen["url"] = url
        return True

    monkeypatch.setattr(desktop, "PREFERRED_PORT", desktop.free_port())
    monkeypatch.setattr(desktop, "open_window", fake_window)
    assert desktop.main([]) == 0
    assert seen["status"] == 200
    assert desktop.port_is_free(int(seen["url"].rsplit(":", 1)[1]))  # server shut down with the window
    assert (desktop.data_dir() / "desktop.log").exists()


def test_open_window_without_pywebview(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_webview(name, *args, **kwargs):
        if name == "webview":
            raise ImportError("no pywebview")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_webview)
    assert desktop.open_window("http://127.0.0.1:1") is False


def test_version_flag(capsys):
    assert desktop.main(["--version"]) == 0
    assert "Dev Toolkit" in capsys.readouterr().out
