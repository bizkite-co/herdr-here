#!/usr/bin/env python3
"""Run the installer from a checkout. The installed command is herdr-here-install."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from herdr_here.install import main

if __name__ == "__main__":
    sys.exit(main())
