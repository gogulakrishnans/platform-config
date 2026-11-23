# Runbook: Day-2 operations

## Add a product to a customer (< 20 min)
1. In a PR, add the product to `customers/<id>/products.yaml`, with a pin per environment.
2. The validator checks:
   - the product is in the catalog
   - its dependencies are enabled (for example, `reporting-engine` needs `payment-api`)
   - Pub/Sub subscribers have their publisher enabled
   - the version window
   - the prod pin is promoted
3. `customer-pr` regenerates the GitOps files. The summary lists the customer's L3 states and the edge states.
4. After merge:
   - L3 adds the schema, bucket, dataset and topics the catalog requires, then the bootstrap job creates the schema.
   - Then either ArgoCD deploys the release (GKE) or `l4-delivery` deploys the service or MIG.

## Upgrade a version
- **One customer:** change the pin in `products.yaml`. `l4-delivery` and ArgoCD roll it out progressively, with automatic rollback:
  - GKE: canary with analysis
  - Cloud Run: 10 → 25 → 50 → 100%
  - MIG: 10% canary
- **Fleet rollout (waves, architecture §7):** a bot opens pin PRs in batches: canary customers → 10% → 50% → all. Each batch merges only after the previous batch's SLO checks pass.
- **Prod pins** must first be promoted by digest:
  1. The product release runs `build-sign`, then dispatches `promote-image.yml`.
  2. A release manager approves it.
  3. The PR that updates `products/<p>/releases.yaml` is merged.
- **Breaking schema changes** use a blue-green Rollout, sequenced per customer.

## Remove a product (phased decommission)
| Phase | Change | Effect |
|---|---|---|
| 1 | `decommission: true` on the product in `products.yaml` | No Application, service or MIG is rendered for it. Prod ApplicationSets are create/update-only, so the prod Application is removed by hand (step 2). |
| 2 | Platform engineer: `argocd app delete <id>-<product>-prod --cascade` (and `-dr`); scale Cloud Run to 0 and the MIG to 0 | Traffic stops |
| 3 | Retention period (contract; default 30 days) | Data kept; the env identity's grants on the product's containers are removed by L3 |
| 4 | Approvals: `platform-admin` and `customer-success` | Deletion window opens |
| 5 | Remove the product from `products.yaml` | L3 switches `deletion_policy` to `DELETE` and drops the bucket, dataset and topics; the bootstrap job drops the schema |

## Offboard a customer
1. Decommission every product as above.
2. Remove the customer's files:
   - its tenant files are removed from `argocd/generated/`
   - in non-prod, ArgoCD prunes the namespaces
   - in prod, delete the Applications by hand: `Delete=false` keeps each namespace until you delete it explicitly
3. Apply the L3 states with `-destroy`, in reverse order: `exchange` → environments → keys.
   - Keys are scheduled for destruction, with KMS's 30-day delay.
4. Remove the customer's directory from `infrastructure/layers/L3-customer/` (generate-layers).
5. Confirm by label that nothing is left: `gcloud asset search-all-resources --query="labels.customer=<id>"`.

## Drift
- `drift.yml` plans one seventh of all states every night, using read-only identities, so every state is checked weekly. A non-empty plan fails that state's job.
- To fix drift:
  - **Manual change:** revert it in the console, or capture it in Git and apply.
  - **Intended change:** a PR. Never apply from a laptop.
- ArgoCD self-heals Kubernetes drift. `managed-by` labels show which tool owns a resource.

At 500 customers there are about 3,500 states. Run two shards per night (`--shard i/14`) to stay under the 256-job matrix limit.

## Region failover and capacity
See [dr.md](dr.md) and [capacity.md](capacity.md).
