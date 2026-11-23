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
| Rendered-manifest policy: mandatory labels, Pod Security `restricted`, resources, pinned images | `policy/check_manifests.py` (+ its own tests) |

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
| Isolation tests (customer A cannot reach customer B's data) | `tests/isolation/` (Phase 4) |
| DR replica lag and failover time per cell | quarterly DR tests |

## Placeholder images and endpoints (Helm)
| Item | Placeholder |
|---|---|
| Product image `payment-api` | Built by the product pipeline (Phase 4). Prod uses `image.digest` after promotion. |
| JWT issuer | `https://auth.platform.example` |
| Repository URL in ArgoCD | `https://github.com/example-org/platform-config.git` (`inventory/platform.yaml` `github`) |

## Known warnings
- **`remove_default_node_pool` deprecation warning:** google provider 8.x warns about this argument on GKE ≥ 1.36.4. The argument still works. Once the STABLE channel is on 1.36.4+, set `initial_node_count = 0` and drop the argument.
