# Status

| Phase | Scope | State |
|---|---|---|
| 1 | Design, three runtime diagrams, supporting diagrams, decisions, traceability, GCP verification | Complete, approved 2026-11-23 (with decision #22 changed to the DNS-based endpoint) |
| 2 | Terraform (D3), placement script, database bootstrap job | Complete (reviewed with Phase 3) |
| 3 | Helm charts and ArgoCD (D4) | **Complete, awaiting review** |
| 4 | Supporting artifacts, CI, repo packaging (D5) | Not started |

## Phase 2 outputs
- **Registry data:**
  - `inventory/{platform,regions}.yaml` and `inventory/{clusters,sql}/*.yaml`
  - catalog entries `products/{payment-api,reporting-engine,legacy-billing}`
  - the two example customers, with placement written by the job
- **Terraform:** `infrastructure/` contains 27 modules, the L0 script, L1, and the generated L2-region, L2-edge and L3 roots. See `infrastructure/README.md`.
- **Placement job:** `scripts/placement/` with its unit tests.
- **Database bootstrap job:** `db-bootstrap/` (Python Cloud Run job, Dockerfile, unit tests).
- **Static policy checks:** `policy/check_terraform.py` with its own tests.
- **Gate scripts:**
  - `scripts/terraform-check.py`
  - `scripts/generate-layers.py`
  - `.tflint.hcl`
- **Documentation:** `docs/what-is-mocked.md`, plus decisions #23-#25 and clarifications C13-C17.

## Phase 3 outputs
- **Charts:**
  - `helm/tenant`: namespace guardrails, StorageClass, NetworkPolicies, Istio isolation, KSAs
  - `helm/product-base`: Rollout or StatefulSet, migration hook, Cloud SQL proxy, Istio routing, AuthZ and egress, HPA and PDB
  - both charts have strict values schemas
- **Values layers:**
  - product: `products/payment-api/helm/values[-<env>].yaml`
  - customer: `customers/acme-corp/helm/payment-api/values-prod.yaml`
- **ArgoCD:**
  - `argocd/root`: app-of-apps per instance, with cluster Secrets, AppProjects and ApplicationSets
  - add-on charts: `argocd/addons/{mesh,platform}`
  - L1 installs the root Application and sets the prod `create-update` policy
- **GitOps index:** `scripts/render-gitops.py` writes `argocd/generated/`, with tests.
- **Gate:**
  - `scripts/gitops-check.py`
  - `policy/check_manifests.py`, with tests
- **Rendered output:** `examples/rendered/`.
- **Documentation:** architecture §14, clarifications C18–C20, decisions #26.

## Depth (per the brief)
| Component | Depth |
|---|---|
| L0 script, L1, L2 (clusters, SQL + replicas, LBs, exchange), L3 composition + data/identity modules, Cloud Run and MIG modules, placement, bootstrap job | Implemented |
| Seed-down function, sanitization SQL, promote-up, isolation tests, Packer/Ansible, DR runbooks, Falco/SCC | Phase 4 (skeleton + docs) |

## Open items
- **To verify on real GCP:** see `docs/what-is-mocked.md`.

## Repository rule
Nothing is pushed to GitHub until the owner explicitly requests it. Local commits only.
