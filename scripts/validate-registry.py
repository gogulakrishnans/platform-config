#!/usr/bin/env python3
"""Validate the Git registry: catalog, customers and inventory (product-change and customer-PR validator).

Schema checks (products/_schema, customers/_schema) plus the cross-file composition rules of
architecture §6 that a JSON Schema cannot express:

  CAT001  metadata.name matches the directory; short codes are unique
  CAT002  supported releases contain `latest`; oldestCompatible is a supported-or-older release
  CAT003  Pub/Sub: subscriptions only on Cloud Run products, MIG products neither publish nor
          subscribe, every subscription names an existing publisher topic
  CAT004  persistent volumes only on GKE products
  CAT005  dependencies exist and are acyclic
  CUS001  metadata.name matches the directory in all three customer files
  CUS002  primary region exists and is active; placement (if present) is in that region and
          points at cells and SQL instances of the right group
  CUS003  every enabled product exists; version pins are in the support window; variants only
          with variantImages; no pre-releases in prod
  CUS004  dependencies and Pub/Sub publishers are enabled for the same customer
  CUS005  promote-up needs every enabled product to support config export
  CUS006  every prod pin has been promoted (products/<product>/releases.yaml: digest or MIG image)

Usage: python scripts/validate-registry.py [--repo .]      exit 1 on findings
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
GROUP_OF_ENV = {"dev": "devstage", "stage": "devstage", "uat": "uat", "prod": "prod"}
VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")


def read(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def minor(v: str) -> tuple[int, int]:
    a, b = v.split(".")[:2]
    return int(a), int(b)


class Validator:
    def __init__(self, root: Path):
        self.root = root
        self.findings: list[str] = []
        self.schemas = {
            name: Draft202012Validator(json.loads((root / path).read_text(encoding="utf-8")))
            for name, path in {
                "product": "products/_schema/product.schema.json",
                "customer": "customers/_schema/customer.schema.json",
                "products": "customers/_schema/products.schema.json",
                "data-sharing": "customers/_schema/data-sharing.schema.json",
            }.items()
        }

    def add(self, rule: str, where: str, msg: str) -> None:
        self.findings.append(f"{rule} {where}: {msg}")

    def schema(self, kind: str, where: str, doc: dict) -> bool:
        errors = sorted(self.schemas[kind].iter_errors(doc), key=lambda e: list(e.path))
        for e in errors:
            path = "/".join(str(p) for p in e.path) or "(root)"
            self.add("SCHEMA", where, f"{path}: {e.message}")
        return not errors

    # ----------------------------------------------------------------- catalog
    def catalog(self) -> dict[str, dict] | None:
        products = {}
        for d in sorted((self.root / "products").iterdir()):
            if not d.is_dir() or d.name.startswith("_"):
                continue
            where = f"products/{d.name}/product.yaml"
            if not (d / "product.yaml").exists():
                self.add("CAT001", where, "missing")
                continue
            doc = read(d / "product.yaml")
            if not self.schema("product", where, doc):
                continue
            if doc["metadata"]["name"] != d.name:
                self.add("CAT001", where, f"metadata.name {doc['metadata']['name']!r} != directory {d.name!r}")
            products[d.name] = doc["spec"]
        if any(f.startswith("SCHEMA") for f in self.findings):
            return None  # cross-file rules would only report follow-on errors

        shorts: dict[str, str] = {}
        for name, p in products.items():
            where = f"products/{name}"
            if p["shortCode"] in shorts:
                self.add("CAT001", where, f"shortCode {p['shortCode']!r} already used by {shorts[p['shortCode']]}")
            shorts[p["shortCode"]] = name
            rel = p["releases"]
            if rel["latest"] not in rel["supported"]:
                self.add("CAT002", where, f"latest {rel['latest']} is not in supported {rel['supported']}")
            if minor(rel["schemaCompatibility"]["oldestCompatible"]) > max(minor(v) for v in rel["supported"]):
                self.add("CAT002", where, "oldestCompatible is newer than every supported release")
            for env, s in p["sizing"].items():
                lo, hi = (s["replicas"]["min"], s["replicas"]["max"]) if "replicas" in s else \
                         (s.get("minInstances", s.get("minReplicas")), s.get("maxInstances", s.get("maxReplicas")))
                if lo > hi:
                    self.add("CAT002", where, f"sizing.{env}: min {lo} > max {hi}")
            if p["persistentVolume"]["required"] and p["runtime"]["type"] != "gke":
                self.add("CAT004", where, "persistent volumes are allowed only for GKE products")

        published = {f"{p['shortCode']}-{t}" for p in products.values() for t in p["data"]["pubsub"].get("publish", [])}
        for name, p in products.items():
            ps, rt = p["data"]["pubsub"], p["runtime"]["type"]
            if rt == "mig" and (ps.get("publish") or ps.get("subscribe")):
                self.add("CAT003", f"products/{name}", "MIG products neither publish nor subscribe")
            if ps.get("subscribe") and rt != "cloud-run":
                self.add("CAT003", f"products/{name}", "only Cloud Run products may subscribe")
            for s in ps.get("subscribe", []):
                if s not in published:
                    self.add("CAT003", f"products/{name}", f"subscription {s!r} has no publisher in the catalog")

        for name, p in products.items():
            for dep in p["dependencies"]["required"]:
                if dep not in products:
                    self.add("CAT005", f"products/{name}", f"dependency {dep!r} is not in the catalog")
        # cycle check (DFS)
        state: dict[str, int] = {}

        def visit(n: str, stack: list[str]) -> None:
            state[n] = 1
            for dep in products.get(n, {}).get("dependencies", {}).get("required", []):
                if state.get(dep) == 1:
                    self.add("CAT005", f"products/{n}", "dependency cycle " + " -> ".join(stack + [n, dep]))
                elif dep in products and not state.get(dep):
                    visit(dep, stack + [n])
            state[n] = 2

        for n in products:
            if not state.get(n):
                visit(n, [])
        return products

    # ----------------------------------------------------------------- customers
    def customers(self, products: dict[str, dict]) -> None:
        inv = self.root / "inventory"
        regions = {r["name"]: r for r in read(inv / "regions.yaml")["regions"]}
        clusters = {d["name"]: d for d in (read(p) for p in (inv / "clusters").glob("*.yaml"))}
        sqls = {d["name"]: d for d in (read(p) for p in (inv / "sql").glob("*.yaml"))}
        by_publish = {f"{p['shortCode']}-{t}": n for n, p in products.items() for t in p["data"]["pubsub"].get("publish", [])}

        for d in sorted((self.root / "customers").iterdir()):
            if not d.is_dir() or d.name.startswith("_"):
                continue
            c = d.name
            docs = {}
            for kind, fname in (("customer", "customer.yaml"), ("products", "products.yaml"), ("data-sharing", "data-sharing.yaml")):
                where = f"customers/{c}/{fname}"
                if not (d / fname).exists():
                    self.add("CUS001", where, "missing")
                    continue
                doc = read(d / fname)
                if self.schema(kind, where, doc):
                    docs[kind] = doc
                    if doc["metadata"]["name"] != c:
                        self.add("CUS001", where, f"metadata.name {doc['metadata']['name']!r} != directory {c!r}")
            if len(docs) < 3:
                continue
            spec = docs["customer"]["spec"]
            selected = docs["products"]["spec"]["products"]
            where = f"customers/{c}"

            region = spec["region"]["primary"]
            if region not in regions or regions[region].get("status") != "active":
                self.add("CUS002", where, f"region {region!r} is not an active region in inventory/regions.yaml")
            for group, cell in (spec.get("placement") or {}).items():
                if group == "dedicated":
                    continue
                cl, sq = clusters.get(cell["cluster"]), sqls.get(cell["sqlInstance"])
                if not cl or cl.get("group") != group or cl.get("region") != region:
                    self.add("CUS002", where, f"placement.{group}.cluster {cell['cluster']!r} is not a {group} cell in {region}")
                side = "prod" if group == "prod" else "nonprod"
                if not sq or sq.get("side") != side or sq.get("region") != region:
                    self.add("CUS002", where, f"placement.{group}.sqlInstance {cell['sqlInstance']!r} is not a {side} instance in {region}")
                if group == "prod" and cl and (cl.get("drCluster") or {}).get("name") != cell.get("drCluster"):
                    self.add("CUS002", where, f"placement.prod.drCluster must be {(cl.get('drCluster') or {}).get('name')!r}")

            variants = bool((spec.get("options") or {}).get("variantImages"))
            for pname, sel in selected.items():
                if pname not in products:
                    self.add("CUS003", where, f"product {pname!r} is not in the catalog")
                    continue
                p = products[pname]
                for env, pin in sel["versions"].items():
                    m = VERSION.match(pin)
                    if f"{m.group(1)}.{m.group(2)}" not in p["releases"]["supported"]:
                        self.add("CUS003", where, f"{pname}.{env} {pin} is outside the support window {p['releases']['supported']}")
                    pre = m.group(4) or ""
                    if pre.startswith(f"{c}."):
                        if not variants:
                            self.add("CUS003", where, f"{pname}.{env} {pin} is a variant image but variantImages is off")
                    elif pre and env == "prod":
                        self.add("CUS003", where, f"{pname}.prod {pin}: pre-releases are not allowed in prod")
                if sel.get("decommission"):
                    continue
                for dep in p["dependencies"]["required"]:
                    if dep not in selected or selected[dep].get("decommission"):
                        self.add("CUS004", where, f"{pname} requires {dep}, which is not enabled")
                for s in p["data"]["pubsub"].get("subscribe", []):
                    pub = by_publish.get(s)
                    if pub and (pub not in selected or selected[pub].get("decommission")):
                        self.add("CUS004", where, f"{pname} subscribes to {s!r} but its publisher {pub} is not enabled")

            for pname, sel in selected.items():
                if pname in products and not sel.get("decommission"):
                    rel = self.root / "products" / pname / "releases.yaml"
                    promoted = (read(rel).get("promoted") or {}) if rel.exists() else {}
                    pin = sel["versions"]["prod"]
                    ref = str(promoted.get(pin, ""))
                    ok = ref.startswith("projects/") if products[pname]["runtime"]["type"] == "mig" else                         re.fullmatch(r"sha256:[a-f0-9]{64}", ref) is not None
                    if not ok:
                        self.add("CUS006", where, f"{pname} prod pin {pin} has not been promoted (products/{pname}/releases.yaml)")

            if docs["data-sharing"]["spec"]["promoteUp"]["enabled"]:
                no_export = sorted(n for n in selected if n in products and not products[n]["supportsExport"])
                if no_export:
                    self.add("CUS005", where, f"promote-up is enabled but {no_export} do not support config export")

    def run(self) -> list[str]:
        products = self.catalog()
        if products is None:
            self.findings.append("SKIP cross-file rules: fix the catalog schema errors first")
        else:
            self.customers(products)
        return self.findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path, default=ROOT)
    args = ap.parse_args(argv)
    findings = Validator(args.repo.resolve()).run()
    for f in findings:
        print(f)
    print(f"{len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
