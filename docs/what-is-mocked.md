# What is mocked

This repository is public and is validated without credentials. This page lists every placeholder,
and every item that can only be proven against a real environment.

## Placeholder identifiers
| Item | Placeholder | Real value lives in |
|---|---|---|
| Organization, folders, access policy | `000000000000`, `folders/1000000000xx` | private overlay of `inventory/platform.yaml` |
| Billing account | `000000-000000-000000` | private overlay |
| Project IDs and numbers | `pfx-*`, `2000000000xx` | private overlay |
| Bucket prefix | `pfx` | private overlay |
| Domains | `platform.example`, `platform.internal` | private overlay |
| Customers | `acme-corp`, `beta-industries` | `customers/` in the private config repo |
| GKE DNS endpoints in `inventory/clusters/*.yaml` | `<cluster>.<region>.gke.goog.example` | written by L2 after apply |
| Cloud SQL write endpoints in `inventory/sql/*.yaml` | `<instance>.write.example` | written by L2 after apply |
| UAT allowlist | RFC 5737 documentation ranges | private overlay |
| State bucket | `pfx-tfstate` (`infrastructure/backend.hcl.example`) | `infrastructure/backend.hcl` (git-ignored) |

## Validated offline
| Check | Tool |
|---|---|
| Terraform format, validate, unit tests with mock providers (both example customers end to end) | `scripts/terraform-check.py` |
| Static policy: mandatory labels, IAM allowlist, no public IPs, private clusters, Cloud Run ingress | `policy/check_terraform.py` (+ its own tests) |
| Lint | `tflint` (terraform + google rulesets) |
| Placement (capacity, alignment, quotas, write-back) | `pytest scripts/placement` |
| Database bootstrap SQL | `pytest db-bootstrap` |
| Generated layer directories in sync with the registry | `scripts/generate-layers.py --check` |

## Proven only against a real environment (rollout checklist)
| Item | Where it is tracked |
|---|---|
| Cloud SQL write endpoint resolution across Shared VPC projects (fallback config kept) | verification V9, DR tests |
| `cloudsqlsuperuser` granting IAM-user role membership to the bootstrap login | `db-bootstrap/README.md` |
| BigQuery cross-region copy into a CMEK DR dataset | verification V4 |
| ArgoCD through GKE DNS endpoints with VPC-SC enforced | verification V7 |
| CAS issuance config in a region other than the CA pool's | `modules/edge` (Dev/Stage certificates) |
| Quota IDs for quota preferences (`gcloud beta quotas info list`) | `modules/project-factory` |
| Isolation tests (customer A cannot reach customer B's data) | `tests/isolation/` (Phase 4) |
| DR replica lag and failover time per cell | quarterly DR tests |

## Known warnings
- **`remove_default_node_pool` deprecation warning:** google provider 8.x warns about this argument on GKE ≥ 1.36.4. The argument still works. Once the STABLE channel is on 1.36.4+, set `initial_node_count = 0` and drop the argument.
