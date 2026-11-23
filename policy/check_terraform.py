#!/usr/bin/env python3
"""Static policy checks for the Terraform code (repo gate, no credentials).

Rules (docs/architecture.md §2, §11, §16):
  LBL001  every labelable resource sets its labels attribute (mandatory labels, Decision 9)
  IAM001  no authoritative IAM (google_*_iam_binding / _iam_policy) anywhere
  IAM002  customer-scoped modules may grant project-level roles only from the allowlist, and the
          Cloud SQL roles only with an IAM condition (Decision 4)
  IAM003  no allUsers / allAuthenticatedUsers members
  NET001  instance templates have no access_config (no external IP)
  NET002  Cloud SQL instances have ipv4_enabled = false
  NET003  GKE clusters have private nodes and IP endpoints disabled
  NET004  buckets enforce public access prevention
  NET005  Cloud Run ingress is internal or internal-and-cloud-load-balancing
  NET006  external addresses only in edge/NAT modules

    python policy/check_terraform.py [paths...]     # default: infrastructure/
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import hcl2

ROOT = Path(__file__).resolve().parent.parent

# Resource type => attribute path (dotted, through nested blocks) that must hold the labels.
LABELED = {
    "google_project": "labels",
    "google_container_cluster": "resource_labels",
    "google_container_node_pool": "node_config.resource_labels",
    "google_sql_database_instance": "settings.user_labels",
    "google_storage_bucket": "labels",
    "google_bigquery_dataset": "labels",
    "google_pubsub_topic": "labels",
    "google_pubsub_subscription": "labels",
    "google_kms_crypto_key": "labels",
    "google_cloud_run_v2_service": "labels",
    "google_cloud_run_v2_job": "labels",
    "google_compute_region_instance_template": "labels",
    "google_compute_instance_template": "labels",
    "google_artifact_registry_repository": "labels",
    "google_gke_backup_backup_plan": "labels",
    "google_certificate_manager_certificate": "labels",
    "google_certificate_manager_certificate_map": "labels",
    "google_certificate_manager_certificate_map_entry": "labels",
    "google_certificate_manager_dns_authorization": "labels",
    "google_certificate_manager_certificate_issuance_config": "labels",
    "google_compute_global_address": "labels",
    "google_compute_address": "labels",
    "google_compute_global_forwarding_rule": "labels",
    "google_compute_forwarding_rule": "labels",
    "google_compute_security_policy": "labels",
    "google_dns_managed_zone": "labels",
    "google_privateca_ca_pool": "labels",
    "google_privateca_certificate_authority": "labels",
}
# (module, resource type) pairs exempt from LBL001. Keep empty unless an API cannot take labels.
LABEL_EXCEPTIONS: set[tuple[str, str]] = set()

CUSTOMER_MODULES = {
    "customer-infrastructure", "cloud-sql-database", "data-sharing", "customer-keys", "storage",
    "bigquery", "pubsub", "cloud-run-service", "mig-service", "backup-plan",
}
PROJECT_ROLE_ALLOWLIST = {
    "roles/cloudsql.client": True,  # True = condition required
    "roles/cloudsql.instanceUser": True,
    "roles/logging.logWriter": False,
    "roles/monitoring.metricWriter": False,
}
EXTERNAL_ADDRESS_MODULES = {"load-balancer", "network-region"}
CLOUD_RUN_INGRESS = {"INGRESS_TRAFFIC_INTERNAL_ONLY", "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"}


@dataclass
class Finding:
    rule: str
    file: Path
    resource: str
    message: str

    def __str__(self) -> str:
        return f"{self.rule} {self.file.relative_to(ROOT).as_posix()}: {self.resource}: {self.message}"


def first(block):
    """python-hcl2 represents nested blocks as lists of dicts."""
    if isinstance(block, list):
        return block[0] if block else None
    return block


def unwrap(value):
    """Older python-hcl2 releases wrap attribute values in a one-element list."""
    if isinstance(value, list) and len(value) == 1 and not isinstance(value[0], dict):
        return value[0]
    return value


def attr(body: dict, key: str, default=None):
    return unwrap(body.get(key, default))


def get_path(body: dict, path: str):
    cur = body
    for part in path.split("."):
        cur = first(cur)
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return unwrap(cur)


def has_dynamic(body: dict, name: str) -> bool:
    return any(name in d for d in body.get("dynamic", []) if isinstance(d, dict))


def module_of(path: Path) -> str:
    parts = path.relative_to(ROOT).parts
    return parts[parts.index("modules") + 1] if "modules" in parts else parts[-2]


def resources(path: Path):
    with path.open(encoding="utf-8") as fh:
        doc = hcl2.load(fh)
    for entry in doc.get("resource", []):
        for rtype, named in entry.items():
            for name, body in named.items():
                yield rtype, name, body


def check_file(path: Path) -> list[Finding]:
    out: list[Finding] = []
    mod = module_of(path)
    text = path.read_text(encoding="utf-8")
    for member in ("allUsers", "allAuthenticatedUsers"):
        if f'"{member}"' in text:
            out.append(Finding("IAM003", path, "-", f"{member} is never allowed"))

    for rtype, name, body in resources(path):
        rid = f"{rtype}.{name}"

        if rtype in LABELED and (mod, rtype) not in LABEL_EXCEPTIONS:
            if get_path(body, LABELED[rtype]) is None:
                out.append(Finding("LBL001", path, rid, f"missing {LABELED[rtype]} (mandatory labels)"))

        if rtype.endswith("_iam_binding") or rtype.endswith("_iam_policy"):
            out.append(Finding("IAM001", path, rid, "authoritative IAM is not allowed; use *_iam_member"))

        if rtype == "google_project_iam_member" and mod in CUSTOMER_MODULES:
            role = str(attr(body, "role", ""))
            if role.startswith("${"):
                # for_each over a literal set: inspect the for_each expression text
                expr = str(attr(body, "for_each", ""))
                roles = [r for r in PROJECT_ROLE_ALLOWLIST if r in expr]
                bad = "roles/" in expr and any(
                    tok.strip('"[]() ,') not in PROJECT_ROLE_ALLOWLIST
                    for tok in expr.replace("[", " ").replace("]", " ").split()
                    if tok.strip('"[]() ,').startswith("roles/")
                )
                if bad or not roles:
                    out.append(Finding("IAM002", path, rid, f"project-level role outside the allowlist: {expr}"))
                if any(PROJECT_ROLE_ALLOWLIST[r] for r in roles) and "condition" not in body:
                    out.append(Finding("IAM002", path, rid, "Cloud SQL project roles need an IAM condition"))
            elif role not in PROJECT_ROLE_ALLOWLIST:
                out.append(Finding("IAM002", path, rid, f"project-level role {role} outside the allowlist"))
            elif PROJECT_ROLE_ALLOWLIST[role] and "condition" not in body:
                out.append(Finding("IAM002", path, rid, f"{role} needs an IAM condition"))

        if rtype in ("google_compute_instance_template", "google_compute_region_instance_template"):
            for nic in body.get("network_interface", []):
                if "access_config" in nic or has_dynamic(nic, "access_config"):
                    out.append(Finding("NET001", path, rid, "external IP (access_config) on an instance template"))

        if rtype == "google_sql_database_instance":
            if str(get_path(body, "settings.ip_configuration.ipv4_enabled")).lower() != "false":
                out.append(Finding("NET002", path, rid, "ipv4_enabled must be false"))

        if rtype == "google_container_cluster":
            if str(get_path(body, "private_cluster_config.enable_private_nodes")).lower() != "true":
                out.append(Finding("NET003", path, rid, "private nodes required"))
            if str(get_path(body, "control_plane_endpoints_config.ip_endpoints_config.enabled")).lower() != "false":
                out.append(Finding("NET003", path, rid, "IP endpoints must be disabled (DNS endpoint only)"))

        if rtype == "google_storage_bucket" and attr(body, "public_access_prevention") != "enforced":
            out.append(Finding("NET004", path, rid, "public_access_prevention must be enforced"))

        if rtype == "google_cloud_run_v2_service" and attr(body, "ingress") not in CLOUD_RUN_INGRESS:
            out.append(Finding("NET005", path, rid, f"ingress {attr(body, 'ingress')} is not internal"))

        if rtype in ("google_compute_address", "google_compute_global_address"):
            external = attr(body, "address_type", "EXTERNAL") == "EXTERNAL" and "purpose" not in body
            if external and mod not in EXTERNAL_ADDRESS_MODULES:
                out.append(Finding("NET006", path, rid, "external address outside the edge/NAT modules"))
    return out


def main(argv: list[str]) -> int:
    targets = [Path(a).resolve() for a in argv] or [ROOT / "infrastructure"]
    files = sorted({f for t in targets for f in ([t] if t.is_file() else t.rglob("*.tf")) if ".terraform" not in f.parts})
    findings = [f for path in files for f in check_file(path)]
    for f in findings:
        print(f)
    print(f"{len(files)} files checked, {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
