# Status

| Phase | Scope | State |
|---|---|---|
| 1 | Design, three runtime diagrams, supporting diagrams, decisions, traceability, GCP verification | Complete, approved 2026-11-23 (with decision #22 changed to the DNS-based endpoint) |
| 2 | Terraform (D3), placement script, database bootstrap job | Complete (reviewed with Phase 3) |
| 3 | Helm charts and ArgoCD (D4) | Complete, approved 2026-11-23 |
| 4 | Supporting artifacts, CI, repo packaging (D5) | **Complete locally, awaiting review; push pending the owner's go-ahead** |

## Phase 2 outputs
- **Registry data:**
  - `inventory/{platform,regions}.yaml` and `inventory/{clusters,sql}/*.yaml`
  - catalog entries `products/{payment-api,reporting-engine,legacy-billing}`
  - the two example customers, with placement written by the job
- **Terraform:** `infrastructure/` contains 25 modules, the L0 script, L1, and the generated L2-region, L2-edge and L3 roots. See `infrastructure/README.md`.
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

## Phase 4 outputs
- **Catalog (item 10):**
  - schemas in `products/_schema` and `customers/_schema`
  - a 4th product, `document-index` (GKE, stateful)
  - `scripts/validate-registry.py`, with tests
  - `docs/catalog.md`: requirement matrix, dependency graph, version matrix
- **Data flows (item 11):** in `data-flows/`. Seed-down function and import job; sanitize, verify and role-mapping SQL; BigQuery anonymization; promote-up. Planning logic has tests.
- **CI/CD (item 12):**
  - `.github/workflows/`: repo-gate, customer-pr, terraform-apply (waves), drift, l4-delivery, promote-image, promote-up, isolation-tests
  - `ci-templates/`: GitHub composite action, Bitbucket template, delivery and promotion scripts
  - `scripts/changed-states.py`, `scripts/changed-pins.py` and `scripts/bootstrap-args.py`
  - promoted digests in `products/*/releases.yaml`
- **Runbooks (item 13):** `docs/runbooks/` (onboarding, Day 2, capacity and regions, DR, break-glass) and `docs/security-operations.md` (Falco, SCC).
- **Other components:**
  - Instance Group path: `packer/`, `ansible/`
  - isolation tests: `tests/isolation/`
- **Roadmap (item 14):** `docs/roadmap.md`.
- **Packaging (item 15):** `README.md`, `CONTRIBUTING.md`, `LICENSE` (MIT), `docs/checklist.md`, `.gitleaks.toml`, Dependabot, CODEOWNERS.
- **Fixes found while building Phase 4:**
  - DR push subscriptions now follow `drActive`.
  - The DR cluster now scales on failover.
  - Shared-bucket grants now apply for promote-up.
  - Placement write-back now writes LF line endings.

## Depth (per the brief)
| Component | Depth |
|---|---|
| L0 script, L1, L2 (clusters, SQL + replicas, LBs, exchange), L3 composition + data/identity modules, Cloud Run and MIG modules, placement, bootstrap job | Implemented |
| Seed-down function, sanitization SQL, promote-up, isolation tests | Skeleton + docs; planning logic unit-tested |
| Packer/Ansible | One minimal working example (`legacy-billing`) |
| DR runbooks, Falco/SCC | Documentation + configuration |
| CI workflows | Implemented; apply, delivery, promotion and isolation paths need the real environment |

## Open items
- **To verify on real GCP:** see `docs/what-is-mocked.md`.

## Repository rule
Nothing is pushed to GitHub until the owner explicitly requests it. Local commits only.
