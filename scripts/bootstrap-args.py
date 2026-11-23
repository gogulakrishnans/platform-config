#!/usr/bin/env python3
"""Arguments for running the database bootstrap job for one customer environment.

The apply pipeline runs it right after an L3 environment state (architecture §17): Terraform creates
the database and the IAM login through the Admin API; the job revokes PUBLIC, grants CONNECT to the
login and creates the product schemas. Terraform never connects to the database.

Usage: python scripts/bootstrap-args.py --customer acme-corp --env uat
Prints JSON: {"project", "region", "job", "args": [...]}; the workflow runs
    gcloud run jobs execute <job> --project <project> --region <region> --wait --args=<args joined by ,>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
GROUP_OF_ENV = {"dev": "devstage", "stage": "devstage", "uat": "uat", "prod": "prod"}


def read(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def bootstrap_args(root: Path, customer: str, env: str) -> dict:
    plat = read(root / "inventory/platform.yaml")
    group = GROUP_OF_ENV[env]
    gcfg = plat["groups"][group]
    pid = {k: v["id"] for k, v in plat["projects"].items()}
    cust = read(root / "customers" / customer / "customer.yaml")["spec"]
    sql_name = cust["placement"][group]["sqlInstance"]
    sql = read(root / "inventory/sql" / f"{sql_name}.yaml")
    selected = read(root / "customers" / customer / "products.yaml")["spec"]["products"]
    schemas = []
    for p, sel in sorted(selected.items()):
        spec = read(root / "products" / p / "product.yaml")["spec"]
        if spec["data"]["cloudSql"]["required"] and not sel.get("decommission"):
            schemas.append(spec["shortCode"].replace("-", "_"))
    data_project = pid[gcfg["dataProject"]]
    return {
        "project": data_project,
        "region": sql["region"],
        "job": f"db-bootstrap-{sql['region']}",
        "args": [
            f"--instance={pid[sql['project']]}:{sql['region']}:{sql_name}",
            f"--database={customer.replace('-', '_')}_{env}",
            f"--login={customer}-{env}@{pid[gcfg['computeProject']]}.iam",
            f"--schemas={','.join(sorted(schemas))}",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path, default=ROOT)
    ap.add_argument("--customer", required=True)
    ap.add_argument("--env", required=True, choices=sorted(GROUP_OF_ENV))
    a = ap.parse_args(argv)
    print(json.dumps(bootstrap_args(a.repo.resolve(), a.customer, a.env)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
