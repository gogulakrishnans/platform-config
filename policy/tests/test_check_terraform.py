"""The policy checker must catch each violation class (and pass the real repository)."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import check_terraform as ct  # noqa: E402


def findings(tmp_path: Path, module: str, hcl: str) -> set[str]:
    path = ct.ROOT / "infrastructure" / "modules" / module / "_policy_test.tf"
    path.write_text(textwrap.dedent(hcl), encoding="utf-8")
    try:
        return {f.rule for f in ct.check_file(path)}
    finally:
        path.unlink()


def test_repository_is_clean():
    assert ct.main([]) == 0


@pytest.mark.parametrize("module, hcl, rule", [
    ("storage", 'resource "google_storage_bucket" "b" {\n  name = "x"\n  public_access_prevention = "enforced"\n}\n', "LBL001"),
    ("storage", 'resource "google_storage_bucket" "b" {\n  labels = var.labels\n  public_access_prevention = "inherited"\n}\n', "NET004"),
    ("storage", 'resource "google_storage_bucket_iam_binding" "b" {\n  members = []\n}\n', "IAM001"),
    ("storage", 'resource "google_storage_bucket_iam_member" "b" {\n  member = "allUsers"\n}\n', "IAM003"),
    ("customer-infrastructure", 'resource "google_project_iam_member" "x" {\n  role = "roles/editor"\n}\n', "IAM002"),
    ("cloud-sql-database", 'resource "google_project_iam_member" "x" {\n  role = "roles/cloudsql.client"\n}\n', "IAM002"),
    ("mig-service", textwrap.dedent('''\
        resource "google_compute_region_instance_template" "t" {
          labels = var.labels
          network_interface {
            access_config {}
          }
        }
        '''), "NET001"),
    ("cloud-sql-instance", textwrap.dedent('''\
        resource "google_sql_database_instance" "i" {
          settings {
            user_labels = var.labels
            ip_configuration {
              ipv4_enabled = true
            }
          }
        }
        '''), "NET002"),
    ("cloud-run-service", 'resource "google_cloud_run_v2_service" "s" {\n  labels = var.labels\n  ingress = "INGRESS_TRAFFIC_ALL"\n}\n', "NET005"),
    ("storage", 'resource "google_compute_address" "a" {\n  labels = var.labels\n}\n', "NET006"),
])
def test_violation_is_detected(tmp_path, module, hcl, rule):
    assert rule in findings(tmp_path, module, hcl)


def test_conditional_cloudsql_grant_is_allowed(tmp_path):
    hcl = textwrap.dedent('''\
        resource "google_project_iam_member" "x" {
          role = "roles/cloudsql.instanceUser"
          condition {
            title      = "only-one"
            expression = "true"
          }
        }
        ''')
    assert findings(tmp_path, "cloud-sql-database", hcl) == set()
