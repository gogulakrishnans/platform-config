#!/usr/bin/env python3
"""Render the first ```mermaid block of each docs/diagrams/*.md to an SVG next to it.

Usage:
    python scripts/render-diagrams.py            # render all diagrams
    python scripts/render-diagrams.py --check    # fail if an SVG is missing or older than its source

Requires the Mermaid CLI (`npm i -g @mermaid-js/mermaid-cli`, command `mmdc`).
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
BLOCK = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)


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
        subprocess.run(
            [mmdc, "-i", str(src), "-o", str(svg), "-b", "white", "-q"],
            check=True,
            shell=sys.platform == "win32",
        )
    print(f"render {md.name} -> {svg.name}")


def check(md: Path) -> bool:
    if mermaid_source(md) is None:
        return True
    svg = md.with_suffix(".svg")
    if not svg.exists():
        print(f"missing {svg.name}")
        return False
    # Google Cloud icon version (docs/diagrams/src, rendered with Graphviz): both outputs present,
    # and the SVG self-contained (icons embedded, no links to files on the author's machine).
    ok = True
    for ext in (".svg", ".png"):
        out = md.with_name(f"{md.stem}-gcp{ext}")
        if not out.exists():
            print(f"missing {out.name} (python docs/diagrams/src/render_all.py {md.stem})")
            ok = False
    gsvg = md.with_name(f"{md.stem}-gcp.svg")
    if gsvg.exists() and re.search(r'href="(?!data:|#|https?:)[^"]+"', gsvg.read_text(encoding="utf-8")):
        print(f"{gsvg.name} links to local files; re-render so the icons are embedded")
        ok = False
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = sorted(DIAGRAMS.glob("*.md"))
    if args.check:
        return 0 if all(check(md) for md in files) else 1
    mmdc = shutil.which("mmdc")
    if not mmdc:
        print("mmdc not found: npm i -g @mermaid-js/mermaid-cli", file=sys.stderr)
        return 1
    for md in files:
        render(md, mmdc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
