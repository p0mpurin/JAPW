# -*- coding: utf-8 -*-
"""Build logo.ico from logo.jpg for PyInstaller (Windows .exe icon)."""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow is required. pip install pillow", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "logo.jpg"
OUT = ROOT / "logo.ico"


def main() -> None:
    if not SRC.is_file():
        print(f"ERROR: Missing {SRC}", file=sys.stderr)
        sys.exit(1)
    im = Image.open(SRC).convert("RGBA")
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    im.save(OUT, format="ICO", sizes=sizes)
    print(f"Wrote {OUT.name}")


if __name__ == "__main__":
    main()
