#!/usr/bin/env python3
"""Placement job: assign each customer to cells (clusters + Cloud SQL instances) in its region.

Reads only Git (inventory/, customers/, products/) and never queries GCP, so it is unit-tested
offline. See docs/architecture.md §3.

Usage:
    python scripts/placement/placement.py --repo . --customer acme-corp          # dry run, prints placement
    python scripts/placement/placement.py --repo . --customer acme-corp --write  # writes placement back
    python scripts/placement/placement.py --repo . --all --write

Exit codes: 0 ok · 2 validation error · 3 capacity or quota request needed (see --request-file)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CUSTOMER_ID = re.compile(r"^[a-z][a-z0-9-]{1,18}[a-z0-9]$")
GROUPS = ("devstage", "uat", "prod")
ENVS_BY_GROUP = {"devstage": ("dev", "stage"), "uat": ("uat",), "prod": ("prod",)}
QUOTA_THRESHOLD = 0.8


class PlacementError(Exception):
    """The customer PR is invalid (exit 2)."""


@dataclass
class CapacityRequest(Exception):
    """A new cell or a quota change is needed before the customer can be placed (exit 3)."""

    kind: str  # "cell" | "sql" | "quota"
    region: str
    group: str
    detail: str

    def __str__(self) -> str:
        return f"{self.kind} request for {self.group} in {self.region}: {self.detail}"


@dataclass
class Repo:
    platform: dict
    regions: dict[str, dict]
    clusters: dict[str, dict]
    sql: dict[str, dict]
    customers: dict[str, dict]
    products: dict[str, dict]
    customer_products: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> "Repo":
        def read(path: Path) -> dict:
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

        inv = root / "inventory"
        regions = {r["name"]: r for r in read(inv / "regions.yaml")["regions"]}
        clusters = {d["name"]: d for d in (read(p) for p in sorted((inv / "clusters").glob("*.yaml")))}
        sql = {d["name"]: d for d in (read(p) for p in sorted((inv / "sql").glob("*.yaml")))}
        customers, customer_products = {}, {}
        for d in sorted((root / "customers").iterdir()):
            if d.is_dir() and not d.name.startswith("_") and (d / "customer.yaml").exists():
                customers[d.name] = read(d / "customer.yaml")
                pfile = d / "products.yaml"
                customer_products[d.name] = read(pfile).get("spec", {}).get("products", {}) if pfile.exists() else {}
        products = {
            d.name: read(d / "product.yaml")
            for d in sorted((root / "products").iterdir())
            if d.is_dir() and not d.name.startswith("_") and (d / "product.yaml").exists()
        }
        return cls(read(inv / "platform.yaml"), regions, clusters, sql, customers, products, customer_products)


def _placement(customer: dict) -> dict:
    return customer.get("spec", {}).get("placement") or {}


def _assigned(repo: Repo, *, cluster: str | None = None, sql: str | None = None, exclude: str = "") -> int:
    """Number of customers already placed on a cluster or a SQL instance (a customer counts once)."""
    count = 0
    for name, c in repo.customers.items():
        if name == exclude:
            continue
        p = _placement(c)
        if cluster and any(p.get(g, {}).get("cluster") == cluster for g in GROUPS):
            count += 1
        elif sql and any(p.get(g, {}).get("sqlInstance") == sql for g in GROUPS):
            count += 1
    return count


def _cloud_run_products(repo: Repo, customer: str) -> int:
    return sum(
        1
        for pname in repo.customer_products.get(customer, {})
        if repo.products.get(pname, {}).get("spec", {}).get("runtime", {}).get("type") == "cloud-run"
    )


def cloud_run_services(repo: Repo, region: str, group: str, extra_customer: str | None = None) -> int:
    """Projected Cloud Run services in (group compute project, region), including DR copies in prod."""
    total = 0
    names = set(repo.customers) | ({extra_customer} if extra_customer else set())
    for name in names:
        cust = repo.customers.get(name, {})
        primary = cust.get("spec", {}).get("region", {}).get("primary")
        if cust.get("spec", {}).get("options", {}).get("isolation") == "dedicated":
            continue
        n = _cloud_run_products(repo, name)
        if not n or primary not in repo.regions:
            continue
        per_customer = n * len(ENVS_BY_GROUP[group])
        if primary == region:
            total += per_customer
        if group == "prod" and repo.regions[primary]["drPair"] == region:
            total += per_customer  # DR copies live in the pair region
    return total


def _pick(candidates: list[tuple[str, int]]) -> str | None:
    """Most free headroom wins; ties go to the lowest name (deterministic)."""
    free = [(name, headroom) for name, headroom in candidates if headroom > 0]
    if not free:
        return None
    return sorted(free, key=lambda x: (-x[1], x[0]))[0][0]


def place(repo: Repo, name: str) -> dict:
    """Return the placement block for a customer. Existing valid placements are kept unchanged."""
    if not CUSTOMER_ID.match(name):
        raise PlacementError(f"invalid customer ID {name!r}: lowercase, 3-20 chars, [a-z0-9-]")
    cust = repo.customers[name]
    spec = cust.get("spec", {})
    if cust.get("metadata", {}).get("name") != name:
        raise PlacementError(f"metadata.name must equal the directory name {name!r}")
    if spec.get("options", {}).get("isolation") == "dedicated":
        return {"dedicated": True}

    region = spec.get("region", {}).get("primary")
    if region not in repo.regions or repo.regions[region]["status"] != "active":
        raise PlacementError(f"region not provisioned: {region}")
    pair = repo.regions[region]["drPair"]
    if repo.regions.get(pair, {}).get("status") != "active":
        raise PlacementError(f"region not provisioned: DR pair {pair} of {region} is not active")

    existing = _placement(cust)
    result: dict = {}

    # Region quota check for Cloud Run (verification V3), primary region and DR pair.
    if _cloud_run_products(repo, name):
        for group in GROUPS:
            regions_to_check = [region] + ([pair] if group == "prod" else [])
            for r in regions_to_check:
                quota = repo.regions[r].get("quotas", {}).get("cloudRunServices", {}).get(group, 1000)
                projected = cloud_run_services(repo, r, group, extra_customer=name)
                if projected > QUOTA_THRESHOLD * quota:
                    raise CapacityRequest("quota", r, group, f"{projected} Cloud Run services > 80% of {quota}")

    # Non-prod databases: one instance from the regional non-prod pool, shared by dev, stage, uat.
    nonprod_sql = existing.get("devstage", {}).get("sqlInstance")
    if not (nonprod_sql and repo.sql.get(nonprod_sql, {}).get("region") == region):
        candidates = [
            (s["name"], s["capacity"]["maxCustomers"] - _assigned(repo, sql=s["name"], exclude=name))
            for s in repo.sql.values()
            if s["side"] == "nonprod" and s["region"] == region and s["status"] == "active"
        ]
        nonprod_sql = _pick(candidates)
        if not nonprod_sql:
            raise CapacityRequest("sql", region, "nonprod", "no non-prod Cloud SQL instance with headroom")

    for group in GROUPS:
        current = existing.get(group, {})
        cluster = current.get("cluster")
        valid = (
            cluster in repo.clusters
            and repo.clusters[cluster]["group"] == group
            and repo.clusters[cluster]["region"] == region
        )
        if not valid:
            candidates = [
                (c["name"], c["capacity"]["maxCustomers"] - _assigned(repo, cluster=c["name"], exclude=name))
                for c in repo.clusters.values()
                if c["group"] == group and c["region"] == region and c["status"] == "active"
            ]
            if group == "prod":
                # The prod database lives on the cell's own instance: both must have headroom.
                candidates = [
                    (n, min(h, _sql_headroom(repo, repo.clusters[n]["sqlInstances"][0], name)))
                    for n, h in candidates
                ]
            cluster = _pick(candidates)
            if not cluster:
                raise CapacityRequest("cell", region, group, f"no {group} cell with headroom in {region}")

        entry = {"cluster": cluster}
        if group == "prod":
            c = repo.clusters[cluster]
            entry["sqlInstance"] = c["sqlInstances"][0]
            entry["drCluster"] = c["drCluster"]["name"]
        else:
            entry["sqlInstance"] = nonprod_sql
        result[group] = entry
    return result


def _sql_headroom(repo: Repo, sql_name: str, exclude: str) -> int:
    s = repo.sql.get(sql_name)
    if not s or s["status"] != "active":
        return 0
    return s["capacity"]["maxCustomers"] - _assigned(repo, sql=sql_name, exclude=exclude)


# --------------------------------------------------------------------------- write-back


def render_block(placement: dict) -> str:
    lines = [
        "  placement:                           # written back by the placement job, never hand-edited",
        "    # keyed by environment group: dev and stage are separate environments in the devstage cell",
    ]
    if placement.get("dedicated"):
        lines.append("    dedicated: true")
        return "\n".join(lines) + "\n"
    for group in GROUPS:
        p = placement[group]
        parts = [f"cluster: {p['cluster']}", f"sqlInstance: {p['sqlInstance']}"]
        if "drCluster" in p:
            parts.append(f"drCluster: {p['drCluster']}")
        lines.append(f"    {group + ':':<9} {{ " + ", ".join(parts) + " }")
    return "\n".join(lines) + "\n"


def write_back(path: Path, placement: dict) -> bool:
    """Replace (or insert) the spec.placement block, keeping comments elsewhere. Returns True if changed."""
    text = path.read_text(encoding="utf-8")
    block = render_block(placement)
    lines = text.splitlines(keepends=True)
    start = next((i for i, l in enumerate(lines) if l.startswith("  placement:")), None)
    if start is not None:
        end = start + 1
        while end < len(lines) and (lines[end].startswith("    ") or not lines[end].strip()):  # includes the comment
            end += 1
        new = "".join(lines[:start]) + block + "".join(lines[end:])
    else:
        anchor = next((i for i, l in enumerate(lines) if l.startswith("  contacts:")), len(lines))
        new = "".join(lines[:anchor]) + block + "".join(lines[anchor:])
    if new != text:
        path.write_text(new, encoding="utf-8", newline="\n")
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", type=Path, default=Path("."))
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument("--customer", action="append")
    target.add_argument("--all", action="store_true")
    ap.add_argument("--write", action="store_true", help="write placement back to customer.yaml")
    ap.add_argument("--request-file", type=Path, help="write capacity/quota requests here as JSON")
    args = ap.parse_args(argv)

    repo = Repo.load(args.repo)
    names = sorted(repo.customers) if args.all else args.customer
    requests, rc = [], 0
    for name in names:
        if name not in repo.customers:
            print(f"ERROR {name}: customers/{name}/customer.yaml not found", file=sys.stderr)
            return 2
        try:
            placement = place(repo, name)
        except PlacementError as e:
            print(f"ERROR {name}: {e}", file=sys.stderr)
            return 2
        except CapacityRequest as e:
            print(f"CAPACITY {name}: {e}", file=sys.stderr)
            requests.append({"customer": name, **e.__dict__})
            rc = 3
            continue
        # Record in memory so later customers in the same run see this placement.
        repo.customers[name].setdefault("spec", {})["placement"] = placement
        print(f"{name}: {json.dumps(placement)}")
        if args.write:
            changed = write_back(args.repo / "customers" / name / "customer.yaml", placement)
            print(f"  {'updated' if changed else 'unchanged'} customers/{name}/customer.yaml")
    if args.request_file and requests:
        args.request_file.write_text(json.dumps(requests, indent=2), encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
