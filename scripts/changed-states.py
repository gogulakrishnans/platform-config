#!/usr/bin/env python3
"""Changed-path detection: which Terraform states a change touches, in apply order (architecture §17).

A customer PR plans only that customer's states, never all 200+. A shared-module change fans out to
every root that uses the module (directly or through other modules), in batches.

Apply waves (each wave depends on the previous one):
  1 L1         layers/L1-foundation
  2 L2-region  layers/L2-region/<region>/<group>
  3 L3-keys    layers/L3-customer/<c>/keys-{nonprod,prod}
  4 L3-env     layers/L3-customer/<c>/{dev,stage,uat,prod}     (then the db-bootstrap job runs)
  5 L3-shared  layers/L3-customer/<c>/exchange
  6 L2-edge    layers/L2-edge/<name>                          (needs the NEGs/MIGs from L3)

Usage:
    git diff --name-only origin/main...HEAD | python scripts/changed-states.py           # JSON plan
    python scripts/changed-states.py --all --shard 3/7                                   # drift: 1/7 of all states
A GitHub matrix holds at most 256 jobs, so any wave above MATRIX_LIMIT must be applied in shards
(terraform-apply.yml workflow_dispatch with --shard).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
LAYERS = Path("infrastructure/layers")
MODULES = Path("infrastructure/modules")
MATRIX_LIMIT = 250
WAVES = ("L1", "L2-region", "L3-keys", "L3-env", "L3-shared", "L2-edge")
SOURCE = re.compile(r'source\s*=\s*"((?:\.\./)+(?:infrastructure/modules/)?([a-z0-9-]+))"')
# Each state's pool: which self-hosted runner pool (and GitHub Environment) may apply it.
POOL_OF_GROUP = {"devstage": "devstage", "uat": "uat", "prod": "prod"}


def roots(root: Path) -> list[Path]:
    return sorted(p.parent.relative_to(root) for p in (root / LAYERS).rglob("main.tf") if ".terraform" not in p.parts)


def module_uses(root: Path) -> dict[str, set[str]]:
    """module name -> modules it calls (transitively closed later)."""
    uses: dict[str, set[str]] = {}
    for d in (root / MODULES).iterdir():
        if d.is_dir():
            text = "".join(f.read_text(encoding="utf-8") for f in d.glob("*.tf"))
            uses[d.name] = {m.group(2) for m in SOURCE.finditer(text)}
    return uses


def root_modules(root: Path, r: Path, uses: dict[str, set[str]]) -> set[str]:
    text = "".join(f.read_text(encoding="utf-8") for f in (root / r).glob("*.tf"))
    todo = [m.group(2) for m in SOURCE.finditer(text)]
    seen: set[str] = set()
    while todo:
        m = todo.pop()
        if m not in seen:
            seen.add(m)
            todo += list(uses.get(m, ()))
    return seen


PREFIX = re.compile(r'prefix "([^"]+)"')


def state_prefix(root: Path, r: Path) -> str:
    """The GCS state prefix each root declares in its backend comment (one source of truth)."""
    for f in sorted((root / r).glob("*.tf")):
        m = PREFIX.search(f.read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    raise SystemExit(f"{r.as_posix()}: no state prefix declared")


def classify(r: Path) -> tuple[str, str]:
    """(wave, pool) of a root."""
    parts = r.relative_to(LAYERS).parts
    if parts[0] == "L0-bootstrap":
        return "L0", "manual"
    if parts[0] == "L1-foundation":
        return "L1", "prod"
    if parts[0] == "L2-region":
        return "L2-region", POOL_OF_GROUP[parts[2]]
    if parts[0] == "L2-edge":
        name = parts[1]
        return "L2-edge", "devstage" if name.startswith("devstage") else POOL_OF_GROUP[name]
    state = parts[2]
    if state.startswith("keys-"):
        return "L3-keys", "prod" if state == "keys-prod" else "uat"
    if state == "exchange":
        return "L3-shared", "prod"
    return "L3-env", {"dev": "devstage", "stage": "devstage", "uat": "uat", "prod": "prod"}[state]


def customers_using(root: Path, product: str) -> set[str]:
    out = set()
    for f in (root / "customers").glob("*/products.yaml"):
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        if product in (doc.get("spec", {}).get("products") or {}):
            out.add(f.parent.name)
    return out


def customer_region(root: Path, customer: str) -> str | None:
    f = root / "customers" / customer / "customer.yaml"
    if not f.exists():
        return None
    return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("spec", {}).get("region", {}).get("primary")


def affected(root: Path, changed: list[str]) -> set[Path]:
    all_roots = roots(root)
    uses = module_uses(root)
    mods = {r: root_modules(root, r, uses) for r in all_roots}
    out: set[Path] = set()

    def l3(customer: str) -> set[Path]:
        return {r for r in all_roots if r.parts[2:4] == ("L3-customer", customer)}

    def edges(region: str | None = None) -> set[Path]:
        """External edges (uat, prod) and the Dev/Stage edge of the region (all regions if None)."""
        return {r for r in all_roots if r.parts[2] == "L2-edge"
                and (not r.parts[3].startswith("devstage-") or region is None or r.parts[3] == f"devstage-{region}")}

    for f in changed:
        p = Path(f)
        parts = p.parts
        if not parts:
            continue
        if p.is_relative_to(MODULES) and len(parts) > 2:
            out |= {r for r in all_roots if parts[2] in mods[r]}
        elif p.is_relative_to(LAYERS):
            out |= {r for r in all_roots if p.is_relative_to(r)}
        elif parts[0] == "customers" and len(parts) > 2 and not parts[1].startswith("_"):
            c = parts[1]
            if parts[2] == "helm":
                continue                       # Kubernetes values only (ArgoCD)
            region = customer_region(root, c)
            out |= l3(c) | edges(region)
            if parts[2] == "customer.yaml" and region:
                out |= {r for r in all_roots if r.parts[2:5] == ("L2-region", region, "prod")}   # hot-standby DR sizing
        elif parts[0] == "products" and len(parts) > 2 and not parts[1].startswith("_"):
            if parts[2] in ("helm", "releases.yaml"):
                continue                       # delivery (L4), not infrastructure
            for c in customers_using(root, parts[1]):
                out |= l3(c) | edges(customer_region(root, c))
        elif f in ("inventory/platform.yaml", "inventory/regions.yaml"):
            out |= {r for r in all_roots if classify(r)[0] != "L0"}
        # inventory/clusters|sql are L2 outputs; argocd/, helm/, docs/ touch no state
    return {r for r in out if classify(r)[0] != "L0"}


def plan(root: Path, states: set[Path], batch_size: int) -> dict:
    waves = []
    for w in WAVES:
        members = sorted(r for r in states if classify(r)[0] == w)
        batches = [members[i:i + batch_size] for i in range(0, len(members), batch_size)] or []
        waves.append({
            "wave": w,
            "count": len(members),
            "states": [{"dir": r.as_posix(), "prefix": state_prefix(root, r), "pool": classify(r)[1]} for r in members],
            "batches": [[r.as_posix() for r in b] for b in batches],
        })
    return {"total": len(states), "waves": waves}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path, default=ROOT)
    ap.add_argument("--all", action="store_true", help="every state (drift detection)")
    ap.add_argument("--batch-size", type=int, default=25)
    ap.add_argument("--shard", default="0/1", help="i/n: keep every n-th state starting at i (sorted)")
    ap.add_argument("files", nargs="*", help="changed files (default: read from stdin)")
    a = ap.parse_args(argv)
    root = a.repo.resolve()
    if a.all:
        states = {r for r in roots(root) if classify(r)[0] != "L0"}
    else:
        files = a.files or [l.strip() for l in sys.stdin if l.strip()]
        states = affected(root, files)
    i, n = (int(x) for x in a.shard.split("/"))
    states = {r for k, r in enumerate(sorted(states)) if k % n == i}
    result = plan(root, states, a.batch_size)
    result["overMatrixLimit"] = [w["wave"] for w in result["waves"] if w["count"] > MATRIX_LIMIT]
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
