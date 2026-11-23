"""Offline tests for the promote-up validation and plan."""
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
spec = importlib.util.spec_from_file_location("promote_up", HERE.parent / "promote_up.py")
pu = importlib.util.module_from_spec(spec)
sys.modules["promote_up"] = pu
spec.loader.exec_module(pu)


def test_uat_to_prod_plan():
    p = pu.plan(REPO, "acme-corp", "payment-api", "uat", "prod", "r1")
    assert p["from"]["version"] == "2.5.1" and p["to"]["version"] == "2.5.0"
    assert p["from"]["runnerPool"] == "uat" and p["to"]["runnerPool"] == "prod"
    assert p["to"]["githubEnvironment"] == "promote-prod"
    assert p["staging"] == "gs://pfx-acme-corp-payment-uat/promote/payment-api/r1/uat-2.5.1.tar.gz"
    assert p["package"] == "gs://pfx-acme-corp-shared/promote/payment-api/r1/uat-2.5.1.tar.gz"
    assert p["publisher"] == "promoter@pfx-platform-prod.iam.gserviceaccount.com"
    assert p["to"]["importUrl"] == "https://acme-corp.platform.example/v1/payments/admin/config:import"
    assert p["approvals"] == ["customer-success"]


def test_dev_to_stage_uses_private_hosts():
    p = pu.plan(REPO, "acme-corp", "payment-api", "dev", "stage", "r")
    assert p["from"]["exportUrl"].startswith("https://acme-corp.dev.platform.internal/")


@pytest.mark.parametrize("customer,product,src,dst,error", [
    ("acme-corp", "payment-api", "dev", "uat", "exactly one step up"),
    ("acme-corp", "payment-api", "prod", "uat", "exactly one step up"),
    ("acme-corp", "legacy-billing", "uat", "prod", "not enabled"),
    ("beta-industries", "payment-api", "uat", "prod", "disabled"),
    ("nobody", "payment-api", "uat", "prod", "unknown customer"),
])
def test_rejected(customer, product, src, dst, error):
    with pytest.raises(pu.PromoteError, match=error):
        pu.plan(REPO, customer, product, src, dst, "r")


def test_export_support_required(tmp_path):
    for d in ("customers", "products", "inventory"):
        shutil.copytree(REPO / d, tmp_path / d)
    f = tmp_path / "products/payment-api/product.yaml"
    doc = yaml.safe_load(f.read_text())
    doc["spec"]["supportsExport"] = False
    f.write_text(yaml.safe_dump(doc))
    with pytest.raises(pu.PromoteError, match="does not support config export"):
        pu.plan(tmp_path, "acme-corp", "payment-api", "uat", "prod", "r")


def test_cli_exit_codes(capsys):
    assert pu.main(["--customer", "acme-corp", "--product", "payment-api", "--from", "stage", "--to", "uat"]) == 0
    assert pu.main(["--customer", "acme-corp", "--product", "payment-api", "--from", "uat", "--to", "stage"]) == 2
