"""Entry point for the PyInstaller-built desktop app."""

import sys

from devtool.desktop import main

if __name__ == "__main__":
    sys.exit(main())
