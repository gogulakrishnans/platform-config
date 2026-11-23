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
| GitOps index in sync; version window, variant opt-in, no pre-releases in prod | `scripts/render-gitops.py --check`, `pytest scripts/tests` |
| Helm lint (every chart with every values set it is deployed with), ApplicationSet expansion, `helm template` of every in-repo Application, kubeconform `-strict` against Kubernetes 1.33 + CRD schemas | `scripts/gitops-check.py` |
| Rendered-manifest policy: mandatory labels, Pod Security `restricted`, resources, pinned images, prod by digest | `policy/check_manifests.py` (+ its own tests) |
| Registry schemas and composition rules (catalog, customers, promoted prod pins) | `scripts/validate-registry.py` (+ tests) |
| Changed-path detection, apply waves, drift shards, changed pins | `scripts/changed-states.py`, `scripts/changed-pins.py` (+ tests) |
| Seed-down and import plans, sanitize/verify/role-mapping rendering, promote-up rules | `pytest data-flows` |
| Isolation case generation | `pytest tests/isolation` (offline part) |
| Packer template syntax and format | `packer validate -syntax-only`, `packer fmt -check` (CI: full `packer validate`) |

## Proven only against a real environment (rollout checklist)
| Item | Where it is tracked |
|---|---|
| Cloud SQL write endpoint resolution across Shared VPC projects (fallback config kept) | verification V9, DR tests |
| `cloudsqlsuperuser` granting IAM-user role membership to the bootstrap login | `db-bootstrap/README.md` |
| BigQuery cross-region copy into a CMEK DR dataset | verification V4 |
| ArgoCD through GKE DNS endpoints with VPC-SC enforced | verification V7 |
| CAS issuance config in a region other than the CA pool's | `modules/edge` (Dev/Stage certificates) |
| Quota IDs for quota preferences (`gcloud beta quotas info list`) | `modules/project-factory` |
| ApplicationSet expansion by the real controller. CI uses an emulator for the goTemplate subset the templates use: dotted paths and `index`. The emulator fails on anything else. | `scripts/gitops-check.py` |
| Cloud SQL Auth Proxy connecting by write-endpoint DNS name, with IAM login and impersonation | `helm/product-base` (proxy sidecar) |
| Managed Istio: `image: auto` gateway injection, native sidecars, a Job without a sidecar reaching Cloud SQL | `argocd/addons/mesh`, migration Job |
| Merging `VirtualService` across products on the same customer host (non-overlapping path prefixes) | `helm/product-base` |
| `argocd-k8s-auth gcp` against the DNS endpoint with the system CA bundle (no `caData`) | `argocd/root/templates/clusters.yaml`, verification V7 |
| Managed Prometheus query frontend authorized through the Workload Identity principal | `argocd/addons/platform`, L1 `gmp_frontend` |
| Every workflow that needs GCP: apply waves, drift, L4 delivery, image promotion, promote-up, isolation probes | `.github/workflows/`; GitHub Environments, variables and self-hosted pools are set up during the rollout |
| GitHub configuration: environments (`tf-<pool>`, `tf-<pool>-readonly`, `deliver-*`, `promote-*`, `build`, `isolation-*`) with reviewers and variables, branch protection, teams in CODEOWNERS | Repository settings (not code) |
| `actionlint` and `gitleaks` | Run in CI only (container images); not run locally while building this repo |
| `ansible-lint` and full `packer validate` (plugins) | Run in CI only |
| Seed-down executor (Admin API calls, SQL over the connector), BigQuery `EXPORT DATA`, Storage Transfer jobs, Eventarc trigger for the import job | `data-flows/` (skeleton) |
| Promote-up: the deployer identity's write access to `promote/` in the env buckets, and how the product admin export/import endpoints authenticate platform callers | `data-flows/promote-up`, product API contract |
| SCC activation and organization-level Data Access audit logs | `docs/security-operations.md` (rollout steps) |
| Isolation tests (customer A cannot reach customer B's data) | `tests/isolation/` (Phase 4) |
| DR replica lag and failover time per cell | quarterly DR tests |

## Placeholder images and endpoints (Helm)
| Item | Placeholder |
|---|---|
| Product images and promoted digests | `products/*/releases.yaml` hold placeholder digests (sha256 of `<product>:<version>`); real ones are written by `promote-image.yml` |
| GitHub org and teams | `example-org`, `@example-org/*` in CODEOWNERS and the Bitbucket template |
| JWT issuer | `https://auth.platform.example` |
| Repository URL in ArgoCD | `https://github.com/example-org/platform-config.git` (`inventory/platform.yaml` `github`) |

## Known warnings
- **`remove_default_node_pool` deprecation warning:** google provider 8.x warns about this argument on GKE ≥ 1.36.4. The argument still works. Once the STABLE channel is on 1.36.4+, set `initial_node_count = 0` and drop the argument.
