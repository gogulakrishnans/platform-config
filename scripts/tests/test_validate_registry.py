"""Tests for scripts/validate-registry.py against a copy of the real registry."""
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("validate_registry", REPO / "scripts" / "validate-registry.py")
vr = importlib.util.module_from_spec(spec)
sys.modules["validate_registry"] = vr
spec.loader.exec_module(vr)


@pytest.fixture
def repo(tmp_path):
    for d in ("inventory", "customers", "products"):
        shutil.copytree(REPO / d, tmp_path / d)
    return tmp_path


def edit(path, fn):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def rules(root):
    return sorted({f.split()[0] for f in vr.Validator(root).run()})


def test_real_registry_is_valid(repo):
    assert vr.Validator(repo).run() == []


def test_schema_rejects_unknown_key_and_bad_shortcode(repo):
    edit(repo / "products/payment-api/product.yaml", lambda d: d["spec"].update(shortCode="Payment_API", colour="red"))
    assert rules(repo) == ["SCHEMA", "SKIP"]


def test_mig_sizing_shape_is_enforced(repo):
    edit(repo / "products/legacy-billing/product.yaml",
         lambda d: d["spec"]["sizing"].update(prod={"replicas": {"min": 1, "max": 2}, "cpu": "1", "memory": "1Gi"}))
    assert rules(repo) == ["SCHEMA", "SKIP"]


def test_duplicate_short_code(repo):
    edit(repo / "products/document-index/product.yaml", lambda d: d["spec"].update(shortCode="payment"))
    assert "CAT001" in rules(repo)


def test_subscription_rules(repo):
    edit(repo / "products/payment-api/product.yaml", lambda d: d["spec"]["data"]["pubsub"].update(subscribe=["reporting-x"]))
    assert rules(repo) == ["CAT003"]  # GKE subscriber and an unknown publisher topic


def test_mig_cannot_publish(repo):
    edit(repo / "products/legacy-billing/product.yaml", lambda d: d["spec"]["data"]["pubsub"].update(publish=["invoices"]))
    assert rules(repo) == ["CAT003"]


def test_persistent_volume_only_on_gke_and_needs_approval(repo):
    edit(repo / "products/reporting-engine/product.yaml",
         lambda d: d["spec"].update(persistentVolume={"required": True, "size": "10Gi", "approvedBy": "ARB-1"}))
    assert rules(repo) == ["CAT004"]
    edit(repo / "products/reporting-engine/product.yaml", lambda d: d["spec"].update(persistentVolume={"required": True}))
    assert "SCHEMA" in rules(repo)


def test_dependency_cycle(repo):
    edit(repo / "products/payment-api/product.yaml", lambda d: d["spec"]["dependencies"].update(required=["document-index"]))
    assert "CAT005" in rules(repo)


def test_version_outside_window_and_prod_prerelease(repo):
    def pins(d):
        d["spec"]["products"]["payment-api"]["versions"].update(stage="2.1.0", prod="2.5.0-rc.1")
    edit(repo / "customers/acme-corp/products.yaml", pins)
    # the rc pin is also not promoted (CUS006)
    assert len([f for f in vr.Validator(repo).run() if f.startswith("CUS003")]) == 2 and rules(repo) == ["CUS003", "CUS006"]


def test_variant_requires_opt_in(repo):
    edit(repo / "customers/beta-industries/customer.yaml", lambda d: d["spec"]["options"].update(variantImages=False))
    assert rules(repo) == ["CUS003"]


def test_dependency_must_be_enabled(repo):
    edit(repo / "customers/acme-corp/products.yaml", lambda d: d["spec"]["products"]["payment-api"].update(decommission=True))
    # reporting-engine requires payment-api and subscribes to its topic
    assert rules(repo) == ["CUS004"]


def test_promote_up_needs_export_support(repo):
    edit(repo / "customers/beta-industries/data-sharing.yaml", lambda d: d["spec"]["promoteUp"].update(enabled=True))
    assert rules(repo) == ["CUS005"]


def test_placement_must_match_region_and_group(repo):
    edit(repo / "customers/acme-corp/customer.yaml",
         lambda d: d["spec"]["placement"]["uat"].update(cluster="uat-us-central1-01"))
    assert rules(repo) == ["CUS002"]


def test_inactive_region(repo):
    edit(repo / "customers/acme-corp/customer.yaml", lambda d: d["spec"]["region"].update(primary="europe-west1"))
    assert "CUS002" in rules(repo)


def test_new_customer_with_region_only_is_valid(repo):
    d = repo / "customers/gamma-labs"
    d.mkdir()
    (d / "customer.yaml").write_text(
        "apiVersion: platform.example/v1\nkind: CustomerConfig\nmetadata: { name: gamma-labs }\n"
        "spec: { displayName: Gamma Labs, accountId: CUST-000003, region: { primary: us-east1 } }\n")
    (d / "products.yaml").write_text(
        "apiVersion: platform.example/v1\nkind: CustomerProducts\nmetadata: { name: gamma-labs }\n"
        "spec:\n  products:\n    payment-api: { versions: { dev: 2.6.0, stage: 2.6.0, uat: 2.6.0, prod: 2.5.0 } }\n")
    (d / "data-sharing.yaml").write_text(
        "apiVersion: platform.example/v1\nkind: DataSharingPolicy\nmetadata: { name: gamma-labs }\n"
        "spec: { sharedReference: false, promoteUp: { enabled: false }, seedDown: { targets: [] } }\n")
    assert vr.Validator(repo).run() == []


def test_prod_pin_must_be_promoted(repo):
    edit(repo / "customers/acme-corp/products.yaml",
         lambda d: d["spec"]["products"]["reporting-engine"]["versions"].update(prod="1.8.3"))
    assert rules(repo) == ["CUS006"]
    edit(repo / "products/legacy-billing/releases.yaml", lambda d: d["promoted"].pop("3.3.2"))
    assert len([f for f in vr.Validator(repo).run() if f.startswith("CUS006")]) == 2
