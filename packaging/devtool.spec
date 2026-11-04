# PyInstaller spec for the Dev Toolkit desktop app.
# Build from the repository root:   pyinstaller packaging/devtool.spec --noconfirm
# Result: dist/DevToolkit/ (Windows, Linux) or dist/Dev Toolkit.app (macOS).

import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 - provided by PyInstaller
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "devtool" / "__init__.py").read_text()).group(1)
ASSETS = ROOT / "devtool" / "assets"

hiddenimports = collect_submodules("uvicorn") + ["devtool.api"]
try:
    import webview  # noqa: F401

    hiddenimports += collect_submodules("webview")
except ImportError:
    print("WARNING: pywebview is not installed - the app will open in the browser instead of its own window")

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "devtool" / "static"), "devtool/static"),
        (str(ASSETS), "devtool/assets"),
    ],
    hiddenimports=hiddenimports,
    # not used by the app; pulled in by optional imports of other libraries
    excludes=["tkinter", "pytest", "PyInstaller", "numpy", "PIL", "yaml", "charset_normalizer", "IPython", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

icon = str(ASSETS / ("icon.icns" if sys.platform == "darwin" else "icon.ico"))

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DevToolkit",
    console=False,  # no terminal window
    icon=icon,
    version=None,
)

coll = COLLECT(exe, a.binaries, a.datas, name="DevToolkit")  # noqa: F821

if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name="Dev Toolkit.app",
        icon=icon,
        bundle_identifier="io.github.auco24.devtoolkit",
        version=VERSION,
        info_plist={
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            # the UI talks to its own server on 127.0.0.1
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        },
    )
