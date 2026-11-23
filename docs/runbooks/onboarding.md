# Runbook: onboard a customer (4 environments)

**Target:** under 30 minutes from merge to a customer serving in all four environments. The PR sets
only `region.primary`.
**Who:** Customer Success opens the PR. A platform engineer approves it. The pipelines do the rest.

| # | Step | Who / what | Time |
|---|---|---|---|
| 1 | Open the PR | Customer Success | 5 min |
| 2 | Validation, placement, generated files (bot commit) | `repo-gate`, `customer-pr` | 3–5 min |
| 3 | Review and merge | Platform engineer | (review) |
| 4 | Keys, 4 environment states, bootstrap, exchange | `terraform-apply` waves 3–5 | ~12 min |
| 5 | Edge: certificate, host rules, DNS | `terraform-apply` wave 6 | ~5 min (certificate issuance can take up to 15 min more for public hosts) |
| 6 | Kubernetes: tenant namespaces, product releases | ArgoCD (automatic) | ~5–10 min |
| 7 | Cloud Run and MIG versions | `l4-delivery` | ~5–10 min (in parallel with 6) |
| 8 | Smoke test and isolation sample | `isolation-tests` (`workflow_dispatch`) | ~5 min |

## 1. Open the PR
Create `customers/<id>/` with three files. The schemas are in [`customers/_schema`](../../customers/_schema).

```yaml
# customer.yaml: only region.primary is required. Options default off.
apiVersion: platform.example/v1
kind: CustomerConfig
metadata: { name: gamma-labs }                     # ^[a-z][a-z0-9-]{1,18}[a-z0-9]$
spec:
  displayName: Gamma Labs
  accountId: CUST-000003
  region: { primary: us-east1 }
```
```yaml
# products.yaml: one pin per environment, within the N-2 support window; prod pins must be promoted.
apiVersion: platform.example/v1
kind: CustomerProducts
metadata: { name: gamma-labs }
spec:
  products:
    payment-api: { versions: { dev: 2.6.0, stage: 2.6.0, uat: 2.6.0, prod: 2.5.0 } }
```
```yaml
# data-sharing.yaml
apiVersion: platform.example/v1
kind: DataSharingPolicy
metadata: { name: gamma-labs }
spec: { sharedReference: false, promoteUp: { enabled: false }, seedDown: { targets: [] } }
```

## 2. Validation and placement (automatic)
- `repo-gate` runs every offline check, including on fork PRs.
- `customer-pr` (same-repo branches only) does the following, then commits the results to the PR:
  - `validate-registry.py`: schemas, support window, dependencies, promoted prod pins
  - placement: the cluster and SQL instance with the most headroom in the region, for each group
  - `generate-layers.py`, `render-gitops.py` and `catalog-report.py`

  The job summary lists the Terraform states that will be applied after merge.
- **If placement exits 3 (capacity request):** no cell has room. Follow [capacity.md](capacity.md), then re-run the job.

## 3. Review checklist
- [ ] The placement block was written by the bot. Dev and stage share the Dev/Stage cell and remain separate environments (namespaces, databases, identities and buckets per environment).
- [ ] Options that cost money (`dr: hot-standby`, `isolation: dedicated`) are approved in the contract.
- [ ] The plan summary lists only this customer's states, plus the edge states.

## 4–5. After merge (automatic, `terraform-apply`)
Waves: `keys-nonprod`/`keys-prod` → `dev`/`stage`/`uat`/`prod` → database bootstrap job per environment → `exchange` → `L2-edge`.
- `tf-prod` asks the prod approvers before the prod states apply.

## 6–7. Delivery (automatic)
- **ArgoCD** picks up the new files under `argocd/generated/`.
  - It creates the customer's AppProject, `tenant-<id>-<env>` (plus `-dr` in prod) and `<id>-<product>-<env>`.
  - The migration Job runs first, then the Rollout.
- **`l4-delivery`** deploys the Cloud Run and MIG pins.

## 8. Verify
```bash
gh workflow run isolation-tests.yml -f environment=uat
```
- Each host should answer: `https://<id>.platform.example`, `https://<id>.uat.platform.example`, and from inside the VPC `<id>.dev|stage.platform.internal`.
- Each `/healthz/ready` should return 200.

## Rollback
- Revert the PR. Prod ApplicationSets never delete Applications, and prod data is `PREVENT`-protected.
- Removing a customer that has data is offboarding: see [day-2.md](day-2.md#offboard-a-customer).
