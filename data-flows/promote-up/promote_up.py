#!/usr/bin/env python3
"""Promote-up pipeline (architecture §9). Skeleton: validation and planning are complete and
unit-tested; the product export/import calls are made by the runner steps in
.github/workflows/promote-up.yml.

Moves a customer's product configuration one step up (dev -> stage -> uat -> prod) as a versioned
package. Rules:
  * the customer enabled promote-up in data-sharing.yaml, and every product it promotes supports
    config export/import (catalog `supportsExport`)
  * exactly one step up; never down, never skipping an environment
  * the target runs a version that can read the package: target minor >= source minor, or the
    target is inside the source schema's compatibility window
  * three hops, each with its own identity:
      1. export  - SOURCE runner pool (its deployer identity), into the source env's own product bucket
      2. publish - after the approvals in data-sharing.yaml (GitHub Environment reviewers), the
                   `promoter` identity (prod pool, the only writer of the customer's shared bucket)
                   copies the package into the shared bucket's promote/ prefix
      3. import  - TARGET runner pool (its deployer identity), which can read the shared bucket
    Lower environments never write into prod or into the shared bucket.

Usage:
    python data-flows/promote-up/promote_up.py --customer acme-corp --product payment-api --from uat --to prod
Prints the plan as JSON; exit 2 when the promotion is not allowed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ORDER = ("dev", "stage", "uat", "prod")
GROUP_OF_ENV = {"dev": "devstage", "stage": "devstage", "uat": "uat", "prod": "prod"}


class PromoteError(Exception):
    pass


def read(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def minor(v: str) -> tuple[int, int]:
    m = re.match(r"^(\d+)\.(\d+)\.", v)
    if not m:
        raise PromoteError(f"unparseable version {v!r}")
    return int(m.group(1)), int(m.group(2))


def plan(root: Path, customer: str, product: str, source: str, target: str, run_id: str) -> dict:
    cdir = root / "customers" / customer
    if not cdir.is_dir():
        raise PromoteError(f"unknown customer {customer!r}")
    sharing = read(cdir / "data-sharing.yaml")["spec"]["promoteUp"]
    if not sharing.get("enabled"):
        raise PromoteError(f"{customer}: promote-up is disabled in data-sharing.yaml")
    selected = read(cdir / "products.yaml")["spec"]["products"]
    if product not in selected or selected[product].get("decommission"):
        raise PromoteError(f"{customer}: {product} is not enabled")
    catalog = read(root / "products" / product / "product.yaml")["spec"]
    if not catalog["supportsExport"]:
        raise PromoteError(f"{product} does not support config export/import")
    if source not in ORDER or target not in ORDER or ORDER.index(target) != ORDER.index(source) + 1:
        raise PromoteError(f"promotion must go exactly one step up ({' -> '.join(ORDER)}), not {source} -> {target}")

    v_src, v_tgt = selected[product]["versions"][source], selected[product]["versions"][target]
    oldest = tuple(int(x) for x in catalog["releases"]["schemaCompatibility"]["oldestCompatible"].split("."))
    if minor(v_tgt) < minor(v_src) and minor(v_tgt) < oldest:
        raise PromoteError(f"{target} runs {v_tgt}, which cannot read a {v_src} package "
                           f"(oldest compatible {'.'.join(map(str, oldest))})")

    if not catalog["data"]["storage"]["required"]:
        raise PromoteError(f"{product} has no bucket to stage its export package in")

    plat = read(root / "inventory/platform.yaml")
    prefix = plat["bucketPrefix"]
    host = {"prod": plat["dns"]["publicZone"], "uat": plat["dns"]["uatZone"]}
    def endpoint(env: str) -> str:
        return f"https://{customer}.{host[env]}" if env in host else f"https://{customer}.{env}.{plat['dns']['privateZone']}"

    name = f"{product}/{run_id}/{source}-{v_src}.tar.gz"
    short = catalog["shortCode"]
    return {
        "runId": run_id,
        "customer": customer,
        "product": product,
        "from": {"env": source, "version": v_src, "runnerPool": GROUP_OF_ENV[source],
                 "exportUrl": f"{endpoint(source)}{catalog['routing']['paths'][0]}/admin/config:export"},
        "to": {"env": target, "version": v_tgt, "runnerPool": GROUP_OF_ENV[target],
               "importUrl": f"{endpoint(target)}{catalog['routing']['paths'][0]}/admin/config:import",
               "githubEnvironment": f"promote-{target}"},
        "staging": f"gs://{prefix}-{customer}-{short}-{source}/promote/{name}",
        "package": f"gs://{prefix}-{customer}-shared/promote/{name}",
        "publisher": f"promoter@{plat['projects']['platform-prod']['id']}.iam.gserviceaccount.com",
        "approvals": sharing.get("approvals", []),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path, default=ROOT)
    ap.add_argument("--customer", required=True)
    ap.add_argument("--product", required=True)
    ap.add_argument("--from", dest="source", required=True)
    ap.add_argument("--to", dest="target", required=True)
    ap.add_argument("--run-id", default="local")
    a = ap.parse_args(argv)
    try:
        print(json.dumps(plan(a.repo, a.customer, a.product, a.source, a.target, a.run_id), indent=2))
    except PromoteError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
