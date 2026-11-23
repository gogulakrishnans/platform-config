"""Offline unit tests for the placement job (no GCP access)."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import placement as pl  # noqa: E402

REPO = HERE.parents[2]


# ----------------------------------------------------------------------------- fixtures


def _w(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _cluster(name, group, region, cap, sql=None, status="active"):
    d = {"name": name, "group": group, "region": region, "status": status, "capacity": {"maxCustomers": cap}}
    d["sqlInstances"] = [sql] if sql else []
    if group == "prod":
        d["drCluster"] = {"name": f"{name}-dr", "region": "r2"}
    return d


def _sql(name, side, region, cap, status="active"):
    return {"name": name, "side": side, "region": region, "status": status, "capacity": {"maxCustomers": cap}}


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    """A small synthetic repo: region r1 (active, pair r2), r2 (active), r3 (reserved)."""
    inv = tmp_path / "inventory"
    _w(inv / "platform.yaml", {"bucketPrefix": "pfx"})
    _w(inv / "regions.yaml", {"regions": [
        {"name": "r1", "status": "active", "drPair": "r2", "quotas": {"cloudRunServices": {"devstage": 10, "uat": 10, "prod": 10}}},
        {"name": "r2", "status": "active", "drPair": "r1", "quotas": {"cloudRunServices": {"devstage": 10, "uat": 10, "prod": 10}}},
        {"name": "r3", "status": "reserved", "drPair": "r1"},
    ]})
    for c in [
        _cluster("devstage-r1-01", "devstage", "r1", 2),
        _cluster("devstage-r1-02", "devstage", "r1", 3),
        _cluster("uat-r1-01", "uat", "r1", 5),
        _cluster("prod-r1-01", "prod", "r1", 2, sql="sql-prod-r1-01"),
        _cluster("prod-r1-02", "prod", "r1", 2, sql="sql-prod-r1-02"),
        _cluster("devstage-r2-01", "devstage", "r2", 5),
        _cluster("uat-r2-01", "uat", "r2", 5),
        _cluster("prod-r2-01", "prod", "r2", 5, sql="sql-prod-r2-01"),
    ]:
        _w(inv / "clusters" / f"{c['name']}.yaml", c)
    for s in [
        _sql("sql-nonprod-r1-01", "nonprod", "r1", 5),
        _sql("sql-prod-r1-01", "prod", "r1", 2),
        _sql("sql-prod-r1-02", "prod", "r1", 2),
        _sql("sql-nonprod-r2-01", "nonprod", "r2", 5),
        _sql("sql-prod-r2-01", "prod", "r2", 5),
    ]:
        _w(inv / "sql" / f"{s['name']}.yaml", s)
    _w(tmp_path / "products" / "api" / "product.yaml", {"spec": {"runtime": {"type": "gke"}}})
    _w(tmp_path / "products" / "run" / "product.yaml", {"spec": {"runtime": {"type": "cloud-run"}}})
    (tmp_path / "customers").mkdir()
    return tmp_path


def add_customer(root: Path, name: str, region: str = "r1", products=("api",), placement=None, **options):
    spec = {"region": {"primary": region}, "options": {"isolation": "shared", **options}}
    if placement:
        spec["placement"] = placement
    _w(root / "customers" / name / "customer.yaml", {"metadata": {"name": name}, "spec": spec})
    _w(root / "customers" / name / "products.yaml", {"spec": {"products": {p: {} for p in products}}})


# ----------------------------------------------------------------------------- tests


def test_places_all_groups_in_primary_region(repo_dir):
    add_customer(repo_dir, "acme")
    p = pl.place(pl.Repo.load(repo_dir), "acme")
    assert set(p) == {"devstage", "uat", "prod"}
    for group in ("devstage", "uat", "prod"):
        assert pl.Repo.load(repo_dir).clusters[p[group]["cluster"]]["region"] == "r1"


def test_most_headroom_wins(repo_dir):
    add_customer(repo_dir, "acme")
    p = pl.place(pl.Repo.load(repo_dir), "acme")
    assert p["devstage"]["cluster"] == "devstage-r1-02"  # cap 3 > cap 2


def test_tie_breaks_on_lowest_name(repo_dir):
    add_customer(repo_dir, "acme")
    p = pl.place(pl.Repo.load(repo_dir), "acme")
    assert p["prod"]["cluster"] == "prod-r1-01"  # both prod cells have headroom 2


def test_prod_database_on_the_cells_own_instance_and_dr_aligned(repo_dir):
    add_customer(repo_dir, "acme")
    p = pl.place(pl.Repo.load(repo_dir), "acme")
    assert p["prod"]["sqlInstance"] == "sql-prod-r1-01"
    assert p["prod"]["drCluster"] == "prod-r1-01-dr"


def test_nonprod_databases_share_one_instance_in_region(repo_dir):
    add_customer(repo_dir, "acme")
    p = pl.place(pl.Repo.load(repo_dir), "acme")
    assert p["devstage"]["sqlInstance"] == p["uat"]["sqlInstance"] == "sql-nonprod-r1-01"


def test_existing_placement_is_kept(repo_dir):
    existing = {
        "devstage": {"cluster": "devstage-r1-01", "sqlInstance": "sql-nonprod-r1-01"},
        "uat": {"cluster": "uat-r1-01", "sqlInstance": "sql-nonprod-r1-01"},
        "prod": {"cluster": "prod-r1-02", "sqlInstance": "sql-prod-r1-02", "drCluster": "prod-r1-02-dr"},
    }
    add_customer(repo_dir, "acme", placement=existing)
    assert pl.place(pl.Repo.load(repo_dir), "acme") == existing


def test_full_cell_is_skipped(repo_dir):
    full = {"prod": {"cluster": "prod-r1-01", "sqlInstance": "sql-prod-r1-01"}}
    add_customer(repo_dir, "a1", placement=full)
    add_customer(repo_dir, "a2", placement=full)
    add_customer(repo_dir, "new")
    assert pl.place(pl.Repo.load(repo_dir), "new")["prod"]["cluster"] == "prod-r1-02"


def test_cell_with_full_sql_instance_is_skipped(repo_dir):
    # prod-r1-01 cluster still has headroom (cap 2, 1 used), but its instance (cap 1) is full.
    _w(repo_dir / "inventory" / "sql" / "sql-prod-r1-01.yaml", _sql("sql-prod-r1-01", "prod", "r1", 1))
    add_customer(repo_dir, "a1", placement={"prod": {"cluster": "prod-r1-01", "sqlInstance": "sql-prod-r1-01"}})
    add_customer(repo_dir, "new")
    assert pl.place(pl.Repo.load(repo_dir), "new")["prod"]["cluster"] == "prod-r1-02"


def test_no_headroom_requests_a_new_cell(repo_dir):
    for i, cell in enumerate(["prod-r1-01", "prod-r1-01", "prod-r1-02", "prod-r1-02"]):
        add_customer(repo_dir, f"c{i}x", placement={"prod": {"cluster": cell, "sqlInstance": cell.replace("prod-", "sql-prod-")}})
    add_customer(repo_dir, "new")
    with pytest.raises(pl.CapacityRequest) as e:
        pl.place(pl.Repo.load(repo_dir), "new")
    assert (e.value.kind, e.value.group, e.value.region) == ("cell", "prod", "r1")


def test_inactive_cells_are_ignored(repo_dir):
    c = _cluster("devstage-r1-03", "devstage", "r1", 99, status="provisioning")
    _w(repo_dir / "inventory" / "clusters" / "devstage-r1-03.yaml", c)
    add_customer(repo_dir, "acme")
    assert pl.place(pl.Repo.load(repo_dir), "acme")["devstage"]["cluster"] != "devstage-r1-03"


def test_region_not_provisioned(repo_dir):
    add_customer(repo_dir, "acme", region="r3")
    with pytest.raises(pl.PlacementError, match="region not provisioned"):
        pl.place(pl.Repo.load(repo_dir), "acme")


def test_unknown_region(repo_dir):
    add_customer(repo_dir, "acme", region="mars-1")
    with pytest.raises(pl.PlacementError, match="region not provisioned"):
        pl.place(pl.Repo.load(repo_dir), "acme")


@pytest.mark.parametrize("bad", ["A-corp", "ab", "x" * 21, "acme-", "1acme", "acme_corp"])
def test_invalid_customer_ids(repo_dir, bad):
    add_customer(repo_dir, bad)
    with pytest.raises(pl.PlacementError, match="invalid customer ID"):
        pl.place(pl.Repo.load(repo_dir), bad)


def test_dedicated_customers_are_not_placed_in_shared_cells(repo_dir):
    add_customer(repo_dir, "acme", isolation="dedicated")
    assert pl.place(pl.Repo.load(repo_dir), "acme") == {"dedicated": True}


def test_cloud_run_quota_counts_dr_copies_in_pair_region(repo_dir):
    # Quota 10, threshold 8. Each customer with 2 cloud-run products adds 2 prod services in r1
    # and 2 DR copies in r2. A customer homed in r2 adds 2 more in r2.
    for i in range(3):
        add_customer(repo_dir, f"r1c{i}x", region="r1", products=("run",))
    add_customer(repo_dir, "r2home", region="r2", products=("run", "api"))
    repo = pl.Repo.load(repo_dir)
    assert pl.cloud_run_services(repo, "r2", "prod") == 3 + 1


def test_cloud_run_quota_exceeded_requests_quota(repo_dir):
    for i in range(4):  # devstage: 4 customers x 1 product x 2 envs = 8 = 80% of 10
        add_customer(repo_dir, f"c{i}x", products=("run",))
    add_customer(repo_dir, "new", products=("run",))
    with pytest.raises(pl.CapacityRequest) as e:
        pl.place(pl.Repo.load(repo_dir), "new")
    assert e.value.kind == "quota"


def test_write_back_replaces_block_and_keeps_comments(repo_dir, tmp_path):
    target = tmp_path / "customer.yaml"
    shutil.copy(REPO / "customers" / "acme-corp" / "customer.yaml", target)
    p = {
        "devstage": {"cluster": "d", "sqlInstance": "s"},
        "uat": {"cluster": "u", "sqlInstance": "s"},
        "prod": {"cluster": "p", "sqlInstance": "sp", "drCluster": "p-dr"},
    }
    assert pl.write_back(target, p) is not None
    text = target.read_text()
    assert "# the only onboarding input" in text
    assert yaml.safe_load(text)["spec"]["placement"] == p
    assert pl.write_back(target, p) is False  # idempotent


def test_cli_exit_codes(repo_dir):
    add_customer(repo_dir, "acme", region="r3")
    assert pl.main(["--repo", str(repo_dir), "--customer", "acme"]) == 2


def test_example_customers_in_this_repo_are_placed_consistently():
    """The committed placements must equal what the job computes from the committed inventory."""
    repo = pl.Repo.load(REPO)
    for name, cust in repo.customers.items():
        committed = cust["spec"].get("placement")
        assert committed, f"{name}: run scripts/placement/placement.py --all --write"
        assert pl.place(repo, name) == committed
