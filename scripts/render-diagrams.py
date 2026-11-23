#!/usr/bin/env python3
"""Diagram gate and Mermaid renderer.

Layout:
    docs/diagrams/<name>.md            page: explanation + the Google Cloud icon diagram
    docs/diagrams/<name>-gcp.{svg,png} icon diagram, rendered by docs/diagrams/src/render_all.py (Graphviz)
    docs/diagrams/backup/<name>.md     Mermaid version (backup), rendered to backup/<name>.svg

Usage:
    python scripts/render-diagrams.py            # re-render the Mermaid backups (needs mmdc)
    python scripts/render-diagrams.py --check    # every page has its icon diagram (self-contained SVG
                                                 # + PNG) and every Mermaid backup has its SVG

Mermaid CLI: `npm i -g @mermaid-js/mermaid-cli` (command `mmdc`).
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIAGRAMS = ROOT / "docs" / "diagrams"
BACKUP = DIAGRAMS / "backup"
BLOCK = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)
LOCAL_HREF = re.compile(r'href="(?!data:|#|https?:)[^"]+"')


def mermaid_source(md: Path) -> str | None:
    match = BLOCK.search(md.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def render(md: Path, mmdc: str) -> None:
    source = mermaid_source(md)
    if source is None:
        print(f"skip   {md.name} (no mermaid block)")
        return
    svg = md.with_suffix(".svg")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "diagram.mmd"
        src.write_text(source, encoding="utf-8")
        subprocess.run([mmdc, "-i", str(src), "-o", str(svg), "-b", "white", "-q"],
                       check=True, shell=sys.platform == "win32")
    print(f"render {md.relative_to(DIAGRAMS)} -> {svg.name}")


def check_page(md: Path) -> bool:
    """A diagram page shows its Google Cloud icon diagram, and the outputs exist and are portable."""
    ok = True
    for ext in (".svg", ".png"):
        out = md.with_name(f"{md.stem}-gcp{ext}")
        if not out.exists():
            print(f"missing {out.name} (python docs/diagrams/src/render_all.py {md.stem})")
            ok = False
    gsvg = md.with_name(f"{md.stem}-gcp.svg")
    if gsvg.exists() and LOCAL_HREF.search(gsvg.read_text(encoding="utf-8")):
        print(f"{gsvg.name} links to local files; re-render so the icons are embedded")
        ok = False
    if f"]({md.stem}-gcp.svg)" not in md.read_text(encoding="utf-8"):
        print(f"{md.name} does not show {md.stem}-gcp.svg")
        ok = False
    if not (BACKUP / md.name).exists():
        print(f"missing backup/{md.name} (Mermaid version)")
        ok = False
    return ok


def check_backup(md: Path) -> bool:
    if mermaid_source(md) is None:
        return True
    if not md.with_suffix(".svg").exists():
        print(f"missing backup/{md.with_suffix('.svg').name}")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    pages = sorted(DIAGRAMS.glob("*.md"))
    backups = sorted(BACKUP.glob("*.md"))
    if args.check:
        results = [check_page(p) for p in pages] + [check_backup(b) for b in backups]
        return 0 if all(results) else 1
    mmdc = shutil.which("mmdc")
    if not mmdc:
        print("mmdc not found: npm i -g @mermaid-js/mermaid-cli", file=sys.stderr)
        return 1
    for md in backups:
        render(md, mmdc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
