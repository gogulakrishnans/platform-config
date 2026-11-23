"""Offline tests for the seed-down plan, guards, templates and the non-prod import plan."""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import main as sd  # noqa: E402
import import_job  # noqa: E402

REPO = HERE.parents[2]


@pytest.fixture(scope="module")
def cfg():
    return sd.build_config(REPO)


def names(steps):
    return [s.name for s in steps]


def test_plan_for_acme_uat(cfg):
    steps = sd.plan(cfg, "acme-corp", "uat", "r1", salt="s")
    assert names(steps) == [
        "export-prod-database", "create-scratch-instance", "import-into-scratch",
        "sanitize-payment", "sanitize-reporting", "verify-payment", "verify-reporting",
        "role-mapping", "export-sanitized", "delete-scratch-instance",
        "gcs-payment", "bigquery-reporting", "gcs-reporting", "publish-manifest",
    ]
    exp = steps[0].params
    assert exp["project"] == "pfx-data-prod" and exp["instance"] == "sql-prod-us-east1-01"
    assert exp["body"]["exportContext"]["uri"] == "gs://pfx-seed-work-us-east1/acme-corp/r1/prod.sql.gz"
    scratch = steps[1].params["body"]
    assert scratch["region"] == "us-east1" and scratch["settings"]["ipConfiguration"]["ipv4Enabled"] is False
    assert scratch["diskEncryptionConfiguration"]["kmsKeyName"].endswith("/keyRings/kr-platform-us-east1/cryptoKeys/sql")
    assert steps[8].params["body"]["exportContext"]["uri"] == "gs://pfx-acme-corp-seed/sql/r1/uat.sql.gz"


def test_everything_leaving_prod_goes_to_the_seed_bucket(cfg):
    for s in sd.plan(cfg, "acme-corp", "stage", "r2", salt="s"):
        if s.name in ("export-sanitized", "publish-manifest"):
            target = s.params.get("uri") or s.params["body"]["exportContext"]["uri"]
            assert target.startswith("gs://pfx-acme-corp-seed/")
        if s.api == "storagetransfer":
            assert s.params["sink"].startswith("gs://pfx-acme-corp-seed/") and s.params["excludePrefixes"]


def test_templates_are_fully_rendered(cfg):
    steps = sd.plan(cfg, "acme-corp", "uat", "r3", salt="abc123")
    sanitize = next(s for s in steps if s.name == "sanitize-payment").params["sql"]
    assert '"payment".users' in sanitize and "abc123" in sanitize and "{{" not in sanitize
    roles = next(s for s in steps if s.name == "role-mapping").params["sql"]
    assert 'REASSIGN OWNED BY "acme-corp-prod@pfx-compute-prod.iam" TO "acme-corp-uat@pfx-compute-uat.iam"' in roles
    assert '"payment-api": "2.5.0"' in roles
    bq = next(s for s in steps if s.name == "bigquery-reporting").params["sql"]
    assert "pfx-data-prod.acme_corp_reporting_prod.events" in bq and "gs://pfx-acme-corp-seed/bigquery/r3/" in bq


def test_salt_is_random_per_run(cfg):
    a = next(s for s in sd.plan(cfg, "acme-corp", "uat", "r") if s.name == "sanitize-payment").params["sql"]
    b = next(s for s in sd.plan(cfg, "acme-corp", "uat", "r") if s.name == "sanitize-payment").params["sql"]
    assert a != b


@pytest.mark.parametrize("customer,target,error", [
    ("acme-corp", "prod", "only targets"),
    ("acme-corp", "dev", "not a seed-down target"),       # acme seeds uat and stage only
    ("beta-industries", "uat", "not a seed-down target"),  # beta has no targets
    ("nobody", "uat", "unknown customer"),
])
def test_guards(cfg, customer, target, error):
    with pytest.raises(sd.SeedDownError, match=error):
        sd.plan(cfg, customer, target, "r")


def test_version_guard(cfg):
    import copy
    c = copy.deepcopy(cfg)
    c["customers"]["acme-corp"]["products"]["payment-api"]["versions"]["uat"] = "2.3.9"   # oldestCompatible 2.4
    with pytest.raises(sd.SeedDownError, match="oldest release compatible"):
        sd.plan(c, "acme-corp", "uat", "r")


def test_render_rejects_missing_placeholders():
    with pytest.raises(sd.SeedDownError, match="unrendered"):
        sd.render("SELECT {{a}}, {{b}}", a="1")


def test_import_plan(cfg):
    manifest = {"runId": "r1", "customer": "acme-corp", "target": "uat", "targetLogin": "acme-corp-uat@pfx-compute-uat.iam",
                "sqlDump": "gs://pfx-acme-corp-seed/sql/r1/uat.sql.gz", "schemas": ["payment", "reporting"]}
    steps = import_job.plan_import(cfg, manifest)
    assert steps[3].params["args"] == ["--instance=pfx-data-nonprod:us-east1:sql-nonprod-us-east1-01", "--database=acme_corp_uat",
                                       "--login=acme-corp-uat@pfx-compute-uat.iam", "--schemas=payment,reporting"]
    assert names(steps)[:4] == ["drop-database", "create-database", "import-dump", "bootstrap-database"]
    imp = steps[2].params
    assert imp["instance"] == "sql-nonprod-us-east1-01" and imp["project"] == "pfx-data-nonprod"
    assert imp["body"]["importContext"]["importUser"] == "acme-corp-uat@pfx-compute-uat.iam"
    assert imp["body"]["importContext"]["database"] == "acme_corp_uat"
    load = next(s for s in steps if s.name == "bigquery-load-reporting").params
    assert load["destination"] == "pfx-data-nonprod.acme_corp_reporting_uat.events"


def test_import_refuses_prod_and_wrong_login(cfg):
    m = {"runId": "r", "customer": "acme-corp", "target": "prod", "targetLogin": "x", "sqlDump": "gs://x"}
    with pytest.raises(sd.SeedDownError, match="refusing"):
        import_job.plan_import(cfg, m)
    m.update(target="uat", targetLogin="acme-corp-prod@pfx-compute-prod.iam")
    with pytest.raises(sd.SeedDownError, match="role-mapped"):
        import_job.plan_import(cfg, m)
