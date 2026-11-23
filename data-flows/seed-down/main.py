"""Seed-down orchestrator (architecture §9, clarification C3). Skeleton: planning is complete and
unit-tested; the executor maps each step to one Google API call and is proven in a real project.

Runs as a 2nd-gen Cloud Function in data-prod, triggered by Cloud Scheduler (schedule from
data-sharing.yaml) or on demand, with {"customer": "acme-corp", "target": "uat"}. Its config is a
JSON snapshot of the registry built by CI at deploy time (`build_config`), so the function never
reads Git at run time.

Flow for one customer and one target environment:
  guard -> export prod DB -> scratch instance -> import -> sanitize -> verify -> role mapping
  -> export to the seed bucket -> delete scratch -> BigQuery anonymized export -> GCS transfer
The non-prod import job (data-nonprod) picks the dump up from the seed bucket (import_job.py).
"""
from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
BQ_DIR = Path(__file__).resolve().parent.parent / "bigquery"
VERSION = re.compile(r"^(\d+)\.(\d+)\.\d+")
NONPROD_TARGETS = ("dev", "stage", "uat")
GROUP_OF_ENV = {"dev": "devstage", "stage": "devstage", "uat": "uat"}
EXCLUDED_GCS_PREFIXES = ["tmp/", "exports/", "secrets/"]


class SeedDownError(Exception):
    """The run must not start (guard) or must stop (verification)."""


@dataclass
class Step:
    name: str
    api: str                       # sqladmin | sql | bigquery | storagetransfer | storage
    params: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------- config snapshot

def build_config(repo_root: Path) -> dict:
    """Registry snapshot for the function (run by CI at deploy time, not at run time)."""
    import yaml

    def read(p: Path) -> dict:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    plat = read(repo_root / "inventory/platform.yaml")
    products = {d.name: read(d / "product.yaml")["spec"] for d in (repo_root / "products").iterdir()
                if d.is_dir() and not d.name.startswith("_") and (d / "product.yaml").exists()}
    sql = {d["name"]: d for d in (read(p) for p in (repo_root / "inventory/sql").glob("*.yaml"))}
    customers = {}
    for d in (repo_root / "customers").iterdir():
        if not d.is_dir() or d.name.startswith("_"):
            continue
        cust = read(d / "customer.yaml")["spec"]
        customers[d.name] = {
            "region": cust["region"]["primary"],
            "placement": cust.get("placement", {}),
            "dataSharing": read(d / "data-sharing.yaml")["spec"],
            "products": read(d / "products.yaml")["spec"]["products"],
        }
    return {
        "bucketPrefix": plat["bucketPrefix"],
        "projects": {k: v["id"] for k, v in plat["projects"].items()},
        "groups": plat["groups"],
        "sql": {k: {"project": v["project"], "region": v["region"]} for k, v in sql.items()},
        "products": {k: {"shortCode": p["shortCode"], "data": p["data"],
                         "oldestCompatible": p["releases"]["schemaCompatibility"]["oldestCompatible"]}
                     for k, p in products.items()},
        "customers": customers,
    }


# ----------------------------------------------------------------------------- guards

def minor(v: str) -> tuple[int, int]:
    m = VERSION.match(v)
    if not m:
        raise SeedDownError(f"unparseable version {v!r}")
    return int(m.group(1)), int(m.group(2))


def check_versions(cfg: dict, customer: str, target: str) -> dict:
    """Version-compatibility guard: the target's app version must be able to run on the prod
    schema, i.e. be at least the catalog's oldestCompatible release. Returns the source versions."""
    source_versions = {}
    for pname, sel in cfg["customers"][customer]["products"].items():
        if sel.get("decommission"):
            continue
        prod_v, target_v = sel["versions"]["prod"], sel["versions"][target]
        oldest = tuple(int(x) for x in cfg["products"][pname]["oldestCompatible"].split("."))
        if minor(target_v) < oldest:
            raise SeedDownError(
                f"{customer}/{pname}: {target} runs {target_v}, older than {'.'.join(map(str, oldest))}, "
                f"the oldest release compatible with the prod schema ({prod_v})")
        source_versions[pname] = prod_v
    return source_versions


def guard(cfg: dict, customer: str, target: str) -> None:
    if customer not in cfg["customers"]:
        raise SeedDownError(f"unknown customer {customer!r}")
    if target not in NONPROD_TARGETS:
        raise SeedDownError(f"seed down only targets {NONPROD_TARGETS}, not {target!r}")
    ds = cfg["customers"][customer]["dataSharing"]["seedDown"]
    if target not in ds.get("targets", []):
        raise SeedDownError(f"{customer}: {target} is not a seed-down target in data-sharing.yaml")
    if ds.get("mode", "sanitized") != "sanitized":
        raise SeedDownError("only sanitized seed down is allowed")


# ----------------------------------------------------------------------------- templates

def render(template: str, **values: str) -> str:
    out = template
    for k, v in values.items():
        out = out.replace("{{" + k + "}}", str(v))
    left = re.findall(r"\{\{(\w+)\}\}", out)
    if left:
        raise SeedDownError(f"unrendered placeholders {sorted(set(left))}")
    return out


# ----------------------------------------------------------------------------- plan

def plan(cfg: dict, customer: str, target: str, run_id: str, salt: str | None = None) -> list[Step]:
    guard(cfg, customer, target)
    source_versions = check_versions(cfg, customer, target)
    c = cfg["customers"][customer]
    c_ = customer.replace("-", "_")
    prefix = cfg["bucketPrefix"]
    p = cfg["projects"]
    prod_sql = c["placement"]["prod"]["sqlInstance"]
    region = cfg["sql"][prod_sql]["region"]
    data_prod, exchange = p["data-prod"], p["data-exchange"]
    target_compute = p[cfg["groups"][GROUP_OF_ENV[target]]["computeProject"]]
    source_login = f"{customer}-prod@{p['compute-prod']}.iam"
    target_login = f"{customer}-{target}@{target_compute}.iam"
    scratch = f"seed-{customer}-{run_id}"[:80]
    work = f"gs://{prefix}-seed-work-{region}/{customer}/{run_id}"   # L2 region-footprint, 2-day lifecycle
    seed = f"gs://{prefix}-{customer}-seed"
    database = f"{c_}_prod"
    salt = salt or secrets.token_hex(16)
    enabled = {n: s for n, s in c["products"].items() if not s.get("decommission")}
    schemas = sorted(cfg["products"][n]["shortCode"].replace("-", "_") for n in enabled
                     if cfg["products"][n]["data"]["cloudSql"]["required"])

    steps = [
        Step("export-prod-database", "sqladmin", {
            "method": "instances.export", "project": data_prod, "instance": prod_sql,
            "body": {"exportContext": {"fileType": "SQL", "databases": [database], "offload": True,
                                       "uri": f"{work}/prod.sql.gz"}}}),
        Step("create-scratch-instance", "sqladmin", {
            "method": "instances.insert", "project": data_prod,
            "body": {"name": scratch, "region": region, "databaseVersion": "POSTGRES_16",
                     "settings": {"tier": "db-custom-2-8192", "edition": "ENTERPRISE",
                                  "ipConfiguration": {"ipv4Enabled": False,
                                                      "privateNetwork": f"projects/{p['net-prod']}/global/networks/vpc-prod"},
                                  "userLabels": {"customer": customer, "environment": "prod", "env-group": "prod",
                                                 "product": "platform", "region-role": "primary",
                                                 "managed-by": "pipeline"},
                                  "deletionProtectionEnabled": False},
                     # same CMEK key as the prod instances in this region (L2 platform keys)
                     "diskEncryptionConfiguration": {"kmsKeyName": f"projects/{p['security-prod']}/locations/{region}"
                                                                   f"/keyRings/kr-platform-{region}/cryptoKeys/sql"}}}),
        Step("import-into-scratch", "sqladmin", {
            "method": "instances.import", "project": data_prod, "instance": scratch,
            "body": {"importContext": {"fileType": "SQL", "database": database, "uri": f"{work}/prod.sql.gz"}}}),
    ]
    sanitize_t = (SQL_DIR / "sanitize.sql.tmpl").read_text(encoding="utf-8")
    verify_t = (SQL_DIR / "verify.sql.tmpl").read_text(encoding="utf-8")
    for s in schemas:
        steps.append(Step(f"sanitize-{s}", "sql", {"instance": scratch, "database": database,
                                                   "sql": render(sanitize_t, schema=s, salt=salt)}))
    for s in schemas:
        steps.append(Step(f"verify-{s}", "sql", {"instance": scratch, "database": database, "expectZero": True,
                                                 "sql": render(verify_t, schema=s)}))
    steps += [
        Step("role-mapping", "sql", {"instance": scratch, "database": database, "sql": render(
            (SQL_DIR / "role-mapping.sql.tmpl").read_text(encoding="utf-8"),
            source_login=source_login, target_login=target_login, database=database,
            run_id=run_id, target_env=target, source_versions=json.dumps(source_versions, sort_keys=True))}),
        Step("export-sanitized", "sqladmin", {
            "method": "instances.export", "project": data_prod, "instance": scratch,
            "body": {"exportContext": {"fileType": "SQL", "databases": [database],
                                       "uri": f"{seed}/sql/{run_id}/{target}.sql.gz"}}}),
        Step("delete-scratch-instance", "sqladmin", {"method": "instances.delete", "project": data_prod, "instance": scratch}),
    ]
    bq_t = (BQ_DIR / "anonymize.sql").read_text(encoding="utf-8")
    for n in sorted(enabled):
        spec = cfg["products"][n]
        short_ = spec["shortCode"].replace("-", "_")
        if spec["data"]["bigQuery"]["required"]:
            steps.append(Step(f"bigquery-{spec['shortCode']}", "bigquery", {
                "project": data_prod, "location": region, "parameters": {"salt": salt},
                "sql": render(bq_t, source=f"{data_prod}.{c_}_{short_}_prod", seed_bucket=f"{prefix}-{customer}-seed",
                              run_id=run_id)}))
        if spec["data"]["storage"]["required"]:
            steps.append(Step(f"gcs-{spec['shortCode']}", "storagetransfer", {
                "project": data_prod,
                "source": f"gs://{prefix}-{customer}-{spec['shortCode']}-prod",
                "sink": f"{seed}/gcs/{run_id}/{spec['shortCode']}/",
                "excludePrefixes": EXCLUDED_GCS_PREFIXES}))
    steps.append(Step("publish-manifest", "storage", {
        "uri": f"{seed}/manifests/{run_id}.json",
        "body": {"runId": run_id, "customer": customer, "target": target, "exchangeProject": exchange,
                 "sqlDump": f"{seed}/sql/{run_id}/{target}.sql.gz", "targetLogin": target_login,
                 "schemas": schemas, "sourceVersions": source_versions}}))
    return steps


# ----------------------------------------------------------------------------- execute (real project)

def execute(steps: list[Step]) -> None:  # pragma: no cover - needs GCP
    """One API call per step, waiting on each long-running operation. A failed verify stops the run
    and leaves the scratch instance for inspection; a cleanup job deletes it after 24 h."""
    from googleapiclient import discovery  # lazy: offline tests never import it

    sqladmin = discovery.build("sqladmin", "v1", cache_discovery=False)
    for step in steps:
        if step.api == "sqladmin":
            m = step.params["method"].split(".")[1]
            call = getattr(sqladmin.instances(), m)
            kwargs = {"project": step.params["project"]}
            if "instance" in step.params:
                kwargs["instance"] = step.params["instance"]
            if "body" in step.params:
                kwargs["body"] = step.params["body"]
            call(**kwargs).execute()           # then poll operations().get until DONE
        elif step.api == "sql":
            _run_sql(step)                     # Cloud SQL Python Connector, IAM login as the platform login
        else:
            raise NotImplementedError(f"{step.api}: wired in the rollout (see data-flows/README.md)")


def _run_sql(step: Step) -> None:  # pragma: no cover - needs GCP
    raise NotImplementedError("connect with cloud-sql-python-connector (google.cloud.sql.connector, IAM auth), run step.params['sql'], "
                              "and fail if expectZero and any violations > 0")


def handler(request):  # pragma: no cover - Cloud Functions entry point
    body = request.get_json(silent=True) or {}
    cfg = json.loads((Path(__file__).parent / "seed-config.json").read_text(encoding="utf-8"))
    run_id = secrets.token_hex(4)
    steps = plan(cfg, body["customer"], body["target"], run_id)
    execute(steps)
    return {"runId": run_id, "steps": [s.name for s in steps]}
