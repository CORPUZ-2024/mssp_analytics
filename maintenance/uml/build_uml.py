"""Regenerate the UML diagrams in docs/uml/.

The diagrams are hand-laid-out SVG drawn by umlkit.py (no Graphviz/PlantUML
dependency). Class, function and import names in d1-d5 were taken from the code;
when the code changes, update the matching dN_*.py file and re-run.

Usage (from the repository root):
    python maintenance/uml/build_uml.py                 # all diagrams
    python maintenance/uml/build_uml.py d4_build_sequence
    python maintenance/uml/build_uml.py --png           # also write PNG previews
                                                        # next to this script
                                                        # (needs Edge or Chrome)
"""
from __future__ import annotations

import importlib
import pathlib
import shutil
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE.parent.parent / "docs" / "uml"
NAMES = {
    "d1_components": "01-system-components.svg",
    "d2_etl_classes": "02-etl-class-diagram.svg",
    "d3_modules": "03-analysis-modules-package-diagram.svg",
    "d4_build_sequence": "04-build-site-sequence.svg",
    "d5_dashboards": "05-dashboards-class-diagram.svg",
}
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "msedge", "google-chrome", "chromium",
]


def _browser() -> str | None:
    for b in BROWSERS:
        if pathlib.Path(b).exists() or shutil.which(b):
            return b
    return None


def _png(svg: pathlib.Path, w: int, h: int) -> None:
    browser = _browser()
    if not browser:
        print("  (no Edge/Chrome found; skipping PNG preview)")
        return
    png = HERE / (svg.stem + ".png")
    png.unlink(missing_ok=True)
    subprocess.run([browser, "--headless", "--disable-gpu", "--hide-scrollbars",
                    f"--window-size={w},{h}", f"--screenshot={png}", svg.as_uri()],
                   capture_output=True, timeout=60)
    for _ in range(40):  # the screenshot is written asynchronously
        if png.exists():
            break
        time.sleep(0.25)
    print("  preview:", png if png.exists() else "not written")


def main(argv: list[str]) -> int:
    want_png = "--png" in argv
    mods = [a for a in argv if not a.startswith("--")] or list(NAMES)
    sys.path.insert(0, str(HERE))
    OUT.mkdir(parents=True, exist_ok=True)
    for mod in mods:
        d = importlib.import_module(mod).make()
        path = OUT / NAMES[mod]
        path.write_text(d.svg(), encoding="utf-8")
        print(f"{path.relative_to(HERE.parent.parent)}  {d.w}x{d.h}")
        if want_png:
            _png(path, d.w, d.h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
