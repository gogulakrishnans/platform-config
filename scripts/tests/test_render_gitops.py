"""Tests for scripts/render-gitops.py against a copy of the real registry."""
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("render_gitops", REPO / "scripts" / "render-gitops.py")
rg = importlib.util.module_from_spec(spec)
sys.modules["render_gitops"] = rg
spec.loader.exec_module(rg)


@pytest.fixture
def repo(tmp_path):
    for d in ("inventory", "customers", "products", "scripts/placement"):
        shutil.copytree(REPO / d, tmp_path / d, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    return tmp_path


def render(root):
    return {p.as_posix(): yaml.safe_load(t) for p, t in rg.Renderer(rg._load_repo(root)).render(root).items()}


def edit(path, fn):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


G = "argocd/generated"


def test_one_application_per_customer_env_target(repo):
    out = render(repo)
    tenants = sorted(p for p in out if "/tenants/" in p)
    # 2 customers x (dev, stage, uat, prod primary, prod DR)
    assert len(tenants) == 10
    products = sorted(p for p in out if "/products/" in p)
    # payment-api is the only GKE product; both customers have it
    assert len(products) == 10
    assert f"{G}/prod/products/acme-corp-payment-api-prod-dr.yaml" in out
    # Cloud Run and MIG products get no Application
    assert not any("reporting-engine" in p or "legacy-billing" in p for p in out)


def test_identity_and_data_names(repo):
    v = render(repo)[f"{G}/prod/products/acme-corp-payment-api-prod.yaml"]
    assert v["argocd"]["project"] == "acme-corp"
    assert v["database"] == {
        "enabled": True, "name": "acme_corp_prod", "schema": "payment",
        "user": "acme-corp-prod@pfx-compute-prod.iam",
        "impersonate": "acme-corp-prod@pfx-compute-prod.iam.gserviceaccount.com",
        "endpoint": "sql-prod-us-east1-01.write.example",
    }
    assert v["platformEnv"]["GCS_BUCKET"] == "pfx-acme-corp-payment-prod"
    assert v["image"] == {"registry": "us-docker.pkg.dev/pfx-platform-prod/products", "tag": "2.5.0"}
    assert v["ingress"] == {"hosts": ["acme-corp.platform.example"], "paths": ["/v1/payments"]}


def test_nonprod_uses_build_registry_and_connection_name(repo):
    v = render(repo)[f"{G}/devstage/products/acme-corp-payment-api-dev.yaml"]
    assert v["image"]["registry"] == "us-east1-docker.pkg.dev/pfx-platform-nonprod/products"
    assert v["database"]["endpoint"] == "pfx-data-nonprod:us-east1:sql-nonprod-us-east1-01"
    assert v["ingress"]["hosts"] == ["acme-corp.dev.platform.internal"]


def test_customer_override_and_dr_replicas(repo):
    out = render(repo)
    assert out[f"{G}/prod/products/acme-corp-payment-api-prod.yaml"]["replicas"] == {"min": 4, "max": 10}
    # warm standby: minimum replicas, no migration on the read-only replica side
    dr = out[f"{G}/prod/products/acme-corp-payment-api-prod-dr.yaml"]
    assert dr["replicas"] == {"min": 1, "max": 10} and dr["migration"] == {"enabled": False}
    assert dr["argocd"]["cluster"] == "prod-us-east1-01-dr"
    # hot standby keeps full size on the DR cluster
    assert out[f"{G}/prod/products/beta-industries-payment-api-prod-dr.yaml"]["replicas"]["min"] == 3


def test_dr_active_restores_full_size(repo):
    edit(repo / "inventory/clusters/prod-us-east1-01.yaml", lambda d: d.update(drActive=True))
    assert render(repo)[f"{G}/prod/products/acme-corp-payment-api-prod-dr.yaml"]["replicas"]["min"] == 4


def test_tenant_values(repo):
    t = render(repo)[f"{G}/prod/tenants/acme-corp-prod-dr.yaml"]
    assert t["regionRole"] == "dr"
    # DR cluster disks use the customer's key in the DR region
    assert "/locations/us-central1/keyRings/kr-acme-corp-prod/cryptoKeys/prod-data" in t["storage"]["kmsKey"]
    assert t["storage"]["reclaimPolicy"] == "Retain"
    assert t["serviceAccounts"] == [{"name": "payment", "gsa": "acme-corp-prod@pfx-compute-prod.iam.gserviceaccount.com"}]
    assert t["network"]["sqlCidrs"] == ["10.110.64.0/18", "10.111.64.0/18"]
    assert t["quota"]["persistentVolumeClaims"] == 0


def test_quota_covers_surge_and_sidecars(repo):
    q = render(repo)[f"{G}/prod/tenants/acme-corp-prod.yaml"]["quota"]
    # payment-api prod: max 10 -> 13 pods with surge; (1000m + 100m + 50m) x 13 + 4 job pods x 1150m
    assert q["pods"] == 17
    assert q["requestsCpu"] == f"{13 * 1150 + 4 * 1150}m"


def test_root_values(repo):
    root = render(repo)[f"{G}/prod/root.yaml"]
    assert [c["name"] for c in root["clusters"]] == [
        "prod-us-central1-01", "prod-us-central1-01-dr", "prod-us-east1-01", "prod-us-east1-01-dr"]
    assert root["gatewayHosts"] == ["*.platform.example"]
    assert root["egressHosts"] == ["api.stripe.example:443"]
    assert root["computeProject"] == "pfx-compute-prod"
    assert root["repoURL"].endswith("/platform-config.git")


def test_custom_domain_reaches_hosts_and_gateway(repo):
    edit(repo / "customers/acme-corp/customer.yaml",
         lambda d: d["spec"]["options"]["edge"].update(customDomain="api.acme.example"))
    out = render(repo)
    assert out[f"{G}/prod/products/acme-corp-payment-api-prod.yaml"]["ingress"]["hosts"] == [
        "acme-corp.platform.example", "api.acme.example"]
    assert "api.acme.example" in out[f"{G}/prod/root.yaml"]["gatewayHosts"]


@pytest.mark.parametrize("version,error", [
    ("2.3.0", "outside the support window"),
    ("2.5", "not semver"),
    ("2.5.0-rc.1", "pre-release"),
    ("2.5.0-acme-corp.1", "variantImages is off"),
])
def test_version_validation(repo, version, error):
    edit(repo / "customers/acme-corp/products.yaml",
         lambda d: d["spec"]["products"]["payment-api"]["versions"].update(prod=version))
    with pytest.raises(rg.RenderError, match=error):
        render(repo)


def test_variant_allowed_when_opted_in(repo):
    # beta-industries prod runs 2.5.0-beta-industries.1 with variantImages: true
    assert render(repo)[f"{G}/prod/products/beta-industries-payment-api-prod.yaml"]["image"]["tag"] == "2.5.0-beta-industries.1"


def test_unplaced_customer_is_an_error(repo):
    edit(repo / "customers/acme-corp/customer.yaml", lambda d: d["spec"].pop("placement"))
    with pytest.raises(rg.RenderError, match="run the placement job first"):
        render(repo)


def test_decommissioned_product_gets_no_application(repo):
    edit(repo / "customers/acme-corp/products.yaml",
         lambda d: d["spec"]["products"]["payment-api"].update(decommission=True))
    out = render(repo)
    assert not any(p.startswith(f"{G}/") and "acme-corp-payment-api" in p for p in out)
    assert render(repo)[f"{G}/prod/tenants/acme-corp-prod.yaml"]["serviceAccounts"] == []


def test_check_mode_detects_stale_and_orphans(repo):
    (repo / "products/payment-api/helm").mkdir(parents=True, exist_ok=True)
    (repo / "products/payment-api/helm/values.yaml").write_text("image: { name: payment-api }\n")
    assert rg.main(["--repo", str(repo)]) == 0
    assert rg.main(["--repo", str(repo), "--check"]) == 0
    orphan = repo / G / "prod/products/old-customer-payment-api-prod.yaml"
    orphan.write_text("x: 1\n")
    assert rg.main(["--repo", str(repo), "--check"]) == 1
    assert rg.main(["--repo", str(repo)]) == 0 and not orphan.exists()


def test_missing_product_values_layer(repo):
    shutil.rmtree(repo / "products/payment-api/helm")
    with pytest.raises(rg.RenderError, match="product values layer"):
        render(repo)
