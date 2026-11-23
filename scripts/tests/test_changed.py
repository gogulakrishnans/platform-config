"""Tests for changed-path detection (changed-states.py) and changed pins (changed-pins.py)."""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


cs = load("changed_states", "changed-states.py")
cp = load("changed_pins", "changed-pins.py")


def states(*files):
    return sorted(r.relative_to(cs.LAYERS).as_posix() for r in cs.affected(REPO, list(files)))


def test_customer_pr_touches_only_that_customer_and_its_edges():
    got = states("customers/acme-corp/products.yaml")
    assert got == sorted([
        "L2-edge/devstage-us-east1", "L2-edge/prod", "L2-edge/uat",
        *[f"L3-customer/acme-corp/{s}" for s in ("dev", "stage", "uat", "prod", "keys-nonprod", "keys-prod", "exchange")],
    ])
    assert not any("beta-industries" in s for s in got)


def test_customer_options_also_touch_the_prod_region_state():
    # hot-standby changes the DR cluster size in L2
    assert "L2-region/us-central1/prod" in states("customers/beta-industries/customer.yaml")


def test_helm_values_and_docs_touch_no_state():
    assert states("customers/acme-corp/helm/payment-api/values-prod.yaml", "helm/tenant/values.yaml",
                  "argocd/root/values.yaml", "docs/architecture.md", "products/payment-api/helm/values.yaml",
                  "products/payment-api/releases.yaml") == []


def test_catalog_change_touches_customers_that_use_it():
    got = states("products/legacy-billing/product.yaml")
    assert any(s.startswith("L3-customer/beta-industries/") for s in got)
    assert not any(s.startswith("L3-customer/acme-corp/") for s in got)


def test_module_change_fans_out_transitively():
    # kms is used by customer-keys (keys states) and by region-footprint (L2 region states)
    got = states("infrastructure/modules/kms/main.tf")
    assert "L3-customer/acme-corp/keys-prod" in got and "L2-region/us-east1/prod" in got
    assert "L3-customer/acme-corp/dev" not in got


def test_platform_inventory_change_is_everything_but_l0():
    got = states("inventory/regions.yaml")
    assert len(got) == len(cs.roots(REPO)) == 25 and not any(s.startswith("L0") for s in got)  # L0 is a script


def test_plan_orders_waves_and_reads_prefixes():
    plan = cs.plan(REPO, cs.affected(REPO, ["customers/acme-corp/products.yaml"]), batch_size=2)
    assert [w["wave"] for w in plan["waves"]] == list(cs.WAVES)
    env = next(w for w in plan["waves"] if w["wave"] == "L3-env")
    assert {s["prefix"]: s["pool"] for s in env["states"]} == {
        "L3/acme-corp/dev": "devstage", "L3/acme-corp/stage": "devstage", "L3/acme-corp/uat": "uat", "L3/acme-corp/prod": "prod"}
    assert [len(b) for b in env["batches"]] == [2, 2]


def test_changed_pins():
    before = {"acme-corp": {"payment-api": {"versions": {"dev": "2.6.0", "stage": "2.5.1", "uat": "2.5.1", "prod": "2.5.0"}}}}
    after = {
        "acme-corp": {
            "payment-api": {"versions": {"dev": "2.6.1", "stage": "2.5.1", "uat": "2.5.1", "prod": "2.5.0"}},
            "reporting-engine": {"versions": {"dev": "1.9.0", "stage": "1.9.0", "uat": "1.9.0", "prod": "1.9.0"}},
        }
    }
    got = cp.diff_pins(before, after, {"payment-api": "gke", "reporting-engine": "cloud-run"})
    assert [(g["product"], g["environment"], g["from"], g["to"], g["runtime"]) for g in got] == [
        ("payment-api", "dev", "2.6.0", "2.6.1", "gke"),
        *[("reporting-engine", e, None, "1.9.0", "cloud-run") for e in ("dev", "stage", "uat", "prod")],
    ]


def test_shards_partition_all_states(capsys):
    import json
    seen = []
    for i in range(7):
        cs.main(["--all", "--shard", f"{i}/7"])
        out = json.loads(capsys.readouterr().out)
        seen += [s["dir"] for w in out["waves"] for s in w["states"]]
        assert out["overMatrixLimit"] == []
    assert len(seen) == len(set(seen)) == 25
