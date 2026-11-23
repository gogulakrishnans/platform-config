#!/usr/bin/env python3
"""Version pins changed between two commits (L4 delivery trigger, architecture §7 and §17).

GKE pins need no action here (ArgoCD picks them up from the GitOps index). Cloud Run and MIG pins are
deployed by the delivery workflow (.github/workflows/l4-delivery.yml) with the canary scripts in
ci-templates/scripts/.

Usage: python scripts/changed-pins.py --base <sha> [--head HEAD]     prints a JSON list
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ENVS = ("dev", "stage", "uat", "prod")


def diff_pins(before: dict[str, dict], after: dict[str, dict], runtimes: dict[str, str]) -> list[dict]:
    """before/after: customer -> products.yaml spec.products. Returns one entry per changed pin."""
    out = []
    for c in sorted(after):
        for p, sel in sorted(after[c].items()):
            if sel.get("decommission"):
                continue
            old = (before.get(c, {}).get(p) or {}).get("versions", {})
            for e in ENVS:
                new_v = sel["versions"].get(e)
                if new_v and new_v != old.get(e):
                    out.append({"customer": c, "product": p, "environment": e, "from": old.get(e), "to": new_v,
                                "runtime": runtimes.get(p, "unknown")})
    return out


def products_at(ref: str | None, root: Path) -> dict[str, dict]:
    out = {}
    if ref is None:
        files = [p.relative_to(root).as_posix() for p in root.glob("customers/*/products.yaml")]
        read = lambda f: (root / f).read_text(encoding="utf-8")
    else:
        files = subprocess.run(["git", "ls-tree", "-r", "--name-only", ref, "customers/"], cwd=root,
                               capture_output=True, text=True, check=True).stdout.split()
        files = [f for f in files if f.endswith("/products.yaml")]
        read = lambda f: subprocess.run(["git", "show", f"{ref}:{f}"], cwd=root, capture_output=True,
                                        text=True, check=True).stdout
    for f in files:
        if f.split("/")[1].startswith("_"):
            continue
        out[f.split("/")[1]] = (yaml.safe_load(read(f)) or {}).get("spec", {}).get("products") or {}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path, default=ROOT)
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", default=None, help="default: the working tree")
    a = ap.parse_args(argv)
    root = a.repo.resolve()
    runtimes = {d.name: (yaml.safe_load((d / "product.yaml").read_text(encoding="utf-8")) or {})["spec"]["runtime"]["type"]
                for d in (root / "products").iterdir() if (d / "product.yaml").exists()}
    print(json.dumps(diff_pins(products_at(a.base, root), products_at(a.head, root), runtimes), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
