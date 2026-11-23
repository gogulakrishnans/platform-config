"""Isolation test cases (architecture §10): for sampled customer pairs (A, B) in one environment,
customer A's identity must be DENIED on every one of customer B's containers.

Cases are derived from the registry, so a new product, bucket or topic is covered automatically.
"""
from __future__ import annotations

import itertools
import random
from dataclasses import dataclass
from pathlib import Path

import yaml

GROUP_OF_ENV = {"dev": "devstage", "stage": "devstage", "uat": "uat", "prod": "prod"}
KINDS = ("database", "schema", "dataset", "bucket", "topic", "namespace", "key")


@dataclass(frozen=True)
class Case:
    env: str
    actor: str          # customer whose identity makes the call
    target: str         # customer who owns the resource
    kind: str
    resource: str
    action: str         # what is attempted (must be denied)

    @property
    def id(self) -> str:
        return f"{self.env}:{self.actor}->{self.target}:{self.kind}:{self.resource}"


def _read(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def build_cases(root: Path, env: str, sample: int | None = None, seed: int | None = None) -> list[Case]:
    plat = _read(root / "inventory/platform.yaml")
    group = GROUP_OF_ENV[env]
    g = plat["groups"][group]
    pid = {k: v["id"] for k, v in plat["projects"].items()}
    prefix = plat["bucketPrefix"]
    catalog = {d.name: _read(d / "product.yaml")["spec"] for d in (root / "products").iterdir()
               if (d / "product.yaml").exists()}
    customers = {}
    for d in sorted((root / "customers").iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        spec = _read(d / "customer.yaml")["spec"]
        if group not in (spec.get("placement") or {}):
            continue
        customers[d.name] = {
            "spec": spec,
            "products": {n: s for n, s in _read(d / "products.yaml")["spec"]["products"].items() if not s.get("decommission")},
        }

    pairs = list(itertools.permutations(sorted(customers), 2))
    if sample is not None and len(pairs) > sample:
        pairs = random.Random(seed).sample(pairs, sample)

    cases: list[Case] = []
    for actor, target in pairs:
        t = customers[target]
        t_ = target.replace("-", "_")
        region = t["spec"]["region"]["primary"]
        sql = t["spec"]["placement"][group]["sqlInstance"]
        db = f"{t_}_{env}"
        cases.append(Case(env, actor, target, "database", f"{pid[g['dataProject']]}:{region}:{sql}/{db}", "connect"))
        cases.append(Case(env, actor, target, "namespace", f"{t['spec']['placement'][group]['cluster']}/{target}-{env}", "list pods"))
        cases.append(Case(env, actor, target, "key",
                          f"projects/{pid[g['securityProject']]}/locations/{region}/keyRings/kr-{target}-{group}/cryptoKeys/{env}-app",
                          "encrypt"))
        for pname in sorted(t["products"]):
            spec = catalog[pname]
            short = spec["shortCode"]
            if spec["data"]["cloudSql"]["required"]:
                cases.append(Case(env, actor, target, "schema", f"{db}.{short.replace('-', '_')}", "select"))
            if spec["data"]["storage"]["required"]:
                cases.append(Case(env, actor, target, "bucket", f"{prefix}-{target}-{short}-{env}", "list objects"))
            if spec["data"]["bigQuery"]["required"]:
                cases.append(Case(env, actor, target, "dataset", f"{pid[g['dataProject']]}.{t_}_{short.replace('-', '_')}_{env}", "query"))
            for topic in spec["data"]["pubsub"].get("publish", []):
                cases.append(Case(env, actor, target, "topic",
                                  f"projects/{pid[g['dataProject']]}/topics/{target}-{short}-{env}-{topic}", "publish"))
    return cases


def actor_identity(root: Path, customer: str, env: str) -> str:
    plat = _read(root / "inventory/platform.yaml")
    compute = plat["projects"][plat["groups"][GROUP_OF_ENV[env]]["computeProject"]]["id"]
    return f"{customer}-{env}@{compute}.iam.gserviceaccount.com"
