"""Non-prod seed import job (architecture §9 step 7, clarification C3). Skeleton: the plan is
complete and unit-tested; the API calls are proven in a real project.

Runs as a Cloud Run job in data-nonprod with the non-prod `seed-import` identity, started by an
Eventarc trigger when the prod side writes a manifest to the customer's seed bucket
(`gs://<prefix>-<customer>-seed/manifests/<run>.json`). It pulls; no prod identity ever writes
into non-prod.

  validate manifest -> drop + recreate the target database -> import the dump AS the target login
  -> rerun the database bootstrap job -> load BigQuery Parquet -> copy GCS objects -> record the run
"""
from __future__ import annotations

from main import GROUP_OF_ENV, NONPROD_TARGETS, SeedDownError, Step


def plan_import(cfg: dict, manifest: dict) -> list[Step]:
    customer, target = manifest["customer"], manifest["target"]
    if target not in NONPROD_TARGETS:
        raise SeedDownError(f"refusing to import into {target!r}")
    if customer not in cfg["customers"]:
        raise SeedDownError(f"unknown customer {customer!r}")
    c = cfg["customers"][customer]
    if target not in c["dataSharing"]["seedDown"].get("targets", []):
        raise SeedDownError(f"{customer}: {target} is not a seed-down target")
    group = GROUP_OF_ENV[target]
    p = cfg["projects"]
    compute = p[cfg["groups"][group]["computeProject"]]
    expected_login = f"{customer}-{target}@{compute}.iam"
    if manifest["targetLogin"] != expected_login:
        raise SeedDownError(f"dump was role-mapped to {manifest['targetLogin']}, expected {expected_login}")
    sql_instance = c["placement"][group]["sqlInstance"]
    data_nonprod = p["data-nonprod"]
    database = f"{customer.replace('-', '_')}_{target}"
    run = manifest["runId"]
    seed = f"gs://{cfg['bucketPrefix']}-{customer}-seed"
    region = cfg["sql"][sql_instance]["region"]

    steps = [
        # No --clean for plain imports (V10): drop and recreate the database instead.
        Step("drop-database", "sqladmin", {"method": "databases.delete", "project": data_nonprod,
                                           "instance": sql_instance, "database": database}),
        Step("create-database", "sqladmin", {"method": "databases.insert", "project": data_nonprod,
                                             "instance": sql_instance, "body": {"name": database}}),
        Step("import-dump", "sqladmin", {"method": "instances.import", "project": data_nonprod, "instance": sql_instance,
                                         "body": {"importContext": {"fileType": "SQL", "database": database,
                                                                    "importUser": expected_login,
                                                                    "uri": manifest["sqlDump"]}}}),
        # Revokes PUBLIC again, grants CONNECT to the env login, creates any missing product schemas.
        Step("bootstrap-database", "run", {"method": "jobs.run", "project": data_nonprod, "region": region,
                                           "job": f"db-bootstrap-{region}", "args": [
                                               f"--instance={data_nonprod}:{region}:{sql_instance}",
                                               f"--database={database}",
                                               f"--login={expected_login}",
                                               f"--schemas={','.join(manifest.get('schemas', []))}"]}),
    ]
    for pname, sel in sorted(c["products"].items()):
        spec = cfg["products"][pname]
        short, short_ = spec["shortCode"], spec["shortCode"].replace("-", "_")
        if sel.get("decommission"):
            continue
        if spec["data"]["bigQuery"]["required"]:
            steps.append(Step(f"bigquery-load-{short}", "bigquery", {
                "project": data_nonprod, "location": region, "writeDisposition": "WRITE_TRUNCATE",
                "destination": f"{data_nonprod}.{customer.replace('-', '_')}_{short_}_{target}.events",
                "sourceUris": [f"{seed}/bigquery/{run}/events/*.parquet"], "sourceFormat": "PARQUET"}))
        if spec["data"]["storage"]["required"]:
            steps.append(Step(f"gcs-copy-{short}", "storagetransfer", {
                "project": data_nonprod, "source": f"{seed}/gcs/{run}/{short}/",
                "sink": f"gs://{cfg['bucketPrefix']}-{customer}-{short}-{target}/",
                "deleteObjectsUniqueInSink": True}))
    steps.append(Step("record-run", "storage", {"uri": f"{seed}/imports/{run}-{target}.json",
                                                "body": {"runId": run, "database": database, "status": "imported"}}))
    return steps
